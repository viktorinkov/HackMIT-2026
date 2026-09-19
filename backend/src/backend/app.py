from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.photo_identification import router as photo_identification_router

app = FastAPI(title="Peel", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(photo_identification_router)


@app.get("/")
def root() -> dict[str, object]:
    return {
        "name": "Peel",
        "docs": "/docs",
        "health": "/health",
        "photo_identification": {
            "bottle": "/photo-identification/bottle",
            "pill": "/photo-identification/pill",
        },
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

