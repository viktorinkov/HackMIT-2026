# Peel API

FastAPI backend. Uses Python 3.13 and the dependencies pinned in `uv.lock`.

## Local development

From the repository root:

```bash
cd backend
uv sync --locked
```

If `.env` does not already exist, create it and fill in the service credentials:

```bash
cp -n .env.example .env
```

Start the development server:

```bash
uv run backend
```

MongoDB Atlas stores scans and concern reports. If `MONGODB_URI` is empty, scans stay in process memory. If the URI is set and Mongo is unreachable, requests fail with 502 — there is no silent memory fallback.

Scan report (always returns `bottle`, `imprint`, and `pill`). Voice Agent clients call `POST /deepgram/session` instead of pasting a prompt:

```bash
curl --fail -X POST http://127.0.0.1:8000/scans?fixture=mismatch
curl --fail http://127.0.0.1:8000/scans/$SCAN_ID
curl --fail -X POST http://127.0.0.1:8000/deepgram/session \
  -H 'Content-Type: application/json' \
  -d "{\"scan_id\":\"$SCAN_ID\"}"
```

`GET /scans/{scan_id}/playground-prompt` remains for debugging. Product path: [docs/deepgram/VALIDATION.md](../docs/deepgram/VALIDATION.md).

## Runpod deployment

- Pod: `peel-fastapi` (`m2cw0a06ep8e5g`), `US-CA-2`.
- CPU: `cpu3g`, 4 vCPUs, 16 GB RAM, 10 GB container disk. Compute: $0.16/hour at deployment; container storage is additional.
- Persistent network volume: `peel-fastapi-data` (`xylsp3iw1j`), 20 GB high-performance storage, mounted at `/workspace`.
- Image: `runpod/base:1.0.2-ubuntu2404`.
- API: https://m2cw0a06ep8e5g-8000.proxy.runpod.net
- Interactive documentation: https://m2cw0a06ep8e5g-8000.proxy.runpod.net/docs
- Application directory: `/workspace/peel/backend` (clone of the `run-pod-eleven-labs` branch).

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
`ELASTICSEARCH_API_KEY`, `DEEPGRAM_API_KEY`, `MONGODB_URI`. Rotating a secret takes effect on the
next pod start. Editing the pod env replaces the container, so keep the app on the
network volume.

The deployed API currently has no client authentication. `/pill` still returns
mock spectrometry. External service calls require valid OpenAI, Firecrawl,
and Elasticsearch credentials.

Check the running API from your computer:

```bash
curl --fail https://m2cw0a06ep8e5g-8000.proxy.runpod.net/health
```

```bash
curl --fail https://m2cw0a06ep8e5g-8000.proxy.runpod.net/pill \
  -H 'Content-Type: application/json' \
  -d '{"status":"unknown"}'
```

Open the existing pod's SSH terminal:

```bash
ssh -tt -i ~/.ssh/id_ed25519 m2cw0a06ep8e5g-644119c5@ssh.runpod.io
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
