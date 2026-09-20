# Merge plan: `main` into `run-pod-eleven-labs`

Date: 2026-09-19. No merge was done. Local `main` is updated to `228cbac`, the same commit as `origin/main`.

After the merge, the app uses the scan and the research agent from main. Our branch adds the Deepgram voice agent and a photo store in MongoDB. Our `scans` package and `docs/elevenlabs/` go away.

---

## Priority 1: Merge main

**1. Start the merge.**

```
git merge main
```

**2. Resolve the 9 conflicts.**

| File | Action |
|---|---|
| `scans/models.py`, `scans/router.py`, `scans/store.py` | Take the version from main |
| `app.py` | Take the side from main in each block |
| `pyproject.toml`, `.env.example`, `.gitignore` | Keep both sides |
| `uv.lock` | Take the version from main |
| `backend/README.md` | Take the version from main. Paste our RunPod section at the end. |

**3. Hide the pod address.** The ID `m2cw0a06ep8e5g` is in 4 files.

| File | Change |
|---|---|
| `config.py` | Set the default of `public_api_base_url` to `""` |
| `.env.example` | `PUBLIC_API_BASE_URL=` with no value |
| `scripts/deepgram-chat.py:27` | Delete `RUNPOD_API`. At lines 64-68, stop with a message if `API` and `PUBLIC_API_BASE_URL` are empty. |
| `backend/README.md` | In our RunPod section, write `<pod-id>` in place of the ID |

This command must show no result:

```
git grep -n m2cw0a06ep8e5g
```

The old address stays in the git history. A new pod gets a new address.

**4. Delete this line from `app.py`.** Git keeps it with no conflict, and it stops the app at start. It comes back in Priority 2.

```python
from backend.deepgram.router import router as deepgram_router
```

**5. Take `scans/__init__.py` from main.** Git keeps our version with no conflict, and our version breaks `tests/scans/test_router.py`.

```
git checkout main -- backend/src/backend/scans/__init__.py
```

**6. Repair `tests/research/test_contract.py`.** The test reads one file from `docs/elevenlabs/`, and the merge deletes that folder.

```
git show main:docs/elevenlabs/demo-contexts.json > backend/tests/research/demo-contexts.json
```

Replace lines 26-27 of the test with this line:

```python
FIXTURES = json.loads((Path(__file__).parent / "demo-contexts.json").read_text())
```

**7. Move the 2 files that Deepgram keeps.**

```
git mv backend/src/backend/scans/prompt.py backend/src/backend/deepgram/prompt.py
git mv backend/src/backend/scans/data/system-prompt.txt backend/src/backend/deepgram/system-prompt.txt
```

**8. Delete the other files of ours in `scans/`.**

```
git rm backend/src/backend/scans/{service,compare,assembler,fixtures}.py
git rm -r backend/src/backend/scans/data
```

**9. Make the lock, and run the tests.**

```
uv lock
uv run pytest
```

**10. Commit the merge with the new `uv.lock`.** `runpod-start.sh` does not start with an old lock.

**Done when:** the app starts, and pytest shows 0 import errors.

---

## Priority 2: Deepgram reads the scan from main

Each Deepgram file imports from our old `scans` package. The replacement is `to_scan_context(doc)` in `research/contract.py`. It returns this `dict`:

```
scan_id, revision, demo, status
bottle:    status, generic_name, brand_name, strength, form, expiration,
           lot_number, manufacturer, ndc, confidence
imprint:   status, observed_text, candidates[] (generic_name, strength, form)
hardware:  status, reported_status, candidate (generic_name, strength, form),
           degradation (status), limitations, model
research:  verdict, risk_level, headline, findings[], mismatches[], gaps[], next_steps[]
drug_facts[], sources[]
```

`bottle`, `imprint`, and `hardware` can be `None`. The key `research` is absent before the first report.

Our old code is still in git:

```
git show 9a1a045:backend/src/backend/scans/store.py
```

**1. Make `backend/mongo.py`.** Copy the connect and close code from our old `scans/store.py`. Add the close call and the `PyMongoError` handler to `app.py`.

**2. Get the scan from the new store.** In `deepgram/router.py`, call `await store.get(scan_id)`. If the result is `None`, return 404.

**3. Start the voice session only after the research.** If `status` is not `complete`, return 409.

`complete` can take 240 seconds. `partial` comes after about 16 seconds and already has a first verdict. If 240 seconds is too long for the demo, permit `partial` too.

**4. Change the field reads in `deepgram/session.py`.**

