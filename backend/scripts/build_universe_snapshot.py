"""Build the committed `graph/fixtures/universe.json` snapshot from the local
seed cache — no Elasticsearch, no network.

    uv run python scripts/build_universe_snapshot.py \\
        --from jsonl --data-dir /path/to/backend/data/normalized

Reads `health_canada.jsonl`, `mhra.jsonl`, `nafdac.jsonl`,
`openfda_enforcement.jsonl` and `who_alerts.jsonl` (the same files
`peel-seed` loads into `peel-regulatory`) read-only, and writes a
`GraphResponse`: 5 regulator nodes, the top medicines/manufacturers/countries
by record count, and weak aggregate links between them. Every node is
`backdrop=True`; this is the corpus backdrop, never a personal graph.

This is `/graph/universe`'s data source (design-data-api.md §4, T4): the live
aggregation path (T1/T2/T3) is cut for tonight, so this file — checked into
`graph/fixtures/universe.json` — is what the endpoint actually serves.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.graph.models import (  # noqa: E402
    GraphLink,
    GraphMeta,
    GraphNode,
    GraphResponse,
    TimelineBucket,
    clip_label,
    link_id,
    node_id,
)
from backend.knowledge import normalize  # noqa: E402

# file -> canonical `source_org` value stored on every record from that file.
SOURCE_FILES: dict[str, str] = {
    "openfda_enforcement.jsonl": "FDA",
    "who_alerts.jsonl": "WHO",
    "nafdac.jsonl": "NAFDAC",
    "mhra.jsonl": "MHRA",
    "health_canada.jsonl": "Health Canada",
}
REGULATORS: tuple[str, ...] = ("FDA", "WHO", "NAFDAC", "MHRA", "Health Canada")

DEFAULT_TOP_DRUGS = 40
DEFAULT_TOP_MFRS = 30
DEFAULT_TOP_COUNTRIES = 25

_JUNK_KEYS = {"various products", "various product", "various", "products", "unknown"}


# --------------------------------------------------------------------------- keys
#
# TODO: switch entirely to `backend.graph.keys` once that module is finished
# and stable (another stream is writing it tonight). For now: use it when it
# is importable, and fall back to a deliberately simple local normaliser
# (casefold, strip a legal suffix, cut at the first comma/paren) otherwise, so
# this script never depends on the other stream landing first.

try:
    from backend.graph.keys import (  # noqa: E402
        company_key as _keys_company_key,
        country_key as _keys_country_key,
        country_label as _keys_country_label,
        drug_key as _keys_drug_key,
        regulator_key as _keys_regulator_key,
        slug as _keys_slug,
    )

    _HAVE_GRAPH_KEYS = True
except Exception:  # noqa: BLE001 - the fallback below covers every case
    _HAVE_GRAPH_KEYS = False


_LEGAL_SUFFIXES = {
    "inc", "llc", "ltd", "limited", "corp", "corporation", "co", "company",
    "plc", "gmbh", "pvt", "usa",
}
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _local_slug(value: str | None) -> str | None:
    text = normalize.clean_text(value)
    if not text:
        return None
    out = _SLUG_RE.sub("-", text.casefold()).strip("-")
    return out or None


def _local_cut_at_first(text: str, markers: tuple[str, ...]) -> str:
    cut = len(text)
    for marker in markers:
        found = text.find(marker)
        if found > 0:
            cut = min(cut, found)
    return text[:cut]


def _local_drug_key(value: str | None) -> str | None:
    text = normalize.clean_text(value)
    if not text:
        return None
    text = _local_cut_at_first(text.casefold(), (",", "("))
    key = " ".join(text.split()).strip()
    return key or None


def _local_company_key(value: str | None) -> str | None:
    text = normalize.clean_text(value)
    if not text:
        return None
    text = _local_cut_at_first(text.casefold(), (",", "(", " - "))
    tokens = [tok.strip(".,;:()") for tok in text.split()]
    tokens = [tok for tok in tokens if tok]
    for index, token in enumerate(tokens):
        if index >= 1 and token in _LEGAL_SUFFIXES:
            tokens = tokens[:index]
            break
    key = " ".join(tokens).strip()
    return key or None


def drug_key(value: str | None) -> str | None:
    return _keys_drug_key(value) if _HAVE_GRAPH_KEYS else _local_drug_key(value)


def company_key(value: str | None) -> str | None:
    return _keys_company_key(value) if _HAVE_GRAPH_KEYS else _local_company_key(value)


def country_key(value: str | None) -> str | None:
    if _HAVE_GRAPH_KEYS:
        return _keys_country_key(value)
    found = normalize.extract_countries(value)
    return _local_slug(found[0]) if found else _local_slug(value)


def country_label(value: str | None) -> str | None:
    if _HAVE_GRAPH_KEYS:
        return _keys_country_label(value)
    found = normalize.extract_countries(value)
    return found[0] if found else normalize.clean_text(value)


def regulator_key(value: str | None) -> str | None:
    if _HAVE_GRAPH_KEYS:
        return _keys_regulator_key(value)
    return _local_slug(value)


def slug(value: str | None) -> str | None:
    return _keys_slug(value) if _HAVE_GRAPH_KEYS else _local_slug(value)


def _is_junk(key: str | None) -> bool:
    """Skip rule from the plan: >4 tokens, <3 chars, or a known-junk phrase."""
    if not key:
        return True
    if len(key) < 3:
        return True
    if key in _JUNK_KEYS:
        return True
    if len(key.split()) > 4:
        return True
    return False


# --------------------------------------------------------------------------- aggregation


class _Aggregate:
    def __init__(self) -> None:
        self.regulator_counts: Counter[str] = Counter()
        self.drug_counts: Counter[str] = Counter()
        self.drug_labels: dict[str, Counter[str]] = {}
        self.mfr_counts: Counter[str] = Counter()
        self.mfr_labels: dict[str, Counter[str]] = {}
        self.country_counts: Counter[str] = Counter()
        self.country_labels: dict[str, str] = {}
        self.reg_drug: Counter[tuple[str, str]] = Counter()
        self.reg_mfr: Counter[tuple[str, str]] = Counter()
        self.reg_country: Counter[tuple[str, str]] = Counter()
        self.drug_mfr: Counter[tuple[str, str]] = Counter()
        self.timeline: dict[int, Counter[str]] = {}
        self.max_indexed_at: str | None = None
        self.records = 0

    def _note_timeline(self, org: str, recency_date: str | None) -> None:
        if not recency_date or len(recency_date) < 4:
            return
        try:
            year = int(recency_date[:4])
        except ValueError:
            return
        self.timeline.setdefault(year, Counter())[org] += 1

    def add(self, org: str, record: dict[str, Any]) -> None:
        self.records += 1
        self.regulator_counts[org] += 1
        self._note_timeline(org, record.get("recency_date"))

        indexed_at = record.get("indexed_at")
        if indexed_at and (self.max_indexed_at is None or indexed_at > self.max_indexed_at):
            self.max_indexed_at = indexed_at

        drug_raw = list(record.get("drug_names") or []) + list(
            record.get("drug_names_extracted") or []
        )
        drug_keys: set[str] = set()
        for raw in drug_raw:
            key = drug_key(raw)
            if _is_junk(key):
                continue
            assert key is not None
            drug_keys.add(key)
            self.drug_labels.setdefault(key, Counter())[str(raw)] += 1
        for key in drug_keys:
            self.drug_counts[key] += 1
            self.reg_drug[(org, key)] += 1

        mfr_raw = record.get("manufacturer") or record.get("recalling_firm")
        mfr_key = company_key(mfr_raw)
        if not _is_junk(mfr_key):
            assert mfr_key is not None
            self.mfr_counts[mfr_key] += 1
            self.mfr_labels.setdefault(mfr_key, Counter())[str(mfr_raw)] += 1
            self.reg_mfr[(org, mfr_key)] += 1
            for drug in drug_keys:
                self.drug_mfr[(drug, mfr_key)] += 1

        for raw_country in record.get("countries") or []:
            key = country_key(raw_country)
            if not key:
                continue
            self.country_counts[key] += 1
            self.reg_country[(org, key)] += 1
            self.country_labels.setdefault(key, str(country_label(raw_country) or raw_country))


def _read_jsonl(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _aggregate_from_jsonl(data_dir: Path) -> _Aggregate:
    agg = _Aggregate()
    for filename, org in SOURCE_FILES.items():
        path = data_dir / filename
        if not path.exists():
            print(f"[WARN] {path} does not exist; {org} will be an empty node.", file=sys.stderr)
            continue
        count = 0
        for record in _read_jsonl(path):
            agg.add(org, record)
            count += 1
        print(f"  read {count} record(s) from {filename} ({org})")
    return agg


# --------------------------------------------------------------------------- graph building


def _weighted(count: int, max_count: int) -> float:
    import math

    if count <= 0 or max_count <= 0:
        return 0.0
    return math.log1p(count) / math.log1p(max_count)


def _top(counter: Counter[str], n: int) -> list[str]:
    return [key for key, _ in counter.most_common(n)]


def build_universe(agg: _Aggregate, *, top_drugs: int, top_mfrs: int, top_countries: int) -> GraphResponse:
    nodes: list[GraphNode] = []
    links: list[GraphLink] = []

    reg_ids: dict[str, str] = {}
    for org in REGULATORS:
        rkey = regulator_key(org)
        assert rkey is not None, f"regulator_key produced None for {org!r}"
        rid = node_id("regulator", rkey)
        reg_ids[org] = rid
        nodes.append(
            GraphNode(
                id=rid,
                type="regulator",
                label=clip_label(org),
                backdrop=True,
                count=agg.regulator_counts.get(org, 0),
                source_org=org,
                val=1.0 + _weighted(agg.regulator_counts.get(org, 0), max(agg.regulator_counts.values(), default=1)) * 4,
            )
        )

    drug_top = _top(agg.drug_counts, top_drugs)
    drug_ids: dict[str, str] = {}
    for key in drug_top:
        did = node_id("medicine", key)
        drug_ids[key] = did
        labels = agg.drug_labels.get(key)
        raw_label = labels.most_common(1)[0][0] if labels else key
        nodes.append(
            GraphNode(
                id=did,
                type="medicine",
                label=clip_label(raw_label.title(), fallback=key.title()),
                backdrop=True,
                count=agg.drug_counts[key],
                val=1.0 + _weighted(agg.drug_counts[key], max(agg.drug_counts.values(), default=1)) * 3,
            )
        )

    mfr_top = _top(agg.mfr_counts, top_mfrs)
    mfr_ids: dict[str, str] = {}
    for key in mfr_top:
        mid = node_id("manufacturer", key)
        mfr_ids[key] = mid
        labels = agg.mfr_labels.get(key)
        # The shortest raw variant seen is usually closest to the plain company
        # name, e.g. "Accord Healthcare" over "Accord Healthcare Limited -
        # Losartan Potassium 50mg Film-coated Tablets".
        raw_label = min(labels, key=len) if labels else key
        nodes.append(
            GraphNode(
                id=mid,
                type="manufacturer",
                label=clip_label(raw_label.title(), fallback=key.title()),
                backdrop=True,
                count=agg.mfr_counts[key],
                val=1.0 + _weighted(agg.mfr_counts[key], max(agg.mfr_counts.values(), default=1)) * 3,
            )
        )

    country_top = _top(agg.country_counts, top_countries)
    country_ids: dict[str, str] = {}
    for key in country_top:
        cid = node_id("country", key)
        country_ids[key] = cid
        label = agg.country_labels.get(key, key)
        nodes.append(
            GraphNode(
                id=cid,
                type="country",
                label=clip_label(label),
                backdrop=True,
                count=agg.country_counts[key],
                val=1.0 + _weighted(agg.country_counts[key], max(agg.country_counts.values(), default=1)) * 2,
            )
        )

    def _add_links(
        pairs: Counter[tuple[str, str]],
        left_ids: dict[str, str],
        right_ids: dict[str, str],
        kind: str,
    ) -> None:
        relevant = {pair: count for pair, count in pairs.items() if pair[0] in left_ids and pair[1] in right_ids}
        if not relevant:
            return
        max_count = max(relevant.values())
        for (left, right), count in relevant.items():
            source, target = left_ids[left], right_ids[right]
            links.append(
                GraphLink(
                    id=link_id(source, kind, target),
                    source=source,
                    target=target,
                    kind=kind,  # type: ignore[arg-type]
                    strong=False,
                    alert=False,
                    weight=max(0.05, _weighted(count, max_count)),
                    count=count,
                )
            )

    _add_links(agg.reg_drug, reg_ids, drug_ids, "about")
    _add_links(agg.drug_mfr, mfr_ids, drug_ids, "makes")
    _add_links(agg.reg_mfr, reg_ids, mfr_ids, "names_maker")
    _add_links(agg.reg_country, reg_ids, country_ids, "affects")

    timeline = [
        TimelineBucket(year=year, total=sum(by_org.values()), by_org=dict(by_org))
        for year, by_org in sorted(agg.timeline.items())
        if sum(by_org.values()) > 0
    ]

    index_date = (agg.max_indexed_at or normalize.to_iso(datetime.now(UTC)) or "").split("T")[0]

    meta = GraphMeta(
        scans=0,
        generated_at=normalize.to_iso(datetime.now(UTC)),
        source="snapshot",
        demo=False,
        truncated=False,
        index_date=index_date or None,
        notice=(
            "Aggregated from the seeded regulatory corpus. This is a summary view of the "
            "public record, not an assurance about any medicine."
        ),
        counts={org: agg.regulator_counts.get(org, 0) for org in REGULATORS},
        timeline=timeline,
    )

    return GraphResponse(nodes=nodes, links=links, meta=meta)


# --------------------------------------------------------------------------- CLI


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="source", choices=["jsonl"], default="jsonl")
    parser.add_argument("--data-dir", required=True, type=Path, help="directory holding the *.jsonl seed cache")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "src" / "backend" / "graph" / "fixtures" / "universe.json",
    )
    parser.add_argument("--top-drugs", type=int, default=DEFAULT_TOP_DRUGS)
    parser.add_argument("--top-mfrs", type=int, default=DEFAULT_TOP_MFRS)
    parser.add_argument("--top-countries", type=int, default=DEFAULT_TOP_COUNTRIES)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.data_dir.is_dir():
        print(f"ERROR: --data-dir {args.data_dir} is not a directory", file=sys.stderr)
        return 1

    print(f"Reading the seed cache from {args.data_dir} (graph.keys available: {_HAVE_GRAPH_KEYS})")
    agg = _aggregate_from_jsonl(args.data_dir)
    print(
        f"Aggregated {agg.records} record(s): {len(agg.drug_counts)} distinct medicine key(s), "
        f"{len(agg.mfr_counts)} manufacturer key(s), {len(agg.country_counts)} countries."
    )

    response = build_universe(
        agg, top_drugs=args.top_drugs, top_mfrs=args.top_mfrs, top_countries=args.top_countries
    )
    # Round-trip through the model once more: this is the same validation the
    # fixture-loading test performs, so a schema mistake fails here, not later.
    validated = GraphResponse.model_validate(response.model_dump())

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(validated.model_dump(mode="json"), indent=2, sort_keys=False) + "\n")
    print(
        f"Wrote {len(validated.nodes)} node(s) and {len(validated.links)} link(s) to {args.out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
