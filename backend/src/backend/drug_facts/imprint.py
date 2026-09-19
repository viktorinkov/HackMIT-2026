from fastapi import APIRouter, Depends, HTTPException

from backend.drug_facts.models import DrugFactsError, DrugFactsResearch
from backend.drug_facts.service import ResearchService, get_research_service
from backend.photo_identification.imprint import ImprintPhotoResult

router = APIRouter()


@router.post("/imprint", response_model=DrugFactsResearch)
async def research_imprint_facts(
    result: ImprintPhotoResult,
    research: ResearchService = Depends(get_research_service),
) -> DrugFactsResearch:
    try:
        return await research.research_imprint(result)
    except DrugFactsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
