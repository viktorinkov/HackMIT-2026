#!/usr/bin/env python3
"""Flutter Results chat, in a terminal.

Same client path the app will use: Runpod POST /deepgram/session, then
wss://agent.deepgram.com/v1/agent/converse with Authorization: Token.
Typing here is Flutter's text chat. An 80 ms linear16 stream stands in
for the open microphone so Deepgram does not close the listen socket.

From backend/:
    uv run --with websockets python scripts/deepgram-chat.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    import websockets
except ImportError:
    sys.exit("From backend/: uv run --with websockets python scripts/deepgram-chat.py")

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
# 80 ms of linear16 / 24 kHz / mono — never a zero-length frame.
FRAME_MS = 80
SILENCE = bytes(24000 * 2 * FRAME_MS // 1000)
KEEPALIVE_EVERY = 8.0

# API fixture, menu label, B↔I, B↔P, I↔P (None = not a name-mismatch row).
CASES: tuple[tuple[str, str, str | None, str | None, str | None], ...] = (
    ("mismatch", "Bottle mismatch", "≠", "≠", "="),
    ("mismatch_bottle_pill", "Bottle-pill mismatch", "=", "≠", "≠"),
    ("mismatch_pill_imprint", "Pill-imprint mismatch", "≠", "=", "≠"),
    ("mismatch_all", "All-channel mismatch", "≠", "≠", "≠"),
    ("suspected_degradation", "Quality concern", None, None, None),
    ("nitroglycerin", "Degraded", None, None, None),
    ("fake", "Fake pill", None, None, None),
    ("pending", "Incomplete scan", None, None, None),
)
CASE_OPTIONS: tuple[tuple[str, str], ...] = tuple((name, label) for name, label, *_ in CASES)
ALIASES = {
    "mismatch_bottle": "mismatch",
    "degraded": "nitroglycerin",
}
OPENED = {name: label for name, label, *_ in CASES}
_SPECTRUM = [0.1] * 16
CASE_PAYLOADS: dict[str, dict] = {
    "mismatch": {
        "device_id": "deepgram-chat",
        "demo": True,
        "bottle": {
            "is_medication_container": True,
            "generic_name": "acetaminophen",
            "strength": "500 mg",
            "form": "tablet",
            "confidence": 0.9,
        },
        "imprint": {"is_pill": True, "imprint": "DEMO-B", "confidence": 0.9},
        "hardware": {
            "status": "real",
            "spectrum": _SPECTRUM,
            "pill_type": "Ibuprofen",
            "degraded": False,
            "confidence": 0.92,
        },
        "hardware_model": "mock-spectrometry",
    },
    "mismatch_bottle_pill": {
        "device_id": "deepgram-chat",
        "demo": True,
        "bottle": {
            "is_medication_container": True,
            "generic_name": "acetaminophen",
            "strength": "500 mg",
            "form": "tablet",
            "confidence": 0.9,
        },
        "imprint": {"is_pill": True, "imprint": "DEMO-A", "confidence": 0.9},
        "hardware": {
            "status": "real",
            "spectrum": _SPECTRUM,
            "pill_type": "Ibuprofen",
            "degraded": False,
            "confidence": 0.92,
        },
        "hardware_model": "mock-spectrometry",
    },
    "mismatch_pill_imprint": {
        "device_id": "deepgram-chat",
        "demo": True,
        "bottle": {
            "is_medication_container": True,
            "generic_name": "ibuprofen",
            "strength": "200 mg",
            "form": "tablet",
            "confidence": 0.9,
        },
        "imprint": {"is_pill": True, "imprint": "DEMO-B", "confidence": 0.9},
        "hardware": {
            "status": "real",
            "spectrum": _SPECTRUM,
            "pill_type": "Ibuprofen",
            "degraded": False,
            "confidence": 0.92,
        },
        "hardware_model": "mock-spectrometry",
    },
    "mismatch_all": {
        "device_id": "deepgram-chat",
        "demo": True,
        "bottle": {
            "is_medication_container": True,
            "generic_name": "acetaminophen",
            "strength": "500 mg",
            "form": "tablet",
            "confidence": 0.9,
        },
        "imprint": {"is_pill": True, "imprint": "DEMO-C", "confidence": 0.9},
        "hardware": {
            "status": "real",
            "spectrum": _SPECTRUM,
            "pill_type": "Naproxen",
            "degraded": False,
            "confidence": 0.92,
        },
        "hardware_model": "mock-spectrometry",
    },
    "suspected_degradation": {
        "device_id": "deepgram-chat",
        "demo": True,
        "bottle": {
            "is_medication_container": True,
            "generic_name": "acetaminophen",
            "strength": "500 mg",
            "form": "tablet",
            "confidence": 0.9,
        },
        "imprint": {"is_pill": True, "imprint": "DEMO-A", "confidence": 0.9},
        "hardware": {
            "status": "substandard",
            "spectrum": _SPECTRUM,
            "pill_type": "acetaminophen",
            "degraded": True,
            "confidence": 0.78,
        },
        "hardware_model": "mock-spectrometry",
    },
    "nitroglycerin": {
        "device_id": "deepgram-chat",
        "demo": True,
        "bottle": {
            "is_medication_container": True,
            "generic_name": "nitroglycerin",
            "strength": "0.4 mg",
            "form": "tablet",
            "confidence": 0.9,
        },
        "imprint": {"is_pill": True, "imprint": "DEMO-N", "confidence": 0.9},
        "hardware": {
            "status": "substandard",
            "spectrum": _SPECTRUM,
            "pill_type": "nitroglycerin",
            "degraded": True,
            "confidence": 0.78,
        },
        "hardware_model": "mock-spectrometry",
    },
    "fake": {
        "device_id": "deepgram-chat",
        "demo": True,
        "bottle": {
            "is_medication_container": True,
            "generic_name": "acetaminophen",
            "strength": "500 mg",
            "form": "tablet",
            "confidence": 0.9,
        },
        "imprint": {"is_pill": True, "imprint": "DEMO-A", "confidence": 0.9},
        "hardware": {
            "status": "fake",
            "spectrum": _SPECTRUM,
            "pill_type": "Ibuprofen",
            "degraded": False,
            "confidence": 0.88,
        },
        "hardware_model": "mock-spectrometry",
    },
    "pending": {
        "device_id": "deepgram-chat",
        "demo": True,
        "bottle": {
            "is_medication_container": True,
            "generic_name": "acetaminophen",
            "confidence": 0.9,
        },
    },
}


def _load_dotenv() -> None:
    if not ENV_PATH.is_file():
        return
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _peel_api() -> str:
    api = (os.environ.get("API") or os.environ.get("PUBLIC_API_BASE_URL") or "").rstrip("/")
    if not api:
        sys.exit("Set API or PUBLIC_API_BASE_URL.")
    if "127.0.0.1" in api or "localhost" in api:
        sys.exit(f"Refusing {api}. The Flutter client talks to Runpod.")
    return api


def _request(method: str, url: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    headers = {"User-Agent": "peel-flutter-cli/1"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        sys.exit(f"{method} {url} -> {exc.code} {body}")


def _resolve_case(raw: str, options: tuple[tuple[str, str], ...]) -> str | None:
    folded = raw.casefold()
    if raw.isdigit() and 1 <= int(raw) <= len(options):
        return options[int(raw) - 1][0]
    for source, dest in ALIASES.items():
        if folded == source.casefold():
            return dest
    for name, label in options:
        if folded in {name.casefold(), label.casefold()}:
            return name
    names = [name for name, _ in options]
    matches = [name for name in names if name.casefold().startswith(folded)]
    alias_hits = [dest for source, dest in ALIASES.items() if source.casefold().startswith(folded)]
    combined = list(dict.fromkeys(matches + alias_hits))
    if len(combined) == 1:
        return combined[0]
    return None


def _ask(title: str, options: tuple[tuple[str, str], ...], default: str = "1") -> str:
    print(title)
    for index, (_name, label) in enumerate(options, 1):
        print(f"  {index}. {label}")
    while True:
        try:
            raw = input(f"Pick [{default}]: ").strip() or default
        except EOFError:
            return options[int(default) - 1][0]
        picked = _resolve_case(raw, options)
        if picked:
            return picked
        print(f"Pick 1-{len(options)}.")


def _print_cases() -> None:
    print(f"{'Case':<38}B↔I  B↔P  I↔P")
    for index, (_name, label, bottle_imprint, bottle_pill, imprint_pill) in enumerate(CASES, 1):
        prefix = f"  {index}. {label}"
        if bottle_imprint is None:
            extra = {
                "suspected_degradation": "names agree · quality flag",
                "nitroglycerin": "names agree · hardware degraded",
                "fake": "hardware reported fake",
                "pending": "no channels",
            }.get(_name, "")
            print(f"{prefix:<38}{extra}")
        else:
            print(
                f"{prefix:<38}{bottle_imprint:<5}{bottle_pill:<5}{imprint_pill}"
            )


def _pick_case(preset: str | None) -> str:
    if preset and preset.startswith("scan-"):
        return preset
    if preset:
        picked = _resolve_case(preset, CASE_OPTIONS)
        if picked:
            return picked
        sys.exit(f"Unknown case {preset!r}.")
    if not sys.stdin.isatty():
        env_fixture = os.environ.get("FIXTURE", "mismatch")
        return ALIASES.get(env_fixture, env_fixture)
    return _ask("Case", CASE_OPTIONS)


def _wait_ready(api: str, scan_id: str, timeout: float = 90) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        scan = _request("GET", f"{api}/scans/{scan_id}")
        if scan.get("status") in {"partial", "complete"} and scan.get("research"):
            return scan
        if scan.get("status") == "error":
            sys.exit(f"scan {scan_id} failed")
        time.sleep(2)
    sys.exit(f"scan {scan_id} is not ready")


def _open_results_chat(api: str, fixture: str) -> dict:
    if fixture.startswith("scan-"):
        scan_id = fixture
    else:
        payload = CASE_PAYLOADS.get(fixture)
        if payload is None:
            sys.exit(f"Unknown case {fixture!r}. Pass a scan- id or a case name.")
        scan = _request("POST", f"{api}/scans", payload)
        scan_id = scan["scan_id"]
        if fixture != "pending":
            _wait_ready(api, scan_id)
    session = _request("POST", f"{api}/deepgram/session", {"scan_id": scan_id})
    if session.get("authorization") != "Token" or "access_token" in session:
        sys.exit("Session is not the Flutter Token handoff")
    print(f"Opened {OPENED.get(fixture, fixture)} ({scan_id})")
    return session


async def _hold_open(ws, send_lock: asyncio.Lock) -> None:
    elapsed = 0.0
    while True:
        async with send_lock:
            await ws.send(SILENCE)
            if elapsed >= KEEPALIVE_EVERY:
                await ws.send(json.dumps({"type": "KeepAlive"}))
                elapsed = 0.0
        await asyncio.sleep(FRAME_MS / 1000)
        elapsed += FRAME_MS / 1000


async def _wait_idle(event: asyncio.Event, timeout: float, settle: float = 0.8) -> bool:
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
    except TimeoutError:
        return False
    while True:
        event.clear()
        try:
            await asyncio.wait_for(event.wait(), timeout=settle)
        except TimeoutError:
            return True


async def _chat(session: dict, api_key: str, fixture: str) -> str:
    async with websockets.connect(
        session["websocket_url"],
        additional_headers={"Authorization": f"Token {api_key}"},
        open_timeout=20,
        max_size=None,
    ) as ws:
        welcome = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
        if welcome.get("type") != "Welcome":
            sys.exit(f"Expected Welcome, got {welcome}")
        await ws.send(json.dumps(session["settings"]))
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=20)
            if isinstance(raw, bytes):
                continue
            msg = json.loads(raw)
            if msg.get("type") == "SettingsApplied":
                break
            if msg.get("type") == "Error":
                sys.exit(json.dumps(msg))
            _show(msg)

        incoming: asyncio.Queue[object] = asyncio.Queue()
        peel_done = asyncio.Event()
        closed = asyncio.Event()
        send_lock = asyncio.Lock()

        async def _read() -> None:
            try:
                async for raw in ws:
                    await incoming.put(raw)
            except websockets.exceptions.ConnectionClosed:
                closed.set()
                peel_done.set()

        async def _render() -> None:
            while True:
                raw = await incoming.get()
                if isinstance(raw, bytes):
                    continue
                msg = json.loads(raw)
                if _show(msg):
                    peel_done.set()
                    if msg.get("type") == "Error":
                        closed.set()

        reader = asyncio.create_task(_read())
        renderer = asyncio.create_task(_render())
        keepalive = asyncio.create_task(_hold_open(ws, send_lock))
        loop = asyncio.get_running_loop()
        smoke = os.environ.get("PEEL_SMOKE") == "1"
        action = "quit"
        try:
            await _wait_idle(peel_done, timeout=25)
            if closed.is_set():
                return action
            if smoke:
                await asyncio.sleep(12)
                if closed.is_set():
                    sys.exit("Audio timeout during idle")
                peel_done.clear()
                async with send_lock:
                    await ws.send(
                        json.dumps(
                            {
                                "type": "InjectUserMessage",
                                "content": "What should I do with this pill?",
                            }
                        )
                    )
                if not await _wait_idle(peel_done, timeout=30):
                    sys.exit("Peel: (no reply)")
                if closed.is_set():
                    sys.exit("Audio timeout after follow-up")
                print("idle+follow-up ok")
                return action
            print("Ask Peel, or type case / quit.")
            while not closed.is_set():
                try:
                    line = await loop.run_in_executor(None, lambda: input("You: "))
                except EOFError:
                    break
                text = line.strip()
                if not text:
                    continue
                if text in {"quit", "exit"}:
                    action = "quit"
                    break
                if text in {"case", "switch", "menu"}:
                    action = "switch"
                    break
                peel_done.clear()
                async with send_lock:
                    await ws.send(
                        json.dumps({"type": "InjectUserMessage", "content": text})
                    )
                if not await _wait_idle(peel_done, timeout=30):
                    print("Peel: (no reply)")
                if closed.is_set():
                    break
        finally:
            keepalive.cancel()
            reader.cancel()
            renderer.cancel()
        return action


def _show(msg: dict) -> bool:
    kind = msg.get("type")
    if kind == "ConversationText" and msg.get("role") == "assistant":
        print(f"Peel: {msg.get('content', '')}")
        return False
    if kind == "AgentAudioDone":
        return True
    if kind == "Error":
        print(f"Peel: something went wrong ({msg.get('description') or msg})")
        return True
    return False


def main() -> None:
    _load_dotenv()
    api_key = os.environ.get("DEEPGRAM_API_KEY", "")
    if not api_key:
        sys.exit("DEEPGRAM_API_KEY missing — Flutter will use the same usage key")
    args = [arg for arg in sys.argv[1:] if not arg.startswith("-")]
    if "--help" in sys.argv or "-h" in sys.argv:
        _print_cases()
        print("From backend/: uv run --with websockets python scripts/deepgram-chat.py")
        return
    smoke = os.environ.get("PEEL_SMOKE") == "1"
    preset = args[0] if args else (
        os.environ.get("SCAN_ID") or (os.environ.get("FIXTURE") if smoke else None)
    )
    api = _peel_api()
    while True:
        fixture = _pick_case(preset)
        preset = None
        session = _open_results_chat(api, fixture)
        action = asyncio.run(_chat(session, api_key, fixture))
        if smoke or action != "switch" or not sys.stdin.isatty():
            break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        sys.exit(130)
