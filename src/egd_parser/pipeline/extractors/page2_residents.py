from egd_parser.domain.models.ocr import OCRPageResult
from egd_parser.pipeline.extractors.page2_core import (
    extract_between,
    parse_resident_chunks,
    parse_resident_rows,
    score_resident_parse,
    suspicious_name_count,
)
from egd_parser.pipeline.extractors.page2_table import parse_resident_rows_with_layout
from egd_parser.pipeline.validate.confidence import (
    score_identity_document_confidence,
    score_person_name_confidence,
)
import re

WITHOUT_REGISTRATION_TEXT_RE = re.compile(r"без\W*регистрац", re.IGNORECASE)


def extract_page2_residents(pages: list[OCRPageResult]) -> dict:
    block, _ = extract_page2_residents_with_trace(pages)
    return block


def extract_page2_residents_with_trace(pages: list[OCRPageResult]) -> tuple[dict, dict]:
    layout_persons = parse_resident_rows_with_layout(pages)
    fallback_persons = parse_resident_rows(pages)
    merged_layout_persons = merge_resident_documents(layout_persons, fallback_persons)

    layout_suspicious = suspicious_name_count(merged_layout_persons)
    fallback_suspicious = suspicious_name_count(fallback_persons)
    layout_score = score_resident_parse(merged_layout_persons)
    fallback_score = score_resident_parse(fallback_persons)

    if merged_layout_persons and layout_suspicious < fallback_suspicious:
        selected_method = "layout"
        persons = merged_layout_persons
    elif layout_score >= fallback_score:
        selected_method = "layout"
        persons = merged_layout_persons
    else:
        selected_method = "fallback"
        persons = fallback_persons

    trace = {
        "selected_method": selected_method,
        "page_numbers": [page.page_number for page in pages],
        "layout_count": len(merged_layout_persons),
        "fallback_count": len(fallback_persons),
        "layout_score": layout_score,
        "fallback_score": fallback_score,
        "persons": [
            {
                "full_name": person.get("full_name"),
                "full_name_confidence": score_person_name_confidence(person.get("full_name")),
                "birthday_date_confidence": 1.0 if person.get("birthday_date") else 0.0,
                "passport_confidence": score_identity_document_confidence(person.get("passport")),
                "source_method": selected_method,
            }
            for person in persons
        ],
    }
    return {
        "count": len(persons),
        "persons": persons,
    }, trace


def merge_resident_documents(layout_persons: list[dict], fallback_persons: list[dict]) -> list[dict]:
    merged = [dict(person) for person in layout_persons]
    for person in merged:
        match = find_matching_fallback_person(person, fallback_persons)
        if not match:
            continue
        if score_document_merge_quality(match.get("passport")) > score_document_merge_quality(person.get("passport")):
            person["passport"] = dict(match.get("passport") or {})
        if not person.get("full_name") or score_person_name_confidence(match.get("full_name")) > score_person_name_confidence(person.get("full_name")):
            person["full_name"] = match.get("full_name")
    return merged


def find_matching_fallback_person(person: dict, fallback_persons: list[dict]) -> dict | None:
    birthday_date = person.get("birthday_date")
    full_name = person.get("full_name") or ""
    if not birthday_date:
        return None

    birthday_matches = [
        candidate
        for candidate in fallback_persons
        if candidate.get("birthday_date") == birthday_date
    ]
    if not birthday_matches:
        return None
    if len(birthday_matches) == 1:
        return birthday_matches[0]

    exact_name = next((candidate for candidate in birthday_matches if canonicalize_name(candidate.get("full_name")) == canonicalize_name(full_name)), None)
    if exact_name:
        return exact_name

    best = None
    best_score = 0
    for candidate in birthday_matches:
        score = resident_name_similarity(full_name, candidate.get("full_name") or "")
        if score > best_score:
            best_score = score
            best = candidate
    return best if best_score >= 1 else None


