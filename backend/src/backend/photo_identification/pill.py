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
This is photo identification of a single pill or capsule.
Describe the pill from the photo so it can be looked up later.
Transcribe imprint characters exactly as printed, including case, slashes, and spacing.
Describe color, shape, form, and score marks from the photo only.
likely_identifications are optional hypotheses for a later research step, not a diagnosis. Leave the list empty if the imprint is missing or unreadable.
This is not medical advice and not a confirmed identification.
If the photo is not a pill or capsule, set is_pill to false and leave fields null.
confidence is how readable the imprint and physical features are, from 0 to 1.
"""

PROMPT = "Identify this pill from the photo and extract the imprint and physical features."


class PillIdentificationGuess(BaseModel):
    name: str
    strength: str | None = None
    reason: str
    confidence: float = Field(ge=0, le=1)


class PillPhotoResult(BaseModel):
    is_pill: bool
    imprint_front: str | None = None
    imprint_back: str | None = None
    color: str | None = None
    shape: str | None = None
    form: str | None = None
    score: str | None = None
    additional_markings: str | None = None
    likely_identifications: list[PillIdentificationGuess] = Field(default_factory=list)
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
