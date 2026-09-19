from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.drug_facts import router as drug_facts_router
from backend.drug_facts.elastic import close_elastic_store
from backend.photo_identification import router as photo_identification_router
from backend.pill import router as pill_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
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
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