def resident_name_similarity(left: str, right: str) -> int:
    left_parts = canonicalize_name(left).split()
    right_parts = canonicalize_name(right).split()
    if not left_parts or not right_parts:
        return 0

    score = 0
    if left_parts[0] == right_parts[0]:
        score += 1
    if len(left_parts) >= 2 and len(right_parts) >= 2:
        if left_parts[1].startswith(right_parts[1]) or right_parts[1].startswith(left_parts[1]):
            score += 1
    if len(left_parts) >= 3 and len(right_parts) >= 3:
        if left_parts[2].startswith(right_parts[2]) or right_parts[2].startswith(left_parts[2]):
            score += 1
    return score


def canonicalize_name(value: str | None) -> str:
    if not value:
        return ""
    normalized = value.replace("-", " ")
    return " ".join(part for part in normalized.lower().split() if part)


def score_document_merge_quality(document: dict | None) -> float:
    if not document:
        return 0.0
    score = score_identity_document_confidence(document)
    document_type = (document.get("document_type") or "").lower()
    series = (document.get("series") or "").strip()
    issued_by = (document.get("issued_by") or "").strip()

    if document_type == "свидетельство о рождении":
        if re.fullmatch(r"(I|II|III|IV|V|VI|VII|VIII|IX|X)-[А-ЯЁ]{2}", series):
            score += 0.2
        elif re.fullmatch(r"(I|II|III|IV|V|VI|VII|VIII|IX|X)", series):
            score -= 0.15
        if "ЗАГС" in issued_by.upper() or "АГЕНТСТВА ЗАГС" in issued_by.upper():
            score += 0.15
    if document_type == "справка" and issued_by:
        score += 0.05
    if issued_by and (issued_by[:1].islower() or issued_by.startswith(("скому", "району", "города", "области"))):
        score -= 0.3
    return score


def extract_registered_persons_temporary(text: str) -> dict:
    block = extract_between(
        text,
        "Кроме того, на данной площади зарегистрированы по месту пребывания",
        "другой жилой площади не имеют/имеют",
    )
    flat = " ".join(block.split())
    persons = parse_resident_chunks(flat)
    return {
        "count": len(persons),
        "persons": persons,
    }


def annotate_without_registration(persons_block: dict) -> dict:
    persons = [annotate_person_registration_status(dict(person)) for person in persons_block.get("persons", [])]
    patched = dict(persons_block)
    patched["persons"] = persons
    patched["count"] = len(persons)
    return patched


def annotate_person_registration_status(person: dict) -> dict:
    raw_text = person_departure_raw_text(person)
    if has_without_registration_marker(raw_text):
        person["__registration_status"] = "without_registration"
        person["__registration_status_raw"] = raw_text
    else:
        person["__registration_status"] = "registered"
        person.pop("__registration_status_raw", None)
    return person


def person_has_without_registration(person: dict) -> bool:
    return (person.get("__registration_status") or "").lower() == "without_registration"


def person_departure_raw_text(person: dict) -> str:
    return (
        person.get("__departure_raw_text")
        or (person.get("departure") or {}).get("raw")
        or ""
    )


def has_without_registration_marker(value: str | None) -> bool:
    if not value:
        return False
    normalized = " ".join(str(value).replace("ё", "е").lower().split())
    if WITHOUT_REGISTRATION_TEXT_RE.search(normalized):
        return True
    compact = re.sub(r"[^а-яa-z0-9]+", "", normalized)
    return "безрегистрац" in compact


def filter_out_without_registration(persons: list[dict]) -> list[dict]:
    return [person for person in persons if not person_has_without_registration(person)]


def build_without_registration_trace(persons: list[dict]) -> list[dict]:
    return [
        {
            "full_name": person.get("full_name"),
            "birthday_date": person.get("birthday_date"),
            "registration_status": "without_registration",
            "raw": person.get("__registration_status_raw") or person.get("__departure_raw_text"),
            "source_pages": [person.get("__page_number")] if person.get("__page_number") else [],
        }
        for person in persons
        if person_has_without_registration(person)
    ]
