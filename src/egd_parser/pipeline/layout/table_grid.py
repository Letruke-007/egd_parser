from __future__ import annotations

from copy import deepcopy

from egd_parser.domain.models.ocr import OCRPageResult


def infer_residents_table_grid(
    base_layout: dict,
    pages: list[OCRPageResult],
) -> dict:
    inferred_layout = deepcopy(base_layout)
    if not pages:
        return inferred_layout

    words = []
    for page in pages:
        words.extend(getattr(page, "words", []) or [])

    if not words:
        return inferred_layout

    first_column_right = inferred_layout["columns"]["full_name"]["right"]
    birth_column_left = inferred_layout["columns"]["birth_date"]["left"]

    # Softly adapt the split using detected date tokens rather than hard-coding
    # a single x-coordinate for every EGD variant.
    date_like_lefts = [
        word.bbox.left
        for word in words
        if looks_like_date(getattr(word, "text", ""))
        and getattr(getattr(word, "bbox", None), "left", None) is not None
    ]
    if date_like_lefts:
        inferred_birth_left = int(sum(date_like_lefts[: min(len(date_like_lefts), 12)]) / min(len(date_like_lefts), 12)) - 20
        inferred_layout["columns"]["birth_date"]["left"] = max(0, min(inferred_birth_left, birth_column_left + 120))
        inferred_layout["columns"]["full_name"]["right"] = max(
            first_column_right - 120,
            inferred_layout["columns"]["birth_date"]["left"] + 40,
        )

    return inferred_layout


def looks_like_date(value: str) -> bool:
    compact = value.strip()
    return len(compact) == 10 and compact[2:3] == "." and compact[5:6] == "." and compact[:2].isdigit()
