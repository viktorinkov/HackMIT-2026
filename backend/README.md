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

## Runpod deployment

- Pod: `peel-fastapi` (`lcbutbr44gta39`), `US-NC-2`.
- CPU: 2 vCPUs, 4 GB RAM, 10 GB container disk. Compute: $0.06/hour at deployment; container storage is additional.
- Persistent network volume: `peel-fastapi-data` (`5ssl74o5qz`), 10 GB standard storage, $0.70/month at deployment.
- Image: `runpod/base:1.0.2-ubuntu2404`.
- API: https://lcbutbr44gta39-8000.proxy.runpod.net
- Interactive documentation: https://lcbutbr44gta39-8000.proxy.runpod.net/docs
- Application directory: `/workspace/peel/backend`.

The app uses `scripts/runpod-start.sh` to install uv 0.12.15, select managed
Python 3.13, install locked runtime dependencies, and run Uvicorn on
`0.0.0.0:8000` without development reload. Runpod exposes `8000/http` and `22/tcp`.
The network volume is mounted at `/workspace`, so the app, credentials, and Python
environment survive container replacement. The pod's saved container command is:

```bash
bash -lc 'bash /start.sh & until test -f /workspace/peel/backend/scripts/runpod-start.sh; do sleep 2; done; exec bash /workspace/peel/backend/scripts/runpod-start.sh'
```

Credentials are in `/workspace/peel/backend/.env`, readable only by its owner.
The deployed API currently has no client authentication. `/pill` still returns
mock spectrometry. External service calls require valid OpenAI, Firecrawl,
and Elasticsearch credentials.

Check the running API from your computer:

```bash
curl --fail https://lcbutbr44gta39-8000.proxy.runpod.net/health
```

```bash
curl --fail https://lcbutbr44gta39-8000.proxy.runpod.net/pill \
  -H 'Content-Type: application/json' \
  -d '{"status":"unknown"}'
```

Open the existing pod's SSH terminal:

```bash
ssh -tt -i ~/.ssh/id_ed25519 lcbutbr44gta39-6441115f@ssh.runpod.io
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
