from fastapi import APIRouter, Depends, HTTPException

from backend.drug_facts.models import DrugFactsError, DrugFactsResearch
from backend.drug_facts.service import ResearchService, get_research_service
from backend.pill import PillHardwareResult

router = APIRouter()


@router.post("/pill", response_model=DrugFactsResearch)
async def research_pill_facts(
    result: PillHardwareResult,
    research: ResearchService = Depends(get_research_service),
) -> DrugFactsResearch:
    try:
        return await research.research_pill(result)
    except DrugFactsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
