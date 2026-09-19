"""RxNav (NLM) lookups: free, no key. Used to repair OCR-mangled drug names and
to flag NDCs the FDA no longer lists. Every call is best-effort: failures and
timeouts return None so research never blocks on RxNav."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

_BASE = "https://rxnav.nlm.nih.gov/REST"
# approximateTerm scores are unbounded; below this the match is usually noise.
_MIN_SCORE = 5.0


@dataclass(frozen=True)
class RxTerm:
    rxcui: str
    name: str
    score: float


@dataclass(frozen=True)
class NdcStatus:
    ndc11: str
    status: str  # ACTIVE | OBSOLETE | ALIEN | UNKNOWN
    active: bool
    rxcui: str | None
    concept_name: str | None


class RxNavClient:
    def __init__(self, *, enabled: bool = True, timeout_s: float = 2.0) -> None:
        self._enabled = enabled
        self._timeout = timeout_s

    async def _get(self, path: str, params: dict[str, str]) -> dict | None:
        if not self._enabled:
            return None
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(f"{_BASE}{path}", params=params)
            if response.status_code != 200:
                return None
            data = response.json()
            return data if isinstance(data, dict) else None
        except (httpx.HTTPError, ValueError):
            return None

    async def approximate_term(self, term: str | None) -> RxTerm | None:
        if not term or len(term.strip()) < 3:
            return None
        data = await self._get("/approximateTerm.json", {"term": term.strip(), "maxEntries": "3"})
        candidates = ((data or {}).get("approximateGroup") or {}).get("candidate") or []
        for candidate in candidates:
            try:
                score = float(candidate.get("score") or 0)
            except (TypeError, ValueError):
                continue
            rxcui, name = candidate.get("rxcui"), candidate.get("name")
            if rxcui and name and score >= _MIN_SCORE:
                return RxTerm(rxcui=str(rxcui), name=str(name), score=score)
        return None

    async def ndc_status(self, ndc11: str | None) -> NdcStatus | None:
        if not ndc11:
            return None
        data = await self._get("/ndcstatus.json", {"ndc": ndc11})
        status = (data or {}).get("ndcStatus") or {}
        if not status:
            return None
        return NdcStatus(
            ndc11=ndc11,
            status=str(status.get("status") or "UNKNOWN").upper(),
            active=str(status.get("active") or "").upper() in ("YES", "Y", "TRUE"),
            rxcui=str(status["rxcui"]) if status.get("rxcui") else None,
            concept_name=status.get("conceptName") or None,
        )
