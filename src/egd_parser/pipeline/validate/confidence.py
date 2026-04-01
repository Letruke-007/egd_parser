from __future__ import annotations

import re


def _clamp(score: float) -> float:
    return max(0.0, min(1.0, score))


def score_text_confidence(value: str | None) -> float:
    if not value:
        return 0.0
    tokens = value.split()
    if not tokens:
        return 0.0

    score = 0.5
    if len(tokens) >= 3:
        score += 0.2
    if any(token[:1].isupper() for token in tokens):
        score += 0.1
    if any(char.isdigit() for char in value):
        score += 0.1
    if any(token in {"Российская", "Федерация", "Документ"} for token in tokens):
        score -= 0.2

    return _clamp(score)


def score_person_name_confidence(value: str | None) -> float:
    if not value:
        return 0.0

    tokens = [token.strip(" ,.;:()[]{}\"'") for token in value.split()]
    tokens = [token for token in tokens if token]
    if not tokens:
        return 0.0

    score = 0.5
    if len(tokens) >= 2:
        score += 0.15
    if len(tokens) >= 3:
        score += 0.2
    if all(re.search(r"[A-Za-zА-Яа-яЁё]", token) for token in tokens):
        score += 0.1
    if all(not any(char.isdigit() for char in token) for token in tokens):
        score += 0.05
    if any(token in {"Российская", "Федерация", "Документ"} for token in tokens):
        score -= 0.25
    if any(len(token) <= 1 for token in tokens):
        score -= 0.15
    if value.rstrip().endswith("-"):
        score -= 0.1

    return _clamp(score)


def score_enum_confidence(value: str | None) -> float:
    if not value:
        return 0.0
    normalized = value.strip()
    if not normalized:
        return 0.0
    return 0.95


def score_date_confidence(value: str | None) -> float:
    if not value:
        return 0.0
    return 1.0 if len(value) == 10 and value[2:3] == "." and value[5:6] == "." else 0.4


def score_address_confidence(value: str | None) -> float:
    if not value:
        return 0.0
    normalized = value.lower()
    score = 0.5
    if "дом" in normalized:
        score += 0.2
    if "кв." in normalized:
        score += 0.15
    if any(prefix in normalized for prefix in ("ул.", "бульвар", "пр-кт", "пер.", "ш.")):
        score += 0.1
    return _clamp(score)


def score_identity_document_confidence(document: dict | None) -> float:
    if not document:
        return 0.0

    raw = (document.get("raw") or "").strip()
    document_type = document.get("document_type")
    series = document.get("series")
    number = document.get("number")
    issued_by = document.get("issued_by")
    issue_date = document.get("issue_date")

    if not any((raw, document_type, series, number, issued_by, issue_date)):
        return 0.0

    score = 0.25
    if document_type:
        score += 0.15
    if series:
        score += 0.15
    if number:
        score += 0.15
    if issued_by:
        score += 0.15
    if issue_date:
        score += 0.15
    if raw and len(raw.split()) >= 2:
        score += 0.05

    minimal_raws = {
        "паспорт",
        "паспорт рф",
        "справка",
        "свидетельство о рождении",
        "свидетель- ство о ро-",
    }
    if raw.lower() in minimal_raws and not any((series, number, issued_by, issue_date)):
        score -= 0.15

    return _clamp(score)
