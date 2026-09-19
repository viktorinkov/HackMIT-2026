from __future__ import annotations

import base64
from pathlib import Path
from typing import TypeVar

from fastapi import Depends, File, HTTPException, UploadFile, status
from openai import APIError, AsyncOpenAI
from pydantic import BaseModel

from backend.config import Settings, get_settings

T = TypeVar("T", bound=BaseModel)

VISION_MODEL = "gpt-4o"
VISION_DETAIL = "high"

_ALLOWED_MEDIA_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
}
_SUFFIX_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
_MAX_IMAGE_BYTES = 10 * 1024 * 1024


class VisionError(Exception):
    pass


class VisionClient:
    def __init__(self, settings: Settings) -> None:
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)

    async def identify_photo(
        self,
        image_bytes: bytes,
        media_type: str,
        instructions: str,
        prompt: str,
        schema: type[T],
    ) -> T:
        data_url = (
            f"data:{media_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
        )
        try:
            response = await self._client.responses.parse(
                model=VISION_MODEL,
                instructions=instructions,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": prompt},
                            {
                                "type": "input_image",
                                "image_url": data_url,
                                "detail": VISION_DETAIL,
                            },
                        ],
                    }
                ],
                text_format=schema,
            )
        except APIError as exc:
            raise VisionError(exc.message or "OpenAI photo identification failed") from exc

        parsed = response.output_parsed
        if parsed is None:
            raise VisionError("OpenAI returned no structured photo identification")
        return parsed


def get_vision_client(settings: Settings = Depends(get_settings)) -> VisionClient:
    return VisionClient(settings)


def media_type_for(upload: UploadFile) -> str:
    declared = (upload.content_type or "").split(";")[0].strip().lower()
    if declared in _ALLOWED_MEDIA_TYPES:
        return declared
    suffix = Path(upload.filename or "").suffix.lower()
    return _SUFFIX_MEDIA_TYPES.get(suffix, declared)


async def read_photo(upload: UploadFile = File(...)) -> tuple[bytes, str]:
    media_type = media_type_for(upload)
    if media_type not in _ALLOWED_MEDIA_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload a JPEG, PNG, WebP, or GIF photo.",
        )
    image_bytes = await upload.read()
    if not image_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The photo was empty.",
        )
    if len(image_bytes) > _MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Photos must be 10 MB or smaller.",
        )
    return image_bytes, media_type
