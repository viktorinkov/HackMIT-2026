"""The package must work wherever it is dropped, under any name.

Copies the package into a fresh directory tree - nested inside another
package, and renamed - and drives it from a clean interpreter whose sys.path
knows nothing about the original. Any absolute self-import, any reliance on
the working directory, or any data file found by a path outside the package
fails here.
"""

from __future__ import annotations

import ast
import shutil
import subprocess
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent

DRIVER = """
import json, sys
import {dotted} as tp
lib = tp.load_library()                                   # finds its data beside itself
line = {{"sweep": {{"red": 900, "yellow": 740, "green": 1400}}, "swept": True}}
blank = [json.dumps(line)] * 5
smp = dict(line, sweep={{c: v * 10 ** -a for (c, v), a in zip(line["sweep"].items(), lib[0].spectrum)}})
r = tp.classify_capture(blank, [json.dumps(smp)] * 5, lib, expected_drug=lib[0].name)
out = tp.to_pill_hardware_result(r, tp.PEEL_BENCH_RIG.classifier)
assert (r.verdict, out["status"]) == ("PASS", "real"), (r, out)
assert "fastapi" not in sys.modules, "importing the package must not drag in the server"
print("OK", tp.__name__)
"""


def _drop_in(tmp_path: Path, *parents: str, name: str) -> tuple[Path, str]:
    root = tmp_path / "site"
    target = root
    for part in parents:
        target = target / part
        target.mkdir(parents=True)
        (target / "__init__.py").write_text("")
    shutil.copytree(PACKAGE, target / name, ignore=shutil.ignore_patterns("__pycache__", ".venv", ".pytest_cache"))
    return root, ".".join([*parents, name])


def _run(root: Path, dotted: str) -> str:
    proc = subprocess.run(
        [sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(root)!r})\n" + DRIVER.format(dotted=dotted)],
        capture_output=True, text=True, cwd="/", timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def test_works_nested_inside_another_package(tmp_path):
    root, dotted = _drop_in(tmp_path, "backend", "instruments", name="truepill")
    assert _run(root, dotted) == "OK backend.instruments.truepill"


def test_works_under_a_different_name(tmp_path):
    root, dotted = _drop_in(tmp_path, name="spectral_classifier")
    assert _run(root, dotted) == "OK spectral_classifier"


def test_no_module_imports_the_package_by_name():
    # The static half of the same guarantee: an absolute self-import would pass
    # above only by luck of what else is on sys.path.
    # Parsed, not grepped: docstrings legitimately show `from truepill import`.
    siblings = {p.stem for p in PACKAGE.glob("*.py")} | {PACKAGE.name}
    for path in PACKAGE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.level == 0:
                roots = [(node.module or "").split(".")[0]]
            elif isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            else:
                continue
            bad = siblings.intersection(roots)
            assert not bad, f"{path.relative_to(PACKAGE)}:{node.lineno} imports {sorted(bad)} absolutely"
