# Peel backend

Peel checks whether a medicine may be counterfeit, substandard or subject to a recall. A user
photographs the **bottle** label and the pill **imprint** (read by GPT-4o vision), a
phone-attached spectrometer analyses the **pill** itself (mocked in this build — see
[`mock-hardware-analysis.md`](mock-hardware-analysis.md)), and this backend's **evidence layer**
turns those three observations plus live web research into a sourced, guardrailed report. This
document covers only that evidence layer: Elasticsearch, the seed corpus, retrieval, the Elastic
Agent Builder research agent, and the scan pipeline that ties them together.

Three capabilities make up the layer:

1. **A pre-seeded regulatory corpus** — FDA, WHO, Health Canada, MHRA and NAFDAC recalls/alerts,
   the NLM Pillbox pill-imprint archive, and the openFDA NDC directory, fetched once by
   `peel-seed` over plain HTTP (no Firecrawl, no LLM) and indexed into Elasticsearch.
2. **A research agent with live web data** — an Elastic Agent Builder agent with eight ES|QL
   tools investigates a scan, backed by Firecrawl web search whose results are indexed back into
   Elasticsearch (so the next scan of the same product finds them without spending a credit),
   temporal decay favouring recent records without erasing old ones, and metadata pre-filtering
   pushed into the vector search itself rather than applied after it.
3. **Past scans** — every scan (label reading, pill identification, hardware result, evidence
   pack and final report) is stored in `peel-scans`, queryable by device, lot or NDC.

## Contents

