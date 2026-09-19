from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pymongo.errors import PyMongoError

from backend.deepgram.router import router as deepgram_router
from backend.drug_facts import router as drug_facts_router
from backend.drug_facts.elastic import close_elastic_store
from backend.photo_identification import router as photo_identification_router
from backend.pill import router as pill_router
from backend.scans import router as scans_router
from backend.scans.store import close_scan_store


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await close_scan_store()
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
app.include_router(deepgram_router)


@app.exception_handler(PyMongoError)
async def mongodb_unavailable(_request, _exc: PyMongoError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": "MongoDB is unreachable"})


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
            "pill": "/drug-facts/pill",
        },
        "pill": "/pill",
        "scans": {
            "create": "/scans",
            "get": "/scans/{scan_id}",
            "bottle": "/scans/{scan_id}/bottle",
            "imprint": "/scans/{scan_id}/imprint",
            "pill": "/scans/{scan_id}/pill",
            "playground_prompt": "/scans/{scan_id}/playground-prompt",
            "reports": "/scans/{scan_id}/reports",
        },
        "deepgram": {
            "session": "/deepgram/session",
        },
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
