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
This is photo identification of a medication bottle, box, or vial.
Extract visible facts from the container photo only.
Read only text and markings that are actually in the image. Do not invent an NDC, drug name, strength, or directions.
Omit patient name, date of birth, address, phone number, and other personal identifiers.
If the photo is not a medication container, set is_medication_container to false and leave fields null.
confidence is how readable the label is, from 0 to 1.
"""

PROMPT = "Identify this medication from the bottle photo and extract the structured label fields."


class BottlePhotoResult(BaseModel):
    is_medication_container: bool
    brand_name: str | None = None
    generic_name: str | None = None
    strength: str | None = None
    form: str | None = None
    quantity: str | None = None
    ndc: str | None = None
    manufacturer: str | None = None
    pharmacy: str | None = None
    rx_number: str | None = None
    directions: str | None = None
    expiration: str | None = None
    lot_number: str | None = None
    imprint_on_label: str | None = None
    visible_warnings: list[str] = Field(default_factory=list)
    other_label_text: str | None = None
    confidence: float = Field(ge=0, le=1)
    notes: str | None = None


class BottlePhotoIdentification(BaseModel):
    identification_method: Literal["photo"] = "photo"
    target: Literal["bottle"] = "bottle"
    model: str
    result: BottlePhotoResult


router = APIRouter()


@router.post("/bottle", response_model=BottlePhotoIdentification)
async def identify_bottle_photo(
    photo: tuple[bytes, str] = Depends(read_photo),
    vision: VisionClient = Depends(get_vision_client),
) -> BottlePhotoIdentification:
    image_bytes, media_type = photo
    try:
        result = await vision.identify_photo(
            image_bytes, media_type, INSTRUCTIONS, PROMPT, BottlePhotoResult
        )
    except VisionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    return BottlePhotoIdentification(model=VISION_MODEL, result=result)