| Function | New source |
|---|---|
| `_bottle_name` | `bottle.generic_name` or `bottle.brand_name`, then `bottle.strength` |
| `_imprint_name` | `imprint.candidates[0].generic_name`, then `.strength` |
| The imprint marking | `imprint.observed_text` |
| `_pill_name` | `hardware.candidate.generic_name`. `candidate` is `None` if the hardware found no pill type. `strength` is always `None`. |
| `keyterms_from_scan` | The same name fields, and `imprint.observed_text` |

**5. Make the greeting shorter.** The research already writes a sentence for each verdict: `research.headline`. It also replaces unsafe text (`research/evidence.py:945`, `:1228`).

The new greeting has these parts:

1. "Hi, I'm Peel."
2. The demo line, if `demo` is true
3. The bottle line, the imprint line, and the pill line
4. If `hardware.reported_status` is `fake`, a line that says so
5. `research.headline`

Delete `_conflict_line`, the import of `pair_mismatches`, and the 4 branches on `finding`.

Item 4 is necessary. The verdict does not read the hardware result, so the headline never says `fake`.

**6. Change the prompt.** In `deepgram/prompt.py`, put `scan_context_json(doc)` into `{{scan_context}}`.

`system-prompt.txt` has no word about a recall, a verdict, or `fake`. Line 16 tells the agent to start with "evidence agrees, evidence conflicts, or there is not enough evidence". Replace line 16 with this line:

```
- Lead with research.headline. If research.verdict is recall_match, say the recall first. If hardware.reported_status is fake, say that first.
```

**7. Move the concern reports into `deepgram/`.** Copy these parts from our old `scans` files:

- The 2 report routes from `router.py`
- `ConcernReportCreate`, `ConcernReport`, and `PlaygroundPrompt` from `models.py`
- `add_concern_report` and `list_concern_reports` from `store.py`

`ConcernReport.snapshot` has the type `ScanReport` (`scans/models.py:89`). That type goes away. Change it to `dict[str, Any]`, and fill it with `to_scan_context(doc)`.

Change `reports_url()` at `deepgram/session.py:152` to the new path. Deepgram calls this address.

After Priority 1, the default of `public_api_base_url` is empty. In `POST /deepgram/session`, return 503 if it is empty. If you do not, Deepgram gets a bad address and drops each concern report.

**8. Put the Deepgram router back in `app.py`.**

**9. Repair `scripts/deepgram-chat.py:148`.** It calls `POST /scans?fixture=`. The new `POST /scans` has no fixtures, and it needs a `device_id`.

**10. Do a test with one real completed scan.** `POST /deepgram/session` must return 200.

The prompt limit is 25,000 characters, and the system prompt uses 6,898. The new context has `drug_facts`, `sources`, and `findings`, so it is longer than ours. If the prompt is too long, the route returns 500. Then cut `sources` from the context. A voice agent cannot say a URL.

**Done when:** the route returns 200 for a real scan, and the greeting is correct for a recall and for a `fake` pill.

---

## Priority 3: The photo store

No code saves a photo at this time. Our old MongoDB store holds only the text from a photo.

- Each photo goes through `read_photo()` at `photo_identification/vision.py:93`.
- A photo can be larger than 10 MB. A MongoDB document has a 16 MB limit. Thus the photo store must use GridFS.
- `POST /scans` already accepts `photos`, a list of `PhotoRef`. A `PhotoRef` has `target`, `sha256`, `bytes`, and `media_type`. `bytes` has no maximum.

**1. Increase the photo limit.** In `photo_identification/vision.py:31`, change `_MAX_IMAGE_BYTES` from 10 MB to 50 MB:

```python
_MAX_IMAGE_BYTES = 50 * 1024 * 1024
```

The error message at `vision.py:106-110` has the text "10 MB". Change it to show the new limit.

OpenAI is not a limit here. The photo goes to OpenAI as base64, which adds 33 %. OpenAI permits 512 MB for each request, and it makes large images smaller by pixel size.

One request holds the photo and its base64 copy in memory. For a 50 MB photo, this is approximately 200 MB.

**2. Save the photo in GridFS.** In the 2 photo routes (`bottle.py:57`, `imprint.py:47`), calculate the `sha256` of the bytes. Then save the bytes with `motor`:

```python
bucket = AsyncIOMotorGridFSBucket(db, bucket_name="photos")
await bucket.upload_from_stream(
    sha256, image_bytes,
    metadata={"target": target, "media_type": media_type},
)
```

GridFS permits 2 files with the same name. Before the save, look for the `sha256` in `photos.files`:

```python
await db["photos.files"].find_one({"filename": sha256})
```

If the file is there, do not save it again. Get `db` from `backend/mongo.py`.

**3. Return the `PhotoRef` in the response of the photo route.**

**4. Send that `PhotoRef` in `POST /scans`.**

**Done when:** a 20 MB photo that you send to `/photo-identification/bottle` is in the `photos.files` collection.
