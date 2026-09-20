"""Static-mount tests for the Atlas page: what a browser can reach, and the
guardrails that never depend on Elasticsearch or a running pipeline.

House style, per backend/tests/scans/test_router.py: sentence test names, a
bare FastAPI() plus the mount, fastapi.testclient.TestClient.

backend.graph.static_app is the other stream's module (the scene agent). It
did not exist for most of this session, so every test here is skipped —
never failed — until it lands.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

static_app = pytest.importorskip("backend.graph.static_app")

STATIC_DIR: Path = static_app.STATIC_DIR

ASSURANCE_WORDS_RE = re.compile(r"\b(safe|genuine|verified|authentic)\b", re.IGNORECASE)
HTML_REF_RE = re.compile(r'(?:src|href)\s*=\s*"([^"]+)"')
STYLE_BLOCK_RE = re.compile(r"<style\b[^>]*>.*?</style>", re.IGNORECASE | re.DOTALL)
BANNED_DOM_SINK_RE = re.compile(r"innerHTML|insertAdjacentHTML|outerHTML|document\.write")
EXTERNAL_PREFIXES = ("http://", "https://", "//")
IGNORED_REF_PREFIXES = EXTERNAL_PREFIXES + ("data:", "mailto:", "#")


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.mount("/atlas", static_app.atlas_static)
    with TestClient(app) as test_client:
        yield test_client


def _index_html_text() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


def _index_html_references() -> list[str]:
    return HTML_REF_RE.findall(_index_html_text())


def test_the_atlas_index_is_served_at_the_atlas_root(client: TestClient) -> None:
    response = client.get("/atlas/")
    assert response.status_code == 200
    assert "<html" in response.text.lower()


def test_every_local_path_the_page_references_exists_on_disk() -> None:
    references = _index_html_references()
    assert references, "expected index.html to reference at least one local file"
    for ref in references:
        if ref.startswith(IGNORED_REF_PREFIXES):
            continue
        target = (STATIC_DIR / ref.split("?", 1)[0].split("#", 1)[0]).resolve()
        assert target.is_file(), f"index.html references a file that does not exist on disk: {ref}"


def test_the_page_references_no_external_hosts() -> None:
    references = _index_html_references()
    external = [ref for ref in references if ref.startswith(EXTERNAL_PREFIXES)]
    assert external == [], f"index.html references an external host: {external}"


def test_ui_copy_never_uses_assurance_words() -> None:
    copy_js = (STATIC_DIR / "js" / "copy.js").read_text(encoding="utf-8")
    # CSS legitimately contains "safe-area-inset"; index.html's own inline
    # <style> block is excluded for the same reason before the lint runs.
    index_html_without_css = STYLE_BLOCK_RE.sub("", _index_html_text())

    for label, text in (("js/copy.js", copy_js), ("index.html", index_html_without_css)):
        match = ASSURANCE_WORDS_RE.search(text)
        assert match is None, f"{label} contains a banned assurance word: {match and match.group(0)!r}"


def test_no_script_writes_html_from_data() -> None:
    offenders: list[str] = []
    for path in (STATIC_DIR / "js").rglob("*.js"):
        if "vendor" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if BANNED_DOM_SINK_RE.search(text):
            offenders.append(str(path.relative_to(STATIC_DIR)))
    assert offenders == [], f"found a banned DOM sink (innerHTML/insertAdjacentHTML/outerHTML/document.write) in: {offenders}"


def test_vendored_files_match_the_manifest() -> None:
    manifest_path = STATIC_DIR / "vendor" / "VENDOR.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        target = STATIC_DIR / "vendor" / entry["file"]
        data = target.read_bytes()
        assert len(data) == entry["bytes"], f"{entry['file']} size no longer matches VENDOR.json"
        digest = hashlib.sha256(data).hexdigest()
        assert digest == entry["sha256"], f"{entry['file']} sha256 no longer matches VENDOR.json"


def test_the_csp_header_is_present(client: TestClient) -> None:
    response = client.get("/atlas/")
    policy = response.headers.get("content-security-policy")
    assert policy, "expected a Content-Security-Policy header on the atlas index"
    assert "default-src" in policy
