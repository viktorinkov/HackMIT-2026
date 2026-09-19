from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.photo_identification.vision import (
    VISION_MODEL,
    VisionClient,
    VisionError,
    get_vision_client,
    read_photo,
)

INSTRUCTIONS = """\
This is photo observation of a single pill or capsule, not identification of the drug.
Read only what is visible in this one photo: imprint, color, shape, form, and score marks.
Transcribe imprint characters exactly as printed, including case, slashes, and spacing.
If the photo is not a pill or capsule, set is_pill to false and leave fields null.
confidence is how readable the imprint and physical features are, from 0 to 1.
"""

PROMPT = "Read the pill photo and extract only the imprint and physical features."


class PillPhotoResult(BaseModel):
    is_pill: bool
    imprint: str | None = None
    color: str | None = None
    shape: str | None = None
    form: str | None = None
    score: str | None = None
    additional_markings: str | None = None
    confidence: float = Field(ge=0, le=1)
    notes: str | None = None


class PillPhotoIdentification(BaseModel):
    identification_method: Literal["photo"] = "photo"
    target: Literal["pill"] = "pill"
    model: str
    result: PillPhotoResult


router = APIRouter()


@router.post("/pill", response_model=PillPhotoIdentification)
async def identify_pill_photo(
    photo: tuple[bytes, str] = Depends(read_photo),
    vision: VisionClient = Depends(get_vision_client),
) -> PillPhotoIdentification:
    image_bytes, media_type = photo
    try:
        result = await vision.identify_photo(
            image_bytes, media_type, INSTRUCTIONS, PROMPT, PillPhotoResult
        )
    except VisionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    return PillPhotoIdentification(model=VISION_MODEL, result=result)
