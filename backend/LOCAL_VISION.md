# Local bottle and pill extraction

The two existing `/photo-identification/{bottle,imprint}` endpoints now use an
in-process Apple Silicon model. There is no OpenAI vision call or cloud fallback.
The mobile response structure stays compatible; personal/free-text fields are
returned as null or empty lists. This is a synthetic-data pilot, not a validated
replacement for GPT's real-photo extraction accuracy.

Base model: [SmolVLM 500M Instruct](https://huggingface.co/HuggingFaceTB/SmolVLM-500M-Instruct),
Apache 2.0, using the
[MLX 4-bit conversion](https://huggingface.co/mlx-community/SmolVLM-500M-Instruct-4bit)
at revision `462811eef5e83cee4df69ef545b31cd6adf0cc50`.
[MLX-VLM](https://github.com/Blaizzy/mlx-vlm) provides inference and QLoRA training.
Only small language-model adapters are trained; base vision weights remain frozen.

## Reproduce on an Apple Silicon Mac

From `backend/`:

```bash
uv sync --extra local-vision
uv run --extra local-vision python scripts/local_vision.py prepare
uv run --extra local-vision python scripts/local_vision.py download
uv run --extra local-vision python scripts/local_vision.py evaluate
uv run --extra local-vision python scripts/local_vision.py train --steps 128
uv run --extra local-vision python scripts/local_vision.py evaluate --adapter
uv run --extra local-vision backend
```

Keep `--extra local-vision` on `uv run` so uv does not remove the optional runtime.
The download is the only step that needs Hugging Face network access. Training and
inference explicitly use local paths and offline mode, with telemetry disabled.
No Hugging Face login or paid inference endpoint is needed.

Artifacts live in gitignored `backend/data/vision/`:

- `base/`: downloaded model, tokenizer and pinned provenance.
- `adapter/`: trained `adapters.safetensors`, adapter config, and `run.json`.
- `train.jsonl`, `valid.jsonl`, `test.jsonl`: disjoint synthetic records.
- `evaluation/base.json`, `evaluation/adapter.json`: identical held-out comparison.
- `evaluation/generated-bottle.png`, `evaluation/generated-pill.png`: reviewed
  GPT Image examples, when present.

The training command refuses to overwrite an existing adapter. Move the directory
before starting a new run. Use `VISION_MODEL_PATH` and `VISION_ADAPTER_PATH` to point
the backend at copies of the model and adapter. Defaults are independent of cwd.
Missing weights, missing dependencies, invalid images or invalid model JSON fail
closed with a generic 502; no raw model output is exposed in error responses.
This runtime targets macOS arm64, not iOS/Android or the Linux RunPod deployment.

## Dataset and evaluation

`prepare` creates 64 training, 8 validation and 16 test examples from a fixed seed.
Labels are rendered from known text; no real patient image or existing test photo
is used for training. Examples include bottles, round/oval tablets, blank negative
images, and `[REDACTED]` patient placeholders. These are deliberately simple
synthetic examples, with substantial domain differences from camera photos.

The extra GPT Image bottle and pill are reserved for evaluation and never trained
on. Their ground truth was checked visually. Built-in imagegen bottle prompt:

> A photorealistic smartphone photo of a single amber bottle, white cap, kitchen
> counter, natural window light. Entire label legible: SYNTHETIC SAMPLE;
> AMOXICILLIN; 500 mg; 30 capsules; LOT: DEMO427; EXP: 2028-06. No other text,
> identifiers, brands, barcodes or pills outside the bottle.

The pill prompt requests a single white round unscored tablet printed `L484`, on
dark blue fabric in natural light, with no other objects or text. Both generation
prompts are recorded in `data/vision/evaluation/imagegen-prompt.txt`.
On a fresh checkout these optional images are absent, so `prepare` produces 16 tests.
The default comparison evaluates eight procedural images plus the generated photos
when available. It reports JSON validity, exact records and non-null field accuracy;
confidence is excluded from field matching. These tiny synthetic metrics cannot
establish real-photo accuracy, drug identity, authenticity or clinical suitability.
Readable confidence is the model's uncalibrated self-report.

Before deployment, collect independently labeled, de-identified camera photos,
including tiny imprints, curved labels, blur, glare, partial text and non-medication
objects. Compare field accuracy and hallucinations against the current baseline.
The pilot train command accepts only its procedural synthetic records by design.

## Privacy boundaries

- Uploaded pixels stay in backend memory and are processed on that Mac. They are
  never written to disk by this extraction path or uploaded to a model provider.
  Image metadata is removed by decoding and converting to RGB.
- Patient/prescriber identity, Rx number, pharmacy, directions, warnings, arbitrary
  label text and notes are excluded from the model contract and discarded in code,
  even if the model emits them. Existing API fields remain null/empty for clients.
- Only product facts (names, strength, lot, expiry, NDC, etc.) and pill appearance
  fields are allowed. An additional conservative filter rejects obvious personal
  text markers. **This does not guarantee that a model will never place a person's
  name inside an allowed product field.** A validated local entity detector or a
  product-vocabulary gate would be needed for a stronger output guarantee.
- Synthetic fine-tuning adds no real patient PII. It cannot certify that the upstream
  pretrained model contains no PII, nor erase its original training data.
- A phone still uploads its image to the configured backend. Use a trusted Mac
  and transport appropriate to your deployment. Running the backend in a cloud VM
  would move this privacy boundary to that VM.
- Research, Elasticsearch storage, web search and voice remain external services.
  This change is local photo extraction, not an end-to-end offline app. Existing
  `SCANS_STORE_SENSITIVE` behavior for separately supplied scan data is unchanged.

Photos, model outputs and adapters are not automatically uploaded, committed or
used to train on future scans. Generated data and weights are gitignored.
