from __future__ import annotations

from dataclasses import dataclass

from egd_parser.domain.models.ocr import OCRPageResult


@dataclass(frozen=True)
class LayoutVariant:
    name: str
    confidence: float
    signals: tuple[str, ...]


def detect_page2_variant(pages: list[OCRPageResult]) -> LayoutVariant:
    if not pages:
        return LayoutVariant(name="page2_default", confidence=0.0, signals=())

    joined_text = "\n".join(page.text.lower().replace("ё", "е") for page in pages)
    signals: list[str] = []

    if "кроме того, на данной площади зарегистрированы по месту пребывания" in joined_text:
        signals.append("temporary_registration_block")
    if "наличие мер социальной поддержки" in joined_text or "субсидия" in joined_text:
        signals.append("benefits_block")
    if any(page.page_number >= 3 for page in pages):
        signals.append("continuation_page")

    confidence = min(1.0, 0.35 + 0.2 * len(signals))
    return LayoutVariant(
        name="page2_residents_table",
        confidence=confidence,
        signals=tuple(signals),
    )
