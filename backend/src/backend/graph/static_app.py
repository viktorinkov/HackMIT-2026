"""The static mount for the Atlas page, served at ``/atlas/``.

Every response carries the same policy. ``script-src`` stays strict: the only inline
script on the page is the import map, and its sha256 is computed once at import from
the real ``index.html``, so the hash can never drift from the file. ``style-src``
needs ``'unsafe-inline'`` because both vendored bundles inject a ``<style>`` element
at load time.
"""

from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path
from typing import Any

from starlette.responses import Response
from starlette.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).parent / "static"

_IMPORT_MAP_RE = re.compile(r'<script type="importmap">(.*?)</script>', re.DOTALL)

_JS_SUFFIXES = (".js", ".mjs")
_IMMUTABLE_PREFIX = "vendor/"


def _import_map_hash() -> str:
    """The sha256 of the exact text between the import map's script tags."""
    try:
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    except OSError:  # pragma: no cover - the page is shipped with the package
        return ""
    match = _IMPORT_MAP_RE.search(html)
    if not match:  # pragma: no cover - guarded by test_static.py
        return ""
    digest = hashlib.sha256(match.group(1).encode("utf-8")).digest()
    return f" 'sha256-{base64.b64encode(digest).decode('ascii')}'"


CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'none'",
        f"script-src 'self'{_import_map_hash()}",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "connect-src 'self'",
        "font-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'self'",
    )
)


class AtlasStaticFiles(StaticFiles):
    """``StaticFiles`` that stamps the Atlas policy onto every response."""

    async def get_response(self, path: str, scope: Any) -> Response:
        response = await super().get_response(path, scope)
        headers = response.headers
        headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        headers["X-Content-Type-Options"] = "nosniff"
        headers["Referrer-Policy"] = "no-referrer"
        if path.startswith(_IMMUTABLE_PREFIX):
            headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            headers["Cache-Control"] = "no-cache"
        if path.endswith(_JS_SUFFIXES):
            headers["Content-Type"] = "text/javascript; charset=utf-8"
        return response


# check_dir=False: a deployment that ships without the page fails only requests under
# /atlas/, instead of failing the import of backend.app and taking the whole API down.
atlas_static = AtlasStaticFiles(directory=STATIC_DIR, html=True, check_dir=False)
