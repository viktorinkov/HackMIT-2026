#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
exec > >(tee -a server.log) 2>&1
export UV_CACHE_DIR="${UV_CACHE_DIR:-/workspace/.cache/uv}"
export UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-/workspace/.local/share/uv/python}"
export UV_PYTHON_PREFERENCE=only-managed
export PYTHONUNBUFFERED=1

# Keep the installer, Python, and dependencies together under /workspace.
UV_BIN=/workspace/.local/bin/uv
if [[ ! -x "$UV_BIN" ]]; then
    curl --fail --silent --show-error --location https://astral.sh/uv/0.12.15/install.sh \
        -o /tmp/peel-install-uv.sh
    UV_INSTALL_DIR=/workspace/.local/bin sh /tmp/peel-install-uv.sh
fi
"$UV_BIN" sync --locked --no-dev --python 3.13
exec .venv/bin/uvicorn backend.app:app --host 0.0.0.0 --port 8000
