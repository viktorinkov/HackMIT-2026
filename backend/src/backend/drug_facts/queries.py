from backend.photo_identification.bottle import BottlePhotoResult
from backend.photo_identification.imprint import ImprintPhotoResult
from backend.pill import PillHardwareResult


def normalize_query(query: str) -> str:
    return " ".join(query.casefold().split())


def imprint_search_query(result: ImprintPhotoResult) -> str:
    """Turn imprint photo observations into a Firecrawl search string.

    Do not include bottle fields. This lookup must stay independent of the label.

    Trade-offs to decide here:
    - Imprint-only is precise, but codes like "10" or "500" match many drugs.
    - Imprint + color + shape + form disambiguates, but a vision color miss can hide the real hit.
    Return "" if there is nothing searchable.
    """
    parts = [
        result.imprint,
        result.color,
        result.shape,
        result.form,
        result.score,
        result.additional_markings,
    ]
    return " ".join(part.strip() for part in parts if part and part.strip())


def bottle_search_query(result: BottlePhotoResult) -> str:
    """Turn bottle photo observations into a Firecrawl search string.

    Do not include imprint guesses. This lookup must stay independent of the imprint photo.

    Trade-offs to decide here:
    - NDC-first is the DailyMed key and is usually unique.
    - Fall back to brand/generic + strength + manufacturer when NDC is missing or unreadable.
    Return "" if there is nothing searchable.
    """
    if result.ndc and result.ndc.strip():
        return result.ndc.strip()
    parts = [
        result.brand_name,
        result.generic_name,
        result.strength,
        result.form,
        result.manufacturer,
    ]
    return " ".join(part.strip() for part in parts if part and part.strip())


def pill_search_query(result: PillHardwareResult) -> str:
    """Turn hardware pill results into a Firecrawl search string.

    Look up the matched pill type, not the real/fake status and not the spectrum.
    Status is a contents verdict; spectrum is not something public pages can search.
    Do not include bottle or imprint fields. This lookup must stay independent.
    Return "" if the hardware did not match a type.
    """
    if result.pill_type and result.pill_type.strip():
        return result.pill_type.strip()
    return ""
