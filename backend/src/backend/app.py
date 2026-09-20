import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.drug_facts import router as drug_facts_router
from backend.drug_facts.elastic import close_elastic_store
from backend.config import get_settings
from backend.deepgram.router import router as deepgram_router
from backend.deepgram.store import close_report_store
from backend.knowledge.client import close_es, get_es
from backend.knowledge.indices import ensure_indices
from backend.knowledge.router import router as knowledge_router
from backend.photo_identification import router as photo_identification_router
from backend.pill import router as pill_router
from backend.research.agent_builder import close_agent_builder
from backend.research.pipeline import cancel_all as cancel_research
from backend.scans.router import router as scans_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Create the strict indices up front: an absent peel-scans would otherwise be
    # auto-created with a dynamic mapping on the first POST /scans. Never fatal —
    # the store answers 503 while the cluster is unreachable.
    try:
        await ensure_indices(get_es(get_settings()))
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not ensure Peel indices at startup: %r", exc)
    yield
    await cancel_research(_app)
    await close_agent_builder()
    await close_report_store()
    await close_es()
    await close_elastic_store()


app = FastAPI(title="Peel", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(photo_identification_router)
app.include_router(drug_facts_router)
app.include_router(pill_router)
app.include_router(scans_router)
app.include_router(knowledge_router)
app.include_router(deepgram_router)


@app.get("/")
def root() -> dict[str, object]:
    return {
        "name": "Peel",
        "docs": "/docs",
        "health": "/health",
        "photo_identification": {
            "bottle": "/photo-identification/bottle",
            "imprint": "/photo-identification/imprint",
        },
        "drug_facts": {
            "bottle": "/drug-facts/bottle",
            "imprint": "/drug-facts/imprint",
        },
        "pill": "/pill",
        "scans": {
            "create": "POST /scans",
            "get": "/scans/{scan_id}",
            "context": "/scans/{scan_id}/context",
            "history": "/scans?device_id=",
            "research": "POST /scans/{scan_id}/research",
        },
        "knowledge": {
            "search": "/knowledge/search?q=",
            "lot": "/knowledge/lot/{lot}",
            "ndc": "/knowledge/ndc/{ndc}",
            "pill": "/knowledge/pill?imprint=",
            "stats": "/knowledge/stats",
        },
        "deepgram": {
            "session": "POST /deepgram/session",
            "reports": "/deepgram/{scan_id}/reports",
        },
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