[Architecture and scan lifecycle](#architecture-and-scan-lifecycle) ·
[Setup](#setup) · [Seeding](#seeding) · [Index reference](#index-reference) ·
[Retrieval](#retrieval) · [Agent Builder](#agent-builder) · [HTTP API](#http-api) ·
[Firecrawl budget and caching](#firecrawl-budget-and-caching) ·
[Safety and privacy](#safety-and-privacy) ·
[Testing and verification](#testing-and-verification) · [Demo script](#demo-script) ·
[Known limitations and future work](#known-limitations-and-future-work)

## Architecture and scan lifecycle

```
 photo(bottle) ──▶ POST /photo-identification/bottle  (GPT-4o vision)
 photo(imprint) ─▶ POST /photo-identification/imprint (GPT-4o vision)
 spectrometer ───▶ POST /pill                         (mock-spectrometry)
                              │
                              ▼
                       POST /scans  (ScanCreate)
                              │
                    ┌─────────────────┐
                    │ peel-scans doc   │  status: pending
                    │ (revision = 1)   │
                    └────────┬─────────┘
                             │ background asyncio task (research/pipeline.py)
   ┌─────────────────────────┼─────────────────────────────────────────────┐
   │ Stage 0  load        read the scan doc from peel-scans (fatal only if ES is down)
   │ Stage 1  normalize   RxNav approximate-term + NDC status (best-effort)
   │ Stage 2  deterministic  exact lot / NDC / pill-ladder / regulatory search lookups
   │                         ──▶ writes a full report, status → partial (~0.3–3 s)
   │ Stage 3  web         Firecrawl search → peel-web-pages (skipped if disabled/no key)
   │ Stage 4  agent       Agent Builder converse() with 8 ES|QL tools (skipped if unavailable)
   │ Stage 5  coerce      OpenAI structured output folds agent + evidence into ResearchReport
   │                         ──▶ enforce_guardrails() ──▶ status → complete (or error)
   └────────────────────────────────────────────────────────────────────────┘
                             │
                             ▼
              GET /scans/{id}  |  GET /scans/{id}/context  (ElevenLabs handoff)

        ┌───────────────────────────── Elasticsearch ─────────────────────────────┐
        │  peel-regulatory   peel-pills   peel-ndc   peel-web-pages   peel-scans    │
        │  (seeded once by peel-seed; peel-web-pages grows on every live scan)      │
        └───────────────────────────────────────────────────────────────────────────┘
```

Every stage runs inside its own `asyncio.wait_for`/`try-except` (`research/pipeline.py`) and
records `stages[<name>] = {status, duration_ms, error}` rather than aborting the run. Only
Elasticsearch being unreachable when the scan is first loaded produces the terminal `error`
status; every other failure degrades gracefully:

| Dependency down | What happens |
|---|---|
| Agent Builder disabled / unreachable / 401-403 | Stage 4 records `unavailable`; the report already written at stage 2 (refined with web hits) stands, `agent_used` stays `false`. |
| Firecrawl disabled or no API key | Stage 3 records `skipped`; gap logged ("Live web research was disabled for this scan."). |
| Firecrawl credit budget exhausted | Stage 3 plans queries against the affordable count up front (`min(max_searches_per_scan, max_credits_per_scan // cost_per_search)`), so a gap is logged only when nothing could be planned/executed at all, or the process-wide daily cap was hit. |
| OpenAI (`responses.parse`) fails/times out at stage 5 | The stage-2 deterministic report (possibly refreshed with web hits) stands unchanged; `enforce_guardrails` only ever runs on model output, never invents one. |
| RxNav fails or times out | Swallowed inside `RxNavClient` (returns `None`); stage 1 essentially never fails because of it. |
| Whole run exceeds `RESEARCH_TOTAL_TIMEOUT_S` | `TimeoutError` around all five stages; a "ran out of time" gap is added and the run finishes with whatever report exists. |

**Status** moves `pending` → `partial` (end of stage 2) → `complete` (end of stage 5, or a caught
top-level exception/timeout) or `error` (scan doc could not even be loaded). **Revision** is a
Painless-scripted counter (`ScanStore.apply`) that increments on *every* write — each stage's
timing record and each `partial`/`complete` patch — so it climbs several times per run rather
than mapping one-to-one onto the five stages; treat it as "something changed", not a stage count.

## Setup

Requires **Python 3.13** (`backend/.python-version`) and [uv](https://docs.astral.sh/uv/).

```bash
cd backend
uv sync                 # installs from pyproject.toml / uv.lock into .venv
uv run backend          # or: uv run fastapi dev src/backend/app.py
uv run peel-seed --list # confirm the seed sources are discoverable
```

`backend/config.py` reads env files in this order — **the repo-root `.env` first, then
`backend/.env`, with later files overriding earlier ones** (`Settings.model_config.env_file =
(repo_root/".env", backend_dir/".env")`). In this repo only the repo-root `.env` exists; keep
secrets there unless you specifically need a backend-local override. `backend/.env.example`
documents every optional key with its default already baked in as a comment.

| Setting | Default | Meaning |
|---|---|---|
| `OPENAI_API_KEY` | *(required)* | GPT-4o vision + the stage-5 `responses.parse` coercion call. |
| `FIRECRAWL_API_KEY` | `""` | Live web search (stage 3); empty disables it regardless of `FIRECRAWL_ENABLED`. |
| `ELASTICSEARCH_URL` | `""` | Elastic Cloud Serverless endpoint (alias: `ELASTICSEARCH_HOST`). |
| `ELASTICSEARCH_API_KEY` | `""` | Used for both the Elasticsearch client and (as a Kibana API key) Agent Builder. |
| `KIBANA_URL` | `""` | Blank derives it from `ELASTICSEARCH_URL` (`resolved_kibana_url`): first `.es.` → `.kb.`, e.g. `x.es.us-east-1.aws.elastic.cloud` → `x.kb.us-east-1.aws.elastic.cloud`. |
| `AGENT_BUILDER_ENABLED` | `true` | Master switch for stage 4. |
| `AGENT_BUILDER_AGENT_ID` | `peel-research-agent` | Agent id created/updated by bootstrap. |
| `AGENT_BUILDER_CONNECTOR_ID` | `.anthropic-claude-5-sonnet-chat_completion` | LLM connector the agent converses through. |
| `AGENT_BUILDER_TIMEOUT_S` | `120.0` | `/converse` timeout; stage 4 adds a 5 s margin on top. |
| `AGENT_BUILDER_FIRECRAWL_CONNECTOR_ID` | `""` | Optional Kibana Firecrawl connector — lets the agent call Firecrawl itself, uncapped. See [Agent Builder](#agent-builder). |
| `SEMANTIC_SCORE_THRESHOLD` | `0.70` | Score floor for the unfiltered semantic ES|QL tool, calibrated for the Jina model. |
| `FIRECRAWL_ENABLED` | `true` | Enables stage 3 (also needs `FIRECRAWL_API_KEY`). |
| `FIRECRAWL_MAX_SEARCHES_PER_SCAN` | `2` | Queries built per scan (`build_web_queries`). |
| `FIRECRAWL_RESULTS_PER_SEARCH` | `3` | Pages scraped per search; `2 × (2+3) = 10` fits the per-scan cap. |
| `FIRECRAWL_MAX_CREDITS_PER_SCAN` | `10` | Hard per-scan `CreditBudget`. |
| `FIRECRAWL_DAILY_CREDIT_CAP` | `150` | Process-wide daily counter shared across all scans. |
| `RESEARCH_MODEL` | `gpt-4o` | Model for the stage-5 structured-output coercion. |
| `RESEARCH_TOTAL_TIMEOUT_S` | `240.0` | Ceiling for the whole 5-stage run. |
| `RESEARCH_RERANK` | `false` | Enables the `text_similarity_reranker` wrapper on `search_regulatory`. |
| `RXNAV_ENABLED` | `true` | Stage-1 RxNav lookups. |
| `SCANS_STORE_SENSITIVE` | `false` | `true` keeps `rx_number`/`pharmacy`/`directions` on stored scans instead of dropping them. |
| `SHAPE_FILTER_MODE` | `family` | `family`\|`strict`\|`boost` — how hard the pill ladder filters on shape ([Retrieval](#retrieval)). |

`web_cache_ttl_hours_{regulator,news,reference,other}` (24 / 6 / 168 / 48, see
[Firecrawl budget and caching](#firecrawl-budget-and-caching)) are also settings without an
`.env.example` entry; override the same way (`WEB_CACHE_TTL_HOURS_NEWS=`, etc.) if needed.

## Seeding

```bash
uv run peel-seed --list                       # show available sources
uv run peel-seed seed --sources all           # fetch + index everything (~3 min once cached)
uv run peel-seed seed --sources openfda_enforcement,pillbox --limit 500   # smoke run
uv run peel-seed seed --dry-run --sources who_alerts       # parse + field-fill report, no writes
uv run peel-seed seed --download-only --sources mhra       # cache raw files, skip Elasticsearch
uv run peel-seed seed --index-only --sources nafdac         # index from an existing raw cache
uv run peel-seed seed --recreate --yes --sources health_canada  # drop + recreate its index first
uv run peel-seed seed --refresh-cache --sources pillbox      # ignore the raw cache
uv run peel-seed seed --hc-detail-limit 1000                 # more Health Canada lot-table pages
```

| Flag | Default | Meaning |
|---|---|---|
| `--sources` | `all` | Comma list of source names, or `all`. |
| `--limit` | none | Cap documents parsed *per source* (smoke runs). |
| `--download-only` | off | Fetch raw files; never touch Elasticsearch. |
| `--index-only` | off | Index from the existing raw cache; no network fetch. |
| `--dry-run` | off | Parse and print field-fill stats + 3 sample docs; no writes. |
| `--recreate` | off | Delete and recreate the target index(es) first — requires `--yes`. |
| `--yes` | off | Confirms `--recreate`. |
| `--refresh-cache` | off | Re-download even if a cached raw file exists. |
| `--concurrency` | `8` | HTTP fan-out for page-per-record sources. |
| `--bulk-chunk` | auto | Override the bulk chunk size (default 100 for semantic sources, 2000 otherwise). |
| `--workers` | `4` | Concurrent bulk requests in flight. |
| `--hc-detail-limit` | `600` | Health Canada detail pages fetched for lot tables (newest-first). |
| `--list` | — | List sources and exit. |

Seeding spends **0 Firecrawl credits and 0 LLM tokens** (every source is a plain, anonymous HTTP
`GET`, `seed/http.py`) and takes roughly 3 minutes end-to-end at the current corpus size
(embedding throughput ~270–370 docs/s for the three sources carrying a `semantic_text` field).

| Source | Index | Origin | Docs | Extracted | Licence / attribution |
|---|---|---|---|---|---|
| `pillbox` | `peel-pills` | NLM Pillbox Socrata CSV (`crzr-uvwg`), frozen Jan 2021 | 83,925 | imprint, shape, colour, size, score, ingredients, NDC | US public domain |
| `openfda_enforcement` | `peel-regulatory` | `api.fda.gov/download.json` bulk export | 17,963 | lot numbers, NDCs, drug names, severity from classification | Public domain (CC0); openFDA disclaimer stored per record |
| `openfda_ndc` | `peel-ndc` | openFDA NDC directory bulk export | 138,046 | brand/generic name, labeler, strengths, listing status | Public domain (CC0) |
| `who_alerts` | `peel-regulatory` | `who.int` OData news feed + annex PDFs on `cdn.who.int` | 83 | batch numbers parsed from annex PDF tables (page text alone rarely carries them) | CC BY-NC-SA 3.0 IGO |
| `nafdac` | `peel-regulatory` | NAFDAC WordPress REST API, category 29 | 403 | batches from prose, alert number, manufacturer | No published licence — summarise and link |
| `mhra` | `peel-regulatory` | gov.uk Search + Content APIs | 588 | batch numbers from HTML `<table>` and prose | Open Government Licence v3.0 |
| `health_canada` | `peel-regulatory` | Health Canada bulk JSON export + up to 600 cached detail pages | 3,840 | lots/manufacturer from the newest detail pages' "Affected products" table | Open Government Licence – Canada |

Of the 17,963 FDA enforcement records, 13,511 carry at least one lot number (75,290 lot numbers in
total) — the rest are recalls that never named a batch, which is exactly what `covers_all_lots` /
`recalls_covering_all_lots` exist to cover (see [Retrieval](#retrieval)).

Parsing notes worth knowing, all in `knowledge/normalize.py` unless noted: `lot_code`/`code_token`
(a single table-cell token is a real code, not a date/strength/stopword), `code_tokens` (every
code-shaped token in a cell, so `"T43157 (Almus)"` yields `["T43157"]` instead of the
un-matchable, whole-cell-normalized `"T43157ALMUS"`), and `mentions_all_lots` (the "all
lots"/"every batch" phrasing) are now public and shared by every table-driven source rather than
copied per module. `extract_lots`' date/NDC/UPC masking now inserts a break character (`;`) at the
start of a masked span instead of blank padding — blank padding let an `EXP`/other aside opened
before a masked expiry date swallow every lot listed after it, silently dropping them; a compound
header like `"Lot, expiry:"` (where the values that follow lead with the lot column) is now
recognised as one header instead of immediately opening an aside that ate the first lot.
`openfda_enforcement` strips ZIP+4 postal codes from the firm's address before extracting NDCs,
because `Bethlehem, PA 18018-3524` has the same 5-4 shape as a product NDC. `mhra`'s table parser
validates the header's batch column against its first data rows before trusting it (gov.uk does
not always follow its own header order), tokenizes each cell instead of normalizing it whole, and
expands a `"From X to Y"` batch range into its two endpoints — or every code in between when the
range is numeric, equal-width and no more than 200 codes wide; its recall-class detection is a
widened title regex (`Class N ... Recall/Notification/Defect...`, not just `Class N:`) with a
title-derived severity fallback so a `Class 2` alert can never silently fall to `unknown`
severity. `health_canada` gates every "Affected products" table cell through the same code-shape
test rather than a bare split, and sets `covers_all_lots` from the lot cell's own "All lots"
wording. `openfda_ndc` picks the bulk zip's `.json` entry by extension, not position, so a bundled
README or checksum file sorted first can't empty the whole source. The MHRA discovery listing
(gov.uk Search API pages) is reused across runs only when a `search-index.complete` marker
confirms an earlier *unlimited* run wrote it, or the cached listing already covers the current
run's own `--limit` — a `--limit` run's partial listing is never mistaken for the full one. A
source that parses to zero documents makes `peel-seed` exit non-zero with status `empty` rather
than reporting `ok`.

Raw downloads live in `backend/data/raw/<source>/`; parsed, index-ready documents are also
tee'd to `backend/data/normalized/<source>.jsonl` on every run (`seed/cli.py: _tee_jsonl`). Both
directories, plus the append-only `backend/data/seed-runs.jsonl` run log, are **gitignored**
(`backend/data/`). Re-running `peel-seed` is idempotent: every source computes a deterministic
`_id` (e.g. `fda-enf-<recall_number>`, Pillbox's Socrata `spp` key), so a re-run overwrites rather
than duplicates, and cached raw files are reused unless `--refresh-cache` is passed.

**Adding a new source:** drop a module with a `Source` subclass into `seed/sources/` —
`discover()` auto-imports every module there and collects `Source` subclasses by their `name`
attribute. Implement `async def download(self, ctx)` (fetch into `ctx.raw_dir(self.name)`, no
writes) and `def parse(self, ctx)` (yield dicts with `_id` plus only fields mapped for
`self.index`; an unmapped field raises `UnmappedFieldError` at bulk time, and `--dry-run` catches
it first).

## Index reference

All five indices live on the same Elastic Cloud Serverless "VectorDB" project (Elastic 9.6, no ML
nodes — vector search is reachable only through `semantic_text` fields backed by the Elastic
Inference Service model `.jina-embeddings-v5-text-small`). Every mapping is `dynamic: "strict"`
(`knowledge/indices.py`): an unmapped field is a hard index-time rejection, which is what keeps
`knowledge/fields.py` the single source of truth for field names across mappings, seed adapters,
the search builder and the ES|QL tool strings.

`app.py`'s `lifespan` calls `ensure_indices()` at startup so all five strict mappings exist before
the first request — a `peel-scans` created implicitly by the first `POST /scans` would otherwise
get a loose dynamic mapping instead. This is **non-fatal**: if the cluster is unreachable at boot
it just logs a warning, and the store answers its normal 503 per-request instead. On shutdown,
`lifespan` cancels every in-flight research `asyncio.Task` (`research.pipeline.cancel_all`)
*before* closing the Elasticsearch and Agent Builder clients, so a task's own in-flight call
cannot race a connection that has already been torn down. The Elasticsearch client itself raises
its connection pool to `connections_per_node=32` (`knowledge/client.py`) — a scan indexes pages,
polls its own status and searches concurrently, and the default pool of 10 was starving pollers
and surfacing as `ConnectionTimeout`.

**Three of the five indices carry no vector field at all** — `peel-pills` and `peel-ndc` are pure
attribute/keyword lookups (pill physical features and NDC identity aren't semantic questions),
and `peel-scans` never needs semantic search over a user's own history. This is the deliberately
"minimal vector space": only `peel-regulatory.body_semantic` and `peel-web-pages.page_semantic`
are embedded, and both are **capped excerpts, not full documents** — `body_semantic` is built
from the title, reason and a short slice of the product description (900–2000 characters
depending on the source), deliberately **excluding lot/NDC lists**, since feeding a lot-number
table to an embedding model both wastes inference and pollutes the vector space with tokens that
mean nothing semantically. Exact lot/NDC matching is handled separately, by keyword
`term`/`MV_CONTAINS` lookups against `lot_numbers` / `ndc9` / `ndc11`.

#### `peel-regulatory` (22,877 docs: FDA 17,963 · Health Canada 3,840 · MHRA 588 · NAFDAC 403 · WHO 83; all embedded, ~14.7k with extracted lot numbers)

| Field(s) | Used for |
|---|---|
| `record_id` | Doc id / citation key. |
| `lot_numbers` | **Exact** lookup (`recalls_by_lot`, `MV_CONTAINS` in ES|QL) — never decayed. |
| `ndc9`, `ndc11`, `ndc_from_description` | **Exact** lookup (`recalls_by_ndc`); `ndc_from_description` (NDCs named in the record's own text) is boosted 10× over the sibling NDCs openFDA lists for the whole product line — see [Retrieval](#retrieval). |
| `covers_all_lots` | Filter — recalls that name no lots at all, so the whole product line is in scope. |
| `title`, `drug_names(.txt)`, `drug_names_extracted(.txt)`, `manufacturer(.txt)`, `reason`, `product_description`, `body` | **BM25** (`multi_match`, `title^3`). |
| `body_semantic` | **Semantic** (300-word chunks). |
| `doc_type`, `source_org`, `dosage_form`, `countries`, `severity` | **Filter** (exact-match pre-filters, `SearchFilters`). |
| `severity`, `severity_rank` | Display + sort tiebreaker. |
| `recency_date` | **Decay** anchor and `max_age_days` range filter. |
| `url`, `attachment_urls`, `attribution`, `source_license`, `source_terms_url`, `source_disclaimer` | Display / licensing. |
| `raw` | Stored only (`enabled: false`) — original source record, never searched. |

#### `peel-pills` (83,925 docs — NLM Pillbox archive, frozen January 2021, no vectors)

| Field(s) | Used for |
|---|---|
| `imprint_norm`, `imprint_sorted` | **Exact** term match — rungs 1–2 of the identification ladder. |
| `imprint_parts`, `imprint_text` | `imprint_parts` also backs the **`imprint_all_parts`** strong-match tier (every observed marking present, for a photo of one face of a two-sided pill), then a boosted `terms` match; `imprint_text` is the fuzzy fallback rung. |
| `shape`, `shape_family` | **Filter** (rung 1, mode-dependent) or **boost** (rung 2) — see [Retrieval](#retrieval). |
| `colors`, `score`, `size_mm` | Boost / range boost, never a hard filter. |
| `medicine_name`, `generic_name(.txt)`, `strength`, `ingredients(.txt)`, `labeler(.txt)`, `product_ndc`, `rxcui` | Display + cross-reference. |
| `raw` | Stored only. |

#### `peel-ndc` (138,046 docs — openFDA NDC directory, no vectors)

| Field(s) | Used for |
|---|---|
| `product_ndc`, `ndc9`, `package_ndcs`, `ndc11` | **Exact** term lookup (`ndc_directory`, `peel.ndc_lookup`). |
| `brand_name(.txt)`, `generic_name(.txt)`, `labeler_name(.txt)`, `active_ingredient_names(.txt)` | Display + mismatch detection (label claim vs. registered identity). |
| `is_listing_expired` | Mismatch signal (expired FDA listing). |
| `raw` | Stored only. |

#### `peel-web-pages` (grows on every live scan)

| Field(s) | Used for |
|---|---|
| `page_id` (= `url_hash(url)`) | Doc id / dedupe key. |
| `title^3`, `description`, `content` | **BM25**. |
| `page_semantic` | **Semantic** (300-word chunks, source capped to 6,000 chars). |
| `source_tier`, `scan_ids` | **Filter** (`source_tier`, and an exact fetch of this scan's own pages). |
| `recency_date` | **Decay** anchor — `published_at` if known, else `last_changed_at`; **never `fetched_at`**, so re-fetching an unchanged page cannot make it look fresh. |
| `content_hash`, `first_seen_at`, `last_changed_at`, `revision` | Change tracking on re-fetch (see [Retrieval](#retrieval)). |
| `query_key`, `queries` | TTL-cache lookup keys (`cached_page_ids`). |
| `flags`, `is_recall`, `is_alert`, `lot_numbers`, `ndc9`, `ndc11`, `countries` | Extracted facets, display. |
| `stale` | Reserved for future use — always written `false`, never read back. |
| `via` | `"backend"` or `"agent_connector"` — who fetched the page. |
| `firecrawl_credits` | Per-document cost accounting. |

#### `peel-scans` (one document per scan, `dynamic: strict` throughout)

| Sub-object | Contents |
|---|---|
| `bottle` | Sanitized `BottlePhotoResult` — see [Safety and privacy](#safety-and-privacy) for what is dropped. |
| `imprint` | `ImprintPhotoResult` fields plus a manually-supplied `size_mm`. |
| `norm` | **Single-valued** join keys (`lot`, `ndc9`, `ndc11`, `imprint_norm`, `shape`, `generic_name`, …) — deliberately never arrays, because ES|QL `==` silently matches nothing on a multi-valued field, and every retrieval path filters on these. |
| `hardware` | Mock/real spectrometry result; `limitations` is set to `"Simulated result; no physical measurement was performed."` whenever `model == "mock-spectrometry"`. |
| `research` | The final `ResearchReport` (`dynamic: false` — the full report lives in `_source` without mapping every leaf field). |
| `evidence` | Record/page ids cited, Firecrawl spend, the agent conversation id, the full evidence pack (`dynamic: false`). |
| `stages` | Per-stage `{status, duration_ms, error}` (`enabled: false` — write-only diagnostics). |
| `photos` | `{target, sha256, bytes, media_type}` — never the image bytes themselves. |

## Retrieval

`knowledge/search.py` implements two deliberately separate retrieval modes:

- **Hybrid + decay** (`search_regulatory`, `search_web`) — an Elasticsearch `linear` retriever
  whose **top-level `filter`** is pushed into *every* leg, so the vector leg searches a
  pre-filtered candidate set instead of filtering after the fact. Each leg (BM25 weight 1.0,
  semantic weight 1.2) is wrapped in a `script_score` that multiplies the leg's score by a
  Gaussian recency decay with a floor, then `minmax`-normalized before the legs are summed.
- **Exact lookups** (`recalls_by_lot`, `recalls_by_ndc`, `ndc_directory`) — flat
  `constant_score` term queries. Never decayed, never fused with the hybrid legs — an old but
  exact lot match is guaranteed to appear by taking the **union** of the exact-lookup hits with
  the hybrid hits, never by hoping it ranks highly enough inside one query. The pipeline applies
  the same union principle to web evidence: `_collect_web_hits` unions the ranked `search_web`
  results with a direct `pages_by_id` fetch of every page *this scan itself* just indexed, so a
  page fetched seconds ago that hasn't yet accumulated ranking signal can never be silently lost.

**Decay formula** (`floor + (1 − floor) × gaussian(age)`, DSL: `decayDateGauss`; ES|QL tools
approximate the same curve with `POW(0.5, GREATEST(age_days − offset, 0) / scale_days)`):

| Profile | Offset | Scale (half-life) | Floor |
|---|---|---|---|
| `REGULATORY_DECAY` | 30 days | 730 days | 0.35 |
| `WEB_DECAY` | 1 day | 7 days | 0.20 |

A regulatory record never falls below 35% of its un-decayed relevance no matter how old; a web
page decays much faster (7-day half-life) since a live search result is only interesting while
it's fresh.

**Lot corroboration.** A lot string is unique per manufacturer only, and the corpus also carries
extraction artefacts ("MG30", "080615"), so a bare term hit on `lot_numbers` is a collision as
often as a match. `recalls_by_lot(lot, *, ndc9=None, drug_names=None)` therefore classifies every
hit *after* retrieval with the same corroboration check `recalls_covering_all_lots` uses, exposed
publicly as `corroborates_product()` for tests and future callers: a hit whose
`ndc9`/`ndc_from_description` or `drug_names`/`drug_names_extracted` token-overlaps the scanned
product — or one where the label gave no product context to check against at all — keeps
`match_kind = "exact_lot"`; a lot-string collision with a *different* product is downgraded to
`"lot_only_match"`. `recalls_covering_all_lots` (recalls that name no lots at all, so the entire
product line is in scope) applies the same test and tags `"all_lots_product"` vs
`"all_lots_sibling"` (reached only through openFDA's sibling-strength NDC list). Both methods sort
corroborated hits first and *then* dedupe by `event_id`, so a corroborated record — not an
uncorroborated sibling that happens to share the same recall event — is the one kept.

**NDC semantics.** `openfda.product_ndc`/`package_ndc` on an FDA enforcement record enumerate
*every sibling strength* of the recalled product line — a 200 mcg levothyroxine recall's own
`openfda` block lists all twelve Accord strengths. `Reg.NDC_FROM_DESCRIPTION` is populated
**only** from NDCs that appear in the record's own free text (`product_description`/`code_info`),
and is boosted 10× (`_NDC_PRECISE_BOOST`) over the sibling-NDC fields so the actually-relevant
record survives the size cap and ranks first. `recalls_by_ndc` tags each hit's `match_kind` as
`ndc_in_description` (precise) or `product_line_match` (a sibling strength) — **an NDC hit alone
is never treated as a recall match, whichever `match_kind` it carries**. Only the `exact_lot_hits`
and `all_lots_hits` lookups can produce verdict `recall_match`, and then only for entries tagged
`exact_lot`/`all_lots_product` (`evidence.py: verdict_from_evidence`); `lot_only_match` and
`all_lots_sibling` — like every `recalls_by_ndc` hit — are folded into caution-level findings
instead.

**Pill identification ladder** (`KnowledgeSearch.identify_pill`) climbs rungs until an exact
imprint form matches. Every imprint tier lives inside its own `must` clause
(`bool_query["must"] = [{"bool": {"should": imprint_tiers, "minimum_should_match": 1}}]`) so a
colour, score or size `should` boost can never satisfy the query by itself — those only re-rank
among documents that already matched an imprint tier. The tiers, highest boost first:
`imprint_norm` (100) and `imprint_sorted` (60) exact term matches; **`imprint_all_parts`** (45) —
a phone photo shows only *one face* of a pill whose Pillbox reference lists both (`"b;972;1;0"`),
so once the observed parts are "distinctive" (two or more parts, or one of three-plus characters)
and every one of them is present in the stored `imprint_parts`, that counts as a strong match even
though the full joined string never matches; then a boosted `terms` match on `imprint_parts` (10)
and a fuzzy `imprint_text` `match` (5) as the lowest tier. `imprint_norm`, `imprint_sorted` and
`imprint_all_parts` all count as "exact" for ladder purposes (`_PILL_EXACT_KINDS`). **Rung 1**
additionally applies shape as a **hard filter** (`SHAPE_FILTER_MODE`: `family` matches the shape
family — round/elongated/quadrilateral/diamond/triangle/polygon/irregular — `strict` matches the
literal shape, `boost` never filters); **rung 2** (only if rung 1 found no exact-tier hit) repeats
the imprint match with shape downgraded to a **3× boost**; **rung 3** (only if an imprint exists
but rung 2 still found nothing exact) drops shape entirely, keeping only the fuzzy tier. The
pipeline passes the imprint **as read** (`imprint.imprint`, e.g. `"b 972"`) rather than the
already-joined `norm.imprint_norm`, because the all-parts tier depends on part boundaries that
`"B972"` would lose. `shape_relaxed = true` only when rung 2/3 actually produced hits, the ladder
needed rung > 1, *and* rung 1 had a real shape filter to drop (`rung1_shape is not None`) — an
imprint simply absent from Pillbox climbs every rung and finds nothing, which is not a shape
disagreement. `derive_mismatches` surfaces `shape_relaxed` as a low-confidence "shape
disagreement" rather than silently dropping the observation, since a vision-read shape is far less
reliable than the label's exact text. A query with no imprint, shape, colour, score or size at all
fails closed before any Elasticsearch call (`rung = 0`, no hits); `build_pill_query` itself falls
back to `match_none` as a second line of defence if it is ever called with nothing left to filter,
boost or require.

**Evidence pack trimming** (`research/evidence.py: build_evidence`, capped at
`MAX_EVIDENCE_CHARS` = 14,000 characters): `web_hits` are ranked by importance — a page naming the
label's own lot first, then a regulator alert about this drug, then any other regulator page,
newest first within each tier — *before* the tail-first size cap trims the pack, so trimming can
only drop the least useful hits, never reorder the ones that survive. A scan with no pill imprint
skips identification entirely (`pill_skipped = "no imprint read"`) rather than matching on shape
and colour alone, which tens of thousands of pills share. Neither the Agent Builder prompt nor the
stage-5 coercion payload ever includes `hardware.spectrum`: `_trimmed_hardware` strips it before
either call, since it is an unbounded float array no model can use and a non-conforming client
could make megabytes long.

**Freshness labels** (`normalize.freshness_label`): `today` (≤1 day), `this_week` (≤7),
`this_month` (≤31), `this_year` (≤365), `older`, or `unknown` when no recency date exists.

**Web page upsert/versioning** (`WebResearcher.index_page`): a page is looked up by `page_id =
url_hash(url)` before every write. New page → `first_seen_at = last_changed_at = now`,
`revision = 1`. Unchanged `content_hash` → only `fetched_at` moves; `recency_date` (`published_at`
or `last_changed_at`, **never `fetched_at`**) stays put, so re-fetching stale content can't make it
rank as fresh. Changed content → `last_changed_at = now`, `revision` increments. Every write is
guarded by optimistic concurrency: a brand-new page uses `op_type: create` so a racing concurrent
create conflicts instead of silently overwriting, and an existing page is guarded by
`if_seq_no`/`if_primary_term` from the version just read; a `ConflictError` retries the whole
read-modify-write exactly once before giving up, because two searches for one scan that return the
same URL must not let one side's `query_key` (and the cache hit it buys next time) get lost to the
other's write.

**TTL cache by source tier** (`WebResearcher.cached_page_ids`): before spending a credit, look for
≥2 pages already indexed under the same `query_key`/`queries` and still inside their tier's TTL
(`web_cache_ttl_hours_{regulator,news,reference,other}` = 24 / 6 / 168 / 48 h). A cache hit costs
0 credits and just appends the current `scan_id` to the page's `scan_ids`.

## Agent Builder

`research/agent_builder.py` bootstraps the Peel agent **lazily** (on the first research request,
not at startup — a Kibana outage must never block `POST /scans`) and **idempotently**: each tool
and the agent itself go through `GET /{kind}/{id}` → `POST` if missing, `PUT` if it already
exists. Bootstrap must run **after** the Elasticsearch indices exist, because ES|QL tools are
validated against the real mappings when they're created.

**Self-healing registration.** The agent id and tool ids are shared by every backend instance
pointed at the same Kibana, and each instance registers its own definitions on its first research
run — so an instance running older code silently overwrites the agent's instructions and tools
(observed live: a second dev server reverted the agent mid-benchmark). `_specs()` therefore hashes
the full tool + agent spec (`spec_fingerprint`) into a `spec-<hash>` label on the agent, and
`converse()` calls `ensure_current()` first: one `GET /agents/{id}` (~0.1 s); if the stored label
differs from this process's fingerprint, tools and agent are re-registered before the round. Last
writer still wins between rounds, so for parallel development give each developer their own
`AGENT_BUILDER_AGENT_ID`.

**Latency protocol.** Tool execution is milliseconds; a round's time is LLM output tokens
(including hidden reasoning) at ~35-55 tok/s plus prefill of ~18k input tokens (mostly Agent
Builder's own scaffolding). The instructions are written for that: the evidence pack is declared to
be *already-executed tool results* (each key mapped to the tool it corresponds to), re-running a
lookup "to verify" is forbidden, tools are for real gaps only and must be issued in one step, and
the output is a terse <=130-word line format — the agent's text is an intermediate artifact that
stage 5 turns into the user-facing report. Measured on the same prompts, same connector:

| Scan | Before | After |
|---|---|---|
| conclusive (exact lot recall in the pack) | 35-88 s, 1-2 LLM calls, up to 3.1k output tokens | **~25 s**, 1 LLM call, 0 tool calls, ~1k output tokens |
| ambiguous (no lot/NDC; imprint only) | 55-100 s | 40-60 s, still runs follow-up tools (`ndc_lookup`, `regulatory_search_text`) |

The other managed connectors on the project (GLM-5.3, Qwen-3.8) were slower on the same prompt
(30-40 s): they emit 3-5k reasoning tokens.

| Tool id | Purpose | Params |
|---|---|---|
| `peel.recalls_by_lot` | Exact lot/batch match in `peel-regulatory`, never decayed. | `lot` |
| `peel.recalls_by_ndc` | Product-line recall lookup by 9-digit NDC; tags `ndc_in_recall_text` vs. `same_product_line`. | `ndc9` |
| `peel.regulatory_search_text` | Keyword search with exact metadata filters and a recency decay boost. | `query`, `drug?`, `source_org?`, `doc_type?`, `dosage_form?`, `country?`, `max_age_days?` |
| `peel.regulatory_search_semantic` | Unfiltered vector search over `body_semantic`, score-thresholded. | `query`, `min_score?` |
| `peel.pill_lookup` | Imprint (+ optional shape/family) lookup in `peel-pills`, imprint passed **as read** and matched with `MATCH ... {"operator": "AND"}`. | `imprint`, `shape?` |
| `peel.ndc_lookup` | Resolve a 9-digit NDC to its registered product identity. | `ndc9` |
| `peel.web_evidence_search` | Search already-fetched web pages, decayed on a 7-day half-life. | `query`, `source_tier?` |
| `peel.prior_scans` | Count earlier Peel scans of the same lot/NDC, by verdict. | `lot?`, `ndc9?` |

**ES|QL gotchas discovered against the live cluster** (baked into `research/tools.py`):

- `==` on a multi-valued keyword field (e.g. `lot_numbers`) silently matches nothing —
  `MV_CONTAINS(field, ?param)` instead.
- `MATCH` cannot follow `MV_EXPAND`, which also duplicates the document and truncates the field
  to the matched element — lot/NDC lookups use `MV_CONTAINS`, never `MV_EXPAND`.
- A `WHERE` filter next to a `MATCH` on `semantic_text` applies **after** the semantic top-k is
  chosen (a post-filter, not a pre-filter) — so `peel.regulatory_search_semantic` is deliberately
  left unfiltered, and the true pre-filtered hybrid search runs in the backend
  (`knowledge/search.py`), not as an agent tool.
- The semantic score threshold is `0.70` (`SEMANTIC_SCORE_THRESHOLD`), calibrated for
  `.jina-embeddings-v5-text-small` — not a universal Elasticsearch default.
- Optional params use an `"any"` sentinel plus `optional: true` + `defaultValue: "any"`, checked
  with `?param == "any" OR ...` — ES|QL tool params have no native "unset" concept.
- `peel.pill_lookup` takes the imprint **as read**, uppercase, with a single space between
  markings (`"B 972"`, not the joined `"B972"`). The exact-form check strips spaces itself
  (`compact = REPLACE(?imprint, " ", "")`) so it doesn't care either way, but
  `MATCH(imprint_text, ?imprint, {"operator": "AND"})` tokenizes `?imprint` directly — a joined
  `"B972"` becomes one token that may not match at all, where `"B 972"` requires the two tokens
  `B` and `972` both be present. The agent's own instructions tell it to pass `imprint.imprint`
  this way rather than a normalized form.

**Enabling the optional Firecrawl connector:** set `AGENT_BUILDER_FIRECRAWL_CONNECTOR_ID` to a
Kibana `.firecrawl` connector id. When set, it's attached to the agent's `connector_ids` so the
agent can call Firecrawl directly (uncapped by the backend's per-scan credit budget — treat this
as a demo-only flag). Any page the agent fetches this way is still indexed into
`peel-web-pages` by the backend afterwards (`WebResearcher.harvest_agent_pages`, called once per
agent round), so "everything fetched from the live web lands back in the index" holds regardless
of which side did the fetching.

## HTTP API

### `scans/router.py`

| Endpoint | Notes |
|---|---|
| `POST /scans` | 202 Accepted. Creates the scan doc (`status: pending`) and launches background research. |
| `GET /scans?device_id=&lot=&ndc=&limit=&after=` | Requires at least one of `device_id`, `lot` or `ndc` — **422** otherwise (`ScanStore.list` itself raises on an empty filter set as a second line of defense, since an unscoped query would dump every device's history). Cursor-paginated; `lot`/`ndc` are normalized server-side and a filter that normalizes to nothing returns an empty page rather than silently dropping the filter. |
| `GET /scans/{scan_id}` | Full `ScanEnvelope`, including the top-level `country` field. |
| `GET /scans/{scan_id}/context?as_string=` | The ElevenLabs `scan_context` handoff — `to_scan_context()` as a dict, or (with `as_string=true`) `{"scan_context": "<json string>"}`, because ElevenLabs dynamic variables must be strings. The `hardware` block carries both the derived `status`/`degradation` and the device's raw `reported_status`, so a "fake" reading with no identified pill type still reads as more than merely inconclusive. |
| `POST /scans/{scan_id}/research` | Re-run research. `{"force": true}` cancels any in-flight run and restarts; otherwise 409 if one is already running, 503 if the pipeline module isn't loaded. |

### `reports/router.py`

A report is the three optional provenance answers (`purchased_on`, `purchase_location`,
`seller`) joined to a scan by `scan_id`; nothing from the scan is copied. Peel collects them in
the voice chat and calls the client-side `draft_report` function, which reaches the app as a
`FunctionCallRequest`; the app shows a preview and only the Submit button writes. Deepgram never
calls these routes. See [`docs/deepgram/INTEGRATION.md`](../docs/deepgram/INTEGRATION.md).

| Endpoint | Notes |
|---|---|
| `POST /scans/{scan_id}/reports` | The Submit button. 201 with the stored `Report`; every tap is a new `report_id`. 404 if the scan is missing. Written with `refresh=False`, so render the confirmation from the response. |
| `GET /scans/{scan_id}/reports` | `{"results": [...]}` for this scan, newest first (search on `scan_id`; can lag a submit by about a second). |

`ScanCreate` (`scans/models.py`) bounds every field an oversized payload could inflate:
`hardware.spectrum` to `MAX_SPECTRUM_LEN` (4096) floats, `bottle.visible_warnings` to
`MAX_VISIBLE_WARNINGS` (50) items of `MAX_WARNING_LEN` (500) characters each, every other
free-text label/imprint field to `MAX_TEXT_FIELD_LEN` (4000) characters, and `hardware_model` to
128 characters — all rejected with a validation error before the scan is ever stored. Elasticsearch
transport errors (timeouts, dropped connections) surface as **503** from every `scans` endpoint,
not a generic 502, so a client can tell "retry me" apart from "this request is wrong".

```bash
curl -s localhost:8000/scans -X POST -H 'content-type: application/json' -d '{
  "device_id": "demo-phone-1",
  "bottle": {"is_medication_container": true, "generic_name": "Levothyroxine Sodium",
             "strength": "200 mcg", "ndc": "16729-457-15", "lot_number": "D2402430",
             "confidence": 0.93}
}'
# -> 202 {"scan_id":"scan-...","status":"pending","revision":1,...}

curl -s "localhost:8000/scans/scan-xxxx"
# -> {"scan_id":"scan-xxxx","status":"partial","research":{"verdict":"recall_match",...},...}

curl -s "localhost:8000/scans/scan-xxxx/context?as_string=true"
# -> {"scan_context":"{\"scan_id\":\"scan-xxxx\",\"revision\":4,\"status\":\"complete\",...}"}
```

**Polling:** `ScanStore.get` reads with `realtime=True`, so a ~1 Hz poll of `GET /scans/{id}` sees
each stage's write immediately. Poll until `status` is `complete`/`error`; a `partial` report
(a few hundred ms to ~3 s in) is already renderable and shares the same `research` shape.

### `knowledge/router.py`

Debug/demo surface over retrieval, independent of the scan pipeline. Every endpoint accepts
`?debug=true` to also return the exact query body sent to Elasticsearch.

`GET /knowledge/search` bounds `size` per retrieval shape — `MAX_REGULATORY_SIZE` (100),
`MAX_WEB_SIZE` (50) and `MAX_RERANK_SIZE` (30), `knowledge/search.py` — mirroring each retriever's
own `rank_window_size`, since a retriever rejects a request whose `size` exceeds its window; every
query itself sets `rank_window_size = max(window, size)`, so an oversized `size` widens the window
rather than failing outright. It returns **422** when a regulatory-only filter (`drug`,
`dosage_form`, `doc_type`, `source_org`, `country`, `severity`, `max_age_days`, `rerank`) is passed
with `index=web`, when `source_tier`/`scan_id` is passed with the default `index=regulatory`, when
`size` exceeds 50 for `index=web`, or when `size` exceeds 30 with `rerank` on — silently ignoring
an unsupported filter would return an unfiltered result set under a body that claims otherwise.

```bash
curl -s "localhost:8000/knowledge/lot/D2402430"
# -> {"lot":"D2402430","count":1,"hits":[{"source":{"record_id":"fda-enf-D-0785-2026",...}}]}

curl -s "localhost:8000/knowledge/ndc/16729-457-15"
# -> {"ndc":{"ndc9":"167290457",...},"recalls":[...match_kind: ndc_in_description...],"directory":[...]}

curl -s "localhost:8000/knowledge/pill?imprint=5892V&shape=capsule"
# -> {"hits":[{"match_kind":"imprint_exact","source":{"generic_name":"temazepam",...}}],"rung":1,...}

curl -s "localhost:8000/knowledge/search?q=levothyroxine+subpotent&source_org=FDA&index=regulatory"
# -> {"query":"...","count":10,"hits":[{"score":1.87,"freshness":"this_month",...}]}

curl -s "localhost:8000/knowledge/stats"
# -> {"counts":{"peel-regulatory":22877,"peel-pills":83925,"peel-ndc":138046,"peel-web-pages":N,"peel-scans":N}}
```

## Firecrawl budget and caching

| Limit | Default | Where enforced |
|---|---|---|
| Searches per scan | 2 | `build_web_queries(..., max_queries=firecrawl_max_searches_per_scan)` |
| Results scraped per search | 3 | passed as `limit` to `firecrawl.search(...)` |
| Per-scan credit cap | 10 | `CreditBudget(per_scan=...)`, reserved *before* the call so a failed call still costs |
| Daily credit cap | 150 | a module-level counter shared by every scan on the process, resets on UTC date rollover |
| Cost model | `2 + pages_scraped` credits per search | `estimate_credits()` — one base credit-pair for the search, one credit per scraped page |

At the defaults, one scan costs at most `2 × (2 + 3) = 10` credits — exactly the per-scan cap.
Stage 3 plans queries *against* this budget up front (`planned = min(max_searches_per_scan,
max_credits_per_scan // cost_per_search)`), reserves the whole plan before it runs, and then fires
every planned search **concurrently** (`asyncio.gather`) inside a 75 s stage budget
(`WEB_TIMEOUT_S`, `research/pipeline.py`) — so it never builds a search it can't afford and then
reports a false "budget spent" gap, and a slow search cannot starve the others out of their share
of the timeout. A cache hit (≥2 pages already indexed for the query within its tier's TTL, see
[Retrieval](#retrieval)) costs 0 credits: its up-front reservation is handed back with
`CreditBudget.refund()`, so the process-wide daily counter is not consumed by a call that never
actually went out. Blocked domains
(`EXCLUDED_DOMAINS` — facebook.com, instagram.com, tiktok.com, x.com, twitter.com, youtube.com,
reddit.com, pinterest.com, linkedin.com) are appended to every query as `-site:` exclusions
(advisory only) **and** enforced again after the fetch (`web.py: is_blocked`): a blocked page
that slips through is dropped before indexing — the credit is still spent, but the page can never
become citable evidence.

## Safety and privacy

- The `Verdict` enum (`research/models.py`) is `no_adverse_findings | mismatch_found |
  recall_match | insufficient_evidence` — **there is no positive-assurance value**. The product
  never says "safe", "genuine", "verified" or "authentic". `enforce_guardrails` checks banned
  words **clause-scoped, not sentence-scoped** — "no recall was found, so this medicine is
  genuine" still trips it, because the negation sits in a different clause than the assurance —
  and neutralises the headline, every finding statement, mismatch explanation and gap that fails
  the check, not just the top-level fields. The mandated no-findings disclaimer is allowlisted by
  its own marker text rather than by the word "not" inside it, so it survives the same filter that
  would otherwise strip it.
- **Verdict corrections are two-way, and an upgrade rebuilds the whole recall side of the
  report.** If the model wrote `recall_match` but the evidence does not support it,
  `enforce_guardrails` downgrades the verdict and clears `recall_hits`. If the evidence supports
  `recall_match` but the model wrote something weaker, it upgrades the verdict *and* replaces
  `headline`, `findings`, `recall_hits`, `sources` and `next_steps` wholesale from
  `deterministic_report` — a model that missed the recall wrote every one of those fields for the
  wrong conclusion, so patching just the verdict field would leave a `recall_match` report that
  still reads like nothing was found. Separately, a lot/all-lots lookup that itself failed
  (`recall_lookup_failed`) forces `insufficient_evidence` instead of `no_adverse_findings`, even
  when nothing else went wrong — a search that never ran cannot support "nothing was found".
- **Only `exact_lot`/`all_lots_product` reach `recall_match`.** `lot_only_match` (a lot string
  that collides with a different product) and `all_lots_sibling` (reached only through openFDA's
  sibling-strength NDC list) are downgraded to caution-level findings — see
  [Retrieval](#retrieval).
- **Every citation is rebuilt from canonical evidence, never trusted verbatim from the model.**
  The model may only choose *which* stored source id to cite; `source_index`/`resolve_source_id`
  resolve whatever id, URL or title it wrote back to the evidence pack's own record, so a retyped
  title or a mangled id can never introduce fabricated metadata. A finding left with no resolvable
  id is dropped unless its `evidence_type` is one of the sourceless exemptions (hardware result,
  bottle label, prior-scan signal) or it carries the mandated disclaimer. Every string is scrubbed
  of C0 control characters before any of these checks run — gpt-4o has been observed turning a
  retyped JSON escape into a stray control byte that could otherwise split a banned word.
- Every `no_adverse_findings` verdict is required to carry `SAFE_NO_FINDINGS_TEXT` verbatim
  ("...that is not a confirmation that this medicine is genuine or safe..."), enforced by
  `_ensure_safe_wording` even if the LLM omitted it.
- Mock hardware is explicitly labelled: `hardware.limitations` is `"Simulated result; no physical
  measurement was performed."` whenever the model is `mock-spectrometry` (`HARDWARE_MODEL`,
  `pill.py`). The evidence pack derives a `hardware.simulated` boolean
  (`model == HARDWARE_MODEL or bool(limitations)`) that the deterministic report and the stage-5
  coercion instructions must both respect; when a substandard/fake reading and a qualifying
  recall both exist, the report may say the two signals "point the same way" but must add that
  it is simulated and "not proof that this particular tablet is falsified or substandard"
  (`_corroboration_finding`) — never a compounded certainty claim.
- **Sensitive label fields are dropped at the API boundary, not just from a display layer.**
  `sanitize_bottle()` (`scans/normalizer.py`) never writes `rx_number`, `pharmacy`, `directions`
  or the free-text `other_label_text` into `peel-scans` unless `SCANS_STORE_SENSITIVE=true`; it
  stores boolean `*_present` flags for the first three instead. `imprint_doc()` applies the same
  rule to the imprint photo's own free-text `notes` field. A patient's name, address or pharmacy
  visit tends to end up in exactly these free-text fields, so an Rx number, a pharmacy name and a
  photo timestamp — together a re-identifiable record — cannot be reconstructed from the default
  index.
- **Image bytes are never stored.** `photos[]` carries only `{target, sha256, bytes,
  media_type}` (`ScanCreate.photos: list[PhotoRef]`); the fingerprint, not the picture.
- **Licensing travels with the data.** openFDA's disclaimer and terms URL are stored per
  enforcement record (`source_disclaimer`, `source_terms_url`); every source carries its own
  license constant — FDA/openFDA CC0, WHO CC BY-NC-SA 3.0 IGO (summarise and link, never read out
  long verbatim passages), Health Canada and MHRA Open Government Licence, NAFDAC "no published
  licence — summarise and link". Pillbox/RxNav/NLM data is US public domain.
- **Pillbox is a frozen archive (January 2021).** A miss there never implies a pill is fake —
  every place a Pillbox match is used (`deterministic_report`, the agent instructions, `_gaps`)
  says so explicitly, and a newer product simply may not be in it.

## Testing and verification

```bash
uv run pytest                    # 930 passed, 14 skipped; live-cluster tests auto-skipped
PEEL_LIVE=1 uv run pytest -m live   # also run the live-cluster suite
uv run python scripts/smoke.py      # read-only smoke test against the real cluster (17/17 checks)
uv run python scripts/smoke.py --e2e   # + one full scan (<=10 Firecrawl credits, OpenAI tokens)
```

`PEEL_LIVE=1` unskips `tests/knowledge/test_search_live.py`, which creates two throwaway indices
(`peel-zz-test-reg-<random8>`, `peel-zz-test-pills-<random8>`), bulk-indexes a handful of
synthetic recall and pill documents, runs five assertions (metadata pre-filter narrows without
dropping in-filter docs, recency ordering, an exact lot lookup on a 2016-dated record, and the
pill ladder relaxing/holding on shape), and deletes both indices in a `finally` block regardless
of outcome — a failed run cannot leave state behind.

`scripts/smoke.py` (no flags) is read-only except for the idempotent Agent Builder bootstrap
(upserting the 8 tools + the agent): 11 retrieval checks (corpus size, exact lot, WHO
falsified-batch hit, unknown-lot miss, NDC product-line ranking, both pill-ladder rungs,
pre-filter honoured, decay/freshness present) + 6 agent-tool checks (one per tool, via
`/tools/_execute`) = 17/17. `--e2e` additionally runs one real demo scan through the whole
pipeline and asserts `complete` + `verdict == recall_match`, budget compliance and a PHI-free
`scan_context` — the only thing here that spends real Firecrawl credits and OpenAI tokens.

## Demo script

**A — Recalled lot (the money shot).** Accord Healthcare Levothyroxine Sodium 200 mcg, NDC
`16729-457-15`, lot `D2402430` → FDA recall `D-0785-2026` (Class II, subpotent drug, published
2026-09-02).

```bash
curl -s localhost:8000/scans -X POST -H 'content-type: application/json' -d '{
  "device_id": "demo-1", "demo": true, "country": "United States",
  "bottle": {"is_medication_container": true, "generic_name": "Levothyroxine Sodium",
             "strength": "200 mcg", "form": "tablet", "ndc": "16729-457-15",
             "manufacturer": "Accord Healthcare", "lot_number": "D2402430",
             "expiration": "10/2026", "confidence": 0.93},
  "imprint": {"is_pill": true, "color": "pink", "shape": "round", "confidence": 0.7},
  "hardware": {"status": "substandard", "spectrum": [0.1,0.1,0.1,0.1], "degraded": false,
               "pill_type": "levothyroxine", "confidence": 0.78},
  "hardware_model": "mock-spectrometry"
}'
```

Poll `GET /scans/{id}` for `research.verdict == "recall_match"`. **Near-miss variant:** repeat
with `"lot_number": "D2402999"` (same NDC, a lot not on the recall) — expect `recall_match` to
*not* fire; the NDC hit downgrades to a `product_line_match` caution, not a recall.

**B — LMIC falsified product.** HEALMOXY Amoxicillin 500 mg, batch `H02605` → WHO Medical Product
Alert N°2/2025 and NAFDAC Public Alert 17/2025 (batches recovered from the WHO alert's annex
PDF; detected in Cameroon and the Central African Republic).

```bash
curl -s localhost:8000/scans -X POST -H 'content-type: application/json' -d '{
  "device_id": "demo-2", "demo": true, "country": "Cameroon",
  "bottle": {"is_medication_container": true, "brand_name": "HEALMOXY",
             "generic_name": "Amoxicillin", "strength": "500 mg", "form": "capsule",
             "manufacturer": "MAXHEAL PHARMACEUTICALS", "lot_number": "H02605",
             "confidence": 0.85},
  "imprint": {"is_pill": true, "color": "white", "shape": "capsule", "confidence": 0.6}
}'
```

Expect `peel.recalls_by_lot`/`recalls_by_lot` to surface the WHO and NAFDAC records together;
the report should name both the falsified-product finding and the Cameroon/CAR country scope.

**C — Clean / unknown bottle.** Any un-recalled generic with no lot or NDC match. Deterministic
lookups return nothing, stage 3 runs 1–2 live Firecrawl searches, the fetched pages are indexed
into `peel-web-pages` with `fetched_at = now`, and the report should end in the exact
`no_adverse_findings` disclaimer, never a green checkmark or the word "safe":

```bash
curl -s localhost:8000/scans -X POST -H 'content-type: application/json' -d '{
  "device_id": "demo-3", "demo": true,
  "bottle": {"is_medication_container": true, "generic_name": "Ibuprofen",
             "strength": "200 mg", "form": "tablet", "confidence": 0.8}
}'
```

## Known limitations and future work

- **Pillbox is frozen at January 2021** — a product launched after that date is simply absent.
- **Lot *ranges* are not modelled outside one table-driven source.** Prose extraction
  (`extract_lots`, `extract_batches_from_prose`) only ever reads literal lot strings — "lots
  D24024xx through D24025xx" is not expanded. The MHRA table parser is the one exception: a
  `"From X to Y"` batch-column cell expands to every code between the endpoints when the range is
  numeric, equal-width and at most 200 codes wide, and otherwise falls back to just the endpoints.
- **Bare 3-4 digit batch codes in MHRA/Health Canada table cells are not indexed.**
  `code_token`'s code-shape rule requires an all-digit code to be 5-14 digits
  (`knowledge/normalize.py`), specifically so page numbers, short counters and truncated years in
  a table cell are never indexed as lots — a genuine short bare-digit batch is therefore missed by
  the table parser, though it may still be recovered from prose.
- **Health Canada lots exist only for the newest `--hc-detail-limit` (600) detail pages** — older
  recalls have a title/description but no parsed lot table.
- **Tier-2 regulators (EMA, TGA, CDSCO, SAHPRA, PMDA, …) are not seeded** — they appear only as
  domain-tier hints for live Firecrawl fetches (`research/web.py: _REGULATOR`), never as
  pre-seeded `peel-regulatory` records.
- **Hardware is mocked** (`HARDWARE_MODEL = "mock-spectrometry"`); a future `peel-spectra` index
  with real kNN spectral matching is out of scope here, and `hardware.spectrum` is stored
  `index: false, doc_values: false` — write-only today.
- **Agent Builder latency: ~25 s for conclusive scans, 40-60 s for ambiguous ones** (see "Latency
  protocol"). A measured end-to-end run with a warm web cache: 0.3 s normalize + 0.2 s
  deterministic (`partial`) + 1.3 s web + 27 s agent + 10 s coerce = 41 s to `complete`.
  `AGENT_BUILDER_TIMEOUT_S` (120 s) + a 5 s margin is the stage's ceiling, so a client must render
  the stage-2 `partial` report rather than block on `complete`.
- **Scan writes do not wait for an index refresh.** On Serverless `refresh="wait_for"` cost 3-5 s
  per write (~28 s per scan across its eight updates, plus seconds on the `POST /scans` response).
  `GET /scans/{id}` is a realtime GET and is unaffected; `GET /scans` (history) and the
  `prior_scans` signal are eventually consistent by a few seconds.
- **The daily Firecrawl credit cap is per process, not durable.** `_daily_used`
  (`research/web.py`) lives in memory and resets on a UTC date rollover *or* a process restart, so
  redeploying or crash-looping resets the counter early — it is a soft guard against runaway spend
  within one process's uptime, not a hard account-wide limit.
- **A process restart mid-pipeline leaves a scan at `partial` forever.** The background
  `asyncio.Task` driving research dies with the process and nothing resumes it automatically;
  call `POST /scans/{id}/research` (`{"force": true}` if needed) to re-run research on that scan.
- **Social/video/forum domains are excluded** from Firecrawl (`EXCLUDED_DOMAINS`) — a Facebook or
  Reddit post is never evidence, at the cost of missing genuinely useful crowd reports there.
- **No authentication.** `device_id` is an arbitrary client string with no verification, and CORS
  is wide open (`allow_origins=["*"]`) — fine for a hackathon demo, not for production.

## Runpod deployment

- Pod: `peel-fastapi` (`<pod-id>`), `US-CA-2`.
- CPU: `cpu3g`, 4 vCPUs, 16 GB RAM, 10 GB container disk. Compute: $0.16/hour at deployment; container storage is additional.
- Persistent network volume: `peel-fastapi-data` (`xylsp3iw1j`), 20 GB high-performance storage, mounted at `/workspace`.
- Image: `runpod/base:1.0.2-ubuntu2404`.
- API: https://<pod-id>-8000.proxy.runpod.net
- Interactive documentation: https://<pod-id>-8000.proxy.runpod.net/docs
- Application directory: `/workspace/peel/backend` (clone of the `runpod-deepgram` branch).

The app uses `scripts/runpod-start.sh` to install uv 0.12.15, select managed
Python 3.13, install locked runtime dependencies, and run Uvicorn on
`0.0.0.0:8000` without development reload. Runpod exposes `8000/http` and `22/tcp`.
The network volume is mounted at `/workspace`, so the app, credentials, and Python
environment survive container replacement. The pod's saved container command is:

```bash
bash -lc 'bash /start.sh & until test -f /workspace/peel/backend/scripts/runpod-start.sh; do sleep 2; done; exec bash /workspace/peel/backend/scripts/runpod-start.sh'
```

There is no `.env` on the pod. Credentials come from Runpod secrets, injected
as environment variables when the container boots. The pod env maps each variable
to a secret of the same name, for example
`OPENAI_API_KEY={{ RUNPOD_SECRET_OPENAI_API_KEY }}`. Secrets in use:
`OPENAI_API_KEY`, `FIRECRAWL_API_KEY`, `ELASTICSEARCH_URL`,
`ELASTICSEARCH_API_KEY`, `DEEPGRAM_API_KEY`. (`PUBLIC_API_BASE_URL` is still mapped on the pod
but nothing reads it any more; only `scripts/deepgram-chat.py` uses it locally.) Rotating a secret takes effect on the
next pod start. Editing the pod env replaces the container, so keep the app on the
network volume.

The deployed API currently has no client authentication. `/pill` still returns
mock spectrometry. External service calls require valid OpenAI, Firecrawl,
and Elasticsearch credentials.

Check the running API from your computer:

```bash
curl --fail https://<pod-id>-8000.proxy.runpod.net/health
```

```bash
curl --fail https://<pod-id>-8000.proxy.runpod.net/pill \
  -H 'Content-Type: application/json' \
  -d '{"status":"unknown"}'
```

Open the existing pod's SSH terminal:

```bash
ssh -tt -i ~/.ssh/id_ed25519 <pod-id>-644119c5@ssh.runpod.io
```

Then inspect the server log:

```bash
tail -n 50 /workspace/peel/backend/server.log
```

Manage restarts and terminate the deployment in the Runpod console:
https://console.runpod.io/pods

The pod is left running so the API stays available. Terminating it deletes its
container disk; the network volume remains and continues billing. For complete
cleanup, terminate the pod first, then delete `peel-fastapi-data` from the Runpod
Storage page. Deleting that volume permanently deletes the deployed files.
