from fastapi import APIRouter

from backend.drug_facts.bottle import router as bottle_router
from backend.drug_facts.imprint import router as imprint_router

router = APIRouter(
    prefix="/drug-facts",
    tags=["drug-facts"],
)
router.include_router(bottle_router)
router.include_router(imprint_router)
