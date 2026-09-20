"""FastAPI WebSocket ingestion for TruePill dissolution runs.

Protocol (JSON messages over /ws):

  client -> {"type": "start_run", "run_id", "wavelengths", "sample", "max_duration_seconds"}
  client -> {"type": "reading", "reading": {...}}      (repeat at ~1 Hz)
  server -> {"type": "partial_result", ...}            (after each reading)
  client -> {"type": "end_run"}
  server -> {"type": "final_result", ...}

Legacy single-scan path (still supported):

  client -> {"type": "scan", "scan": {...}}            (old snapshot event)
  server -> {"type": "final_result", ...}              (immediately)

A run also closes automatically when a reading's t_seconds exceeds the run's
max_duration_seconds; the final result is sent and the run is discarded.

Run: uvicorn truepill.server:app --reload   (from the directory that holds truepill/)
Library: TRUEPILL_LIBRARY=published requires
spectral_db.py and the reference spectra it reads, which are not in this
repository (their licence terms are unchecked for a public repo).
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from .models import (
    DissolutionRun,
    EndRunMessage,
    LegacyScanMessage,
    ReadingMessage,
    StartRunMessage,
)
from .verdict import PipelineConfig, evaluate_run, partial_payload

log = logging.getLogger("truepill.server")


def _build_library() -> list:
    """Reference library selected by the TRUEPILL_LIBRARY environment variable."""
    source = os.environ.get("TRUEPILL_LIBRARY", "published").strip().lower()
    if source == "published":
        try:
            from .spectral_db import build_published_reference_library
        except ImportError as e:
            raise RuntimeError(
                "TRUEPILL_LIBRARY=published needs spectral_db.py and its reference spectra, "
                "which are not shipped in this repository"
            ) from e

        entries, excluded = build_published_reference_library()
        for name, reason in excluded.items():
            log.warning("published library: %s excluded - %s", name, reason)
        if not entries:
            raise RuntimeError("no published spectrum is usable on the configured LED channels")
        return entries
    raise RuntimeError("Synthetic libraries are disabled. Use the measured backend /pill endpoint.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Swap for a Supabase-backed loader once the schema migration is approved.
    # Pre-seeding app.state.library (e.g. in a test) wins over building one.
    if not hasattr(app.state, "library"):
        app.state.library = _build_library()
    if not hasattr(app.state, "config"):
        app.state.config = PipelineConfig()
    yield


app = FastAPI(title="TruePill ingestion", lifespan=lifespan)


def _final_payload(run: DissolutionRun, library: list, config: PipelineConfig) -> dict[str, Any]:
    result = evaluate_run(run, library, config)
    return {"type": "final_result", "run_id": run.run_id, **result.payload()}


def _error(detail: str) -> dict[str, Any]:
    return {"type": "error", "detail": detail}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    library = app.state.library
    config: PipelineConfig = app.state.config

    run: DissolutionRun | None = None
    max_duration = 3600.0

    try:
        while True:
            raw = await ws.receive_json()
            msg_type = raw.get("type")

            if msg_type == "start_run":
                try:
                    start = StartRunMessage.model_validate(raw)
                except ValidationError as e:
                    await ws.send_json(_error(str(e)))
                    continue
                run = DissolutionRun(
                    run_id=start.run_id,
                    wavelengths=start.wavelengths,
                    sample=start.sample,
                )
                max_duration = start.max_duration_seconds
                await ws.send_json({"type": "run_started", "run_id": run.run_id})

            elif msg_type == "reading":
                if run is None:
                    await ws.send_json(_error("no open run - send start_run first"))
                    continue
                try:
                    reading = ReadingMessage.model_validate(raw).reading
                    run.add_reading(reading)
                except (ValidationError, ValueError) as e:
                    await ws.send_json(_error(str(e)))
                    continue
                try:
                    await ws.send_json({"run_id": run.run_id, **partial_payload(run, library)})
                except Exception as e:  # a bad reading must not kill the socket
                    await ws.send_json(_error(f"partial evaluation failed: {e}"))
                if reading.t_seconds >= max_duration:
                    try:
                        await ws.send_json(_final_payload(run, library, config))
                    except Exception as e:
                        await ws.send_json(_error(f"evaluation failed: {e}"))
                    run = None

            elif msg_type == "end_run":
                if run is None:
                    await ws.send_json(_error("no open run to end"))
                    continue
                EndRunMessage.model_validate(raw)
                try:
                    await ws.send_json(_final_payload(run, library, config))
                except Exception as e:
                    await ws.send_json(_error(f"evaluation failed: {e}"))
                run = None

            elif msg_type == "scan":
                # Legacy single-snapshot path: one reading, immediate verdict.
                try:
                    scan = LegacyScanMessage.model_validate(raw).scan
                except ValidationError as e:
                    await ws.send_json(_error(str(e)))
                    continue
                try:
                    await ws.send_json(_final_payload(scan.as_run(), library, config))
                except Exception as e:
                    await ws.send_json(_error(f"evaluation failed: {e}"))

            else:
                await ws.send_json(_error(f"unknown message type: {msg_type!r}"))

    except WebSocketDisconnect:
        pass
