"""In-process concern reports for the current backend process."""

from __future__ import annotations

from backend.deepgram.models import ConcernReport

_store: "MemoryReportStore | None" = None


class MemoryReportStore:
    def __init__(self) -> None:
        self._reports: dict[str, list[ConcernReport]] = {}

    async def add(self, report: ConcernReport) -> ConcernReport:
        self._reports.setdefault(report.scan_id, []).append(report)
        return report

    async def list(self, scan_id: str) -> list[ConcernReport]:
        return list(reversed(self._reports.get(scan_id, [])))


async def get_report_store() -> MemoryReportStore:
    global _store
    if _store is None:
        _store = MemoryReportStore()
    return _store


async def close_report_store() -> None:
    global _store
    _store = None
