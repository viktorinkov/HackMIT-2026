from fastapi import APIRouter, Depends, HTTPException

from backend.drug_facts.models import DrugFactsError, DrugFactsResearch
from backend.drug_facts.service import ResearchService, get_research_service
from backend.photo_identification.bottle import BottlePhotoResult

router = APIRouter()


@router.post("/bottle", response_model=DrugFactsResearch)
async def research_bottle_facts(
    result: BottlePhotoResult,
    research: ResearchService = Depends(get_research_service),
) -> DrugFactsResearch:
    try:
        return await research.research_bottle(result)
    except DrugFactsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
