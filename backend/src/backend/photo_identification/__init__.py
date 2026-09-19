from fastapi import APIRouter

from backend.photo_identification.bottle import router as bottle_router
from backend.photo_identification.pill import router as pill_router

router = APIRouter(
    prefix="/photo-identification",
    tags=["photo-identification"],
)
router.include_router(bottle_router)
router.include_router(pill_router)
