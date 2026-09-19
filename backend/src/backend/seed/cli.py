"""peel-seed: pre-download regulatory corpora and index them into Elasticsearch.

Every source is fetched over plain HTTP. Seeding spends no Firecrawl credits
and no LLM tokens.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import Counter
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from itertools import islice
from typing import Any

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from backend.config import get_settings
from backend.knowledge.client import build_client
from backend.knowledge.indices import ensure_indices, mapped_fields, recreate_index
from backend.seed.base import DATA_DIR, SeedContext, Source
from backend.seed.bulk import BulkResult, bulk_index
from backend.seed.http import build_http
from backend.seed.sources import discover

app = typer.Typer(add_completion=False, help=__doc__)
console = Console()

_DRY_RUN_SAMPLE = 2000


def _select(names: str, available: dict[str, type[Source]]) -> list[Source]:
    if names.strip().lower() == "all":
        return [cls() for cls in available.values()]
    wanted = [name.strip() for name in names.split(",") if name.strip()]
    unknown = [name for name in wanted if name not in available]
    if unknown:
        raise typer.BadParameter(f"Unknown sources {unknown}. Available: {', '.join(available)}")
    return [available[name]() for name in wanted]


def _tee_jsonl(docs: Iterable[dict[str, Any]], path: Any) -> Iterator[dict[str, Any]]:
    with path.open("w", encoding="utf-8") as handle:
        for doc in docs:
            handle.write(json.dumps(doc, ensure_ascii=False, default=str) + "\n")
            yield doc


def _dry_run(source: Source, ctx: SeedContext) -> None:
    docs = list(islice(source.parse(ctx), ctx.limit or _DRY_RUN_SAMPLE))
    allowed = mapped_fields(source.index) | {"_id"}
    fill: Counter[str] = Counter()
    unmapped: Counter[str] = Counter()
    for doc in docs:
        fill.update(key for key, value in doc.items() if value not in (None, "", [], {}))
        unmapped.update(set(doc) - allowed)
    if unmapped:
        console.print(f"[red]Unmapped fields (strict mapping would reject): {dict(unmapped)}[/red]")
    missing_id = sum(1 for doc in docs if not doc.get("_id"))
    if missing_id:
        console.print(f"[red]{missing_id} docs have no _id[/red]")
    table = Table(title=f"{source.name}: field fill over {len(docs)} docs")
    table.add_column("field")
    table.add_column("filled", justify="right")
    for key, count in sorted(fill.items(), key=lambda item: -item[1]):
        table.add_row(key, f"{count / max(len(docs), 1):.0%}")
    console.print(table)
    for doc in docs[:3]:
        # Clip long values before printing; slicing the JSON string would make it invalid.
        preview = {
            key: (value[:400] + "…" if isinstance(value, str) and len(value) > 400 else value)
            for key, value in doc.items()
            if key != "raw"
        }
        console.print_json(json.dumps(preview, ensure_ascii=False, default=str))


async def _run(
    selected: list[Source],
    *,
    limit: int | None,
    download_only: bool,
    index_only: bool,
    dry_run: bool,
    recreate: bool,
    refresh_cache: bool,
    concurrency: int,
    bulk_chunk: int | None,
    workers: int,
    options: dict[str, Any],
) -> int:
    settings = get_settings()
    writes = not (download_only or dry_run)
    es = build_client(settings, request_timeout=300) if writes else None
    results: list[tuple[str, BulkResult | None, str]] = []
    failures = 0
    try:
        if es is not None:
            if recreate:
                for index in sorted({source.index for source in selected}):
                    console.print(f"[yellow]Recreating {index}[/yellow]")
                    await recreate_index(es, index)
            created = await ensure_indices(es)
            if created:
                console.print(f"Created indices: {', '.join(created)}")
        async with build_http(concurrency) as http:
            ctx = SeedContext(
                http=http,
                now=datetime.now(UTC),
                limit=limit,
                refresh_cache=refresh_cache,
                concurrency=concurrency,
                options=options,
            )
            for source in selected:
                console.rule(f"{source.name} -> {source.index}")
                try:
                    if not index_only:
                        started = time.monotonic()
                        await source.download(ctx)
                        console.print(f"downloaded in {time.monotonic() - started:.1f}s")
                    if download_only:
                        results.append((source.name, None, "downloaded"))
                        continue
                    if dry_run:
                        _dry_run(source, ctx)
                        results.append((source.name, None, "dry-run"))
                        continue
                    assert es is not None
                    docs = _tee_jsonl(source.parse(ctx), ctx.normalized_path(source.name))
                    with Progress(
                        SpinnerColumn(),
                        TextColumn("{task.description}"),
                        TimeElapsedColumn(),
                        console=console,
                    ) as progress:
                        task = progress.add_task("indexing…")
                        began = time.monotonic()

                        def report(indexed: int, failed: int) -> None:
                            rate = indexed / max(time.monotonic() - began, 0.001)
                            progress.update(
                                task,
                                description=f"indexed {indexed:,} · failed {failed:,} · {rate:,.0f} docs/s",
                            )

                        outcome = await bulk_index(
                            es,
                            source.index,
                            docs,
                            semantic=source.semantic,
                            chunk_size=bulk_chunk,
                            workers=workers,
                            on_progress=report,
                        )
                    status = "ok" if outcome.failed == 0 else "errors"
                    if outcome.failed:
                        failures += 1
                        for error in outcome.errors[:5]:
                            console.print(f"[red]{error}[/red]")
                    results.append((source.name, outcome, status))
                except Exception as exc:  # one bad source must not stop the rest
                    failures += 1
                    console.print(f"[red]{source.name} failed: {exc!r}[/red]")
                    results.append((source.name, None, f"failed: {exc}"[:80]))
    finally:
        if es is not None:
            await es.close()

    table = Table(title="peel-seed summary")
    for column in ("source", "indexed", "failed", "docs/s", "seconds", "status"):
        table.add_column(column)
    for name, outcome, status in results:
        if outcome is None:
            table.add_row(name, "-", "-", "-", "-", status)
        else:
            table.add_row(
                name,
                f"{outcome.indexed:,}",
                f"{outcome.failed:,}",
                f"{outcome.rate:,.0f}",
                f"{outcome.seconds:,.0f}",
                status,
            )
    console.print(table)
    if writes:
        runs = DATA_DIR / "seed-runs.jsonl"
        runs.parent.mkdir(parents=True, exist_ok=True)
        with runs.open("a", encoding="utf-8") as handle:
            for name, outcome, status in results:
                handle.write(
                    json.dumps(
                        {
                            "source": name,
                            "at": datetime.now(UTC).isoformat(),
                            "status": status,
                            "indexed": outcome.indexed if outcome else None,
                            "failed": outcome.failed if outcome else None,
                            "limit": limit,
                        }
                    )
                    + "\n"
                )
    return failures


@app.command()
def seed(
    sources: str = typer.Option("all", help="Comma list of sources, or 'all'."),
    limit: int | None = typer.Option(None, help="Max documents per source (smoke runs)."),
    download_only: bool = typer.Option(False, help="Fetch raw files; do not touch Elasticsearch."),
    index_only: bool = typer.Option(False, help="Index from the existing raw cache; no network fetch."),
    dry_run: bool = typer.Option(False, help="Parse and print samples + field-fill stats; no writes."),
    recreate: bool = typer.Option(False, help="Delete and recreate the target indices first (needs --yes)."),
    yes: bool = typer.Option(False, help="Confirm destructive operations."),
    refresh_cache: bool = typer.Option(False, help="Re-download even if a cached raw file exists."),
    concurrency: int = typer.Option(8, help="HTTP fan-out for page-per-record sources."),
    bulk_chunk: int | None = typer.Option(None, help="Override bulk chunk size."),
    workers: int = typer.Option(4, help="Concurrent bulk requests."),
    hc_detail_limit: int = typer.Option(600, help="Health Canada detail pages to fetch for lot tables."),
    list_sources: bool = typer.Option(False, "--list", help="List available sources and exit."),
) -> None:
    available = discover()
    if list_sources:
        for name, cls in available.items():
            console.print(f"{name:22} -> {cls.index:18} {cls.description}")
        raise typer.Exit()
    if recreate and not yes:
        raise typer.BadParameter("--recreate deletes indices; pass --yes to confirm.")
    if download_only and index_only:
        raise typer.BadParameter("--download-only and --index-only are mutually exclusive.")
    failures = asyncio.run(
        _run(
            _select(sources, available),
            limit=limit,
            download_only=download_only,
            index_only=index_only,
            dry_run=dry_run,
            recreate=recreate,
            refresh_cache=refresh_cache,
            concurrency=concurrency,
            bulk_chunk=bulk_chunk,
            workers=workers,
            options={"hc_detail_limit": hc_detail_limit},
        )
    )
    raise typer.Exit(code=min(failures, 1))
