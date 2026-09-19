from backend.scans.models import BottleChannel, Finding, ImprintChannel, PillChannel


def _norm(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.casefold().split())
    return cleaned or None


def _bottle_identity(channel: BottleChannel) -> str | None:
    observation = channel.observation
    facts = channel.research.facts if channel.research else None
    return _norm(
        (facts.generic_name if facts else None)
        or (facts.name if facts else None)
        or observation.generic_name
        or observation.brand_name
    )


def _imprint_identity(channel: ImprintChannel) -> str | None:
    facts = channel.research.facts if channel.research else None
    return _norm(
        (facts.generic_name if facts else None)
        or (facts.name if facts else None)
    )


def _pill_identity(channel: PillChannel) -> str | None:
    facts = channel.research.facts if channel.research else None
    return _norm(
        (facts.generic_name if facts else None)
        or (facts.name if facts else None)
        or channel.hardware.pill_type
    )


def compare_channels(
    bottle: BottleChannel | None,
    imprint: ImprintChannel | None,
    pill: PillChannel | None,
) -> Finding | None:
    if bottle is None and imprint is None and pill is None:
        return None

    identities = [
        identity
        for identity in (
            _bottle_identity(bottle) if bottle else None,
            _imprint_identity(imprint) if imprint else None,
            _pill_identity(pill) if pill else None,
        )
        if identity
    ]
    quality_concern = bool(
        pill
        and (pill.hardware.degraded or pill.hardware.status == "substandard")
    )
    unknown_pill = bool(pill and pill.hardware.status in {"fake", "unknown"})

    if unknown_pill or len(identities) < 2:
        finding: Finding = "inconclusive"
    elif len(set(identities)) == 1:
        finding = "agree"
    else:
        finding = "conflict"

    if quality_concern and finding == "agree":
        return "quality_concern"
    return finding
