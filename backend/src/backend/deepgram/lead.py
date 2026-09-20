"""What Peel should say first.

`research.headline` is not a recall field. It is one sentence for whatever
verdict the research pipeline chose. Hardware `fake` is not in that verdict.
Do not put those cases in the system prompt or the greeting assembler.
Resolve them here, from a `to_scan_context` dict.

Conflicts and how they are handled
----------------------------------
1. There is no headline-recall.
   A `recall_match` verdict can still arrive with a headline that never
   mentions a recall (the model wrote the wrong sentence). If the verdict
   is `recall_match`, speak a recall sentence even when the headline does
   not.

2. A no-findings headline still contains the word "recall".
   "No matching recall was found…" is absence of evidence, not a recall.
   Only an affirmative recall sentence may be reused as the lead.

3. Hardware `fake` is invisible to the verdict.
   `verdict_from_evidence` does not read hardware, so the headline never
   says fake. If `hardware.reported_status` is `fake`, say that first,
   attributed to the hardware analysis.

4. Fake and recall together.
   Two independent signals. Say fake, then the recall. Do not fold them
   into one proof that the tablet is falsified.

5. Fake and `no_adverse_findings` / `insufficient_evidence`.
   Fake still leads. A "no matching recall" headline must not sound like
   the pill is fine.

6. Fake vs substandard vs degradation.
   `fake` is the device's identity reading. `substandard` and
   `hardware.degradation` are quality. This module only elevates `fake`.
   Do not call a degraded pill fake, or a fake reading degraded.

7. Banned wording.
   Do not say safe, genuine, authentic, or verified. Do not say "not fake".
   Do not tell the user to stop taking a prescribed medicine.

8. Old `scan.finding` values.
   `conflict` / `agree` / `quality_concern` / `inconclusive` are gone.
   Do not reconstruct them here.
"""

from __future__ import annotations

from typing import Any

FAKE_LEAD = "The hardware analysis reported this pill as fake."
RECALL_LEAD = "A recall or safety alert matches this medicine."


def lead_from_context(context: dict[str, Any]) -> str | None:
    """The first finding the greeting and the agent should speak, or None."""
    parts: list[str] = []
    if _reported_fake(context.get("hardware")):
        parts.append(FAKE_LEAD)
    recall = _recall_sentence(context.get("research") or {})
    if recall:
        parts.append(recall)
    if parts:
        return " ".join(parts)
    headline = str((context.get("research") or {}).get("headline") or "").strip()
    return headline or None


def _reported_fake(hardware: dict[str, Any] | None) -> bool:
    return bool(hardware) and hardware.get("reported_status") == "fake"


def _recall_sentence(research: dict[str, Any]) -> str | None:
    if research.get("verdict") != "recall_match":
        return None
    headline = str(research.get("headline") or "").strip()
    if headline and _affirmative_recall(headline):
        return headline
    return RECALL_LEAD


def _affirmative_recall(headline: str) -> bool:
    text = headline.lower()
    if "recall" not in text and "safety alert" not in text:
        return False
    if text.startswith(("no ", "not ", "there was not", "there is not")):
        return False
    if "was not found" in text or "were not found" in text:
        return False
    return True
