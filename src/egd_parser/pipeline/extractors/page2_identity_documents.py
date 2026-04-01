from __future__ import annotations

import re
from datetime import datetime

from egd_parser.domain.reference.okato_regions import detect_okato_series_prefix_hints
from egd_parser.pipeline.extractors.page2_passports import (
    normalize_passport_raw,
    normalize_registered_issued_by,
    normalize_registered_passport,
)
from egd_parser.pipeline.normalize.issuer_grammar import normalize_civil_document_issuer_grammar
from egd_parser.utils.text import normalize_whitespace


DATE_RE = re.compile(r"\d{2}\.\d{2}\.\d{4}")
SERIES_WITH_SPACE_RE = re.compile(r"(?<!\d)(\d{2})\s+(\d{2})(?!\d)")
SERIES_COMPACT_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")
NUMBER_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
PASSPORT_NUMBER_SERIES_RE = re.compile(r"№?\s*(?P<number>\d{6})\s*(?P<series>\d{2}\s?\d{2})(?!\d)")
PASSPORT_SERIES_NUMBER_RE = re.compile(r"(?<!\d)(?P<series>\d{2}\s?\d{2})\s*(?P<number>\d{6})(?!\d)")
PASSPORT_NUMBER_FUZZY_SERIES_RE = re.compile(
    r"№?\s*(?P<number>\d{6})\s*(?P<series1>\d{2})\D{0,3}(?P<series2>\d{2})(?!\d)"
)
PASSPORT_SERIES_FUZZY_NUMBER_RE = re.compile(
    r"(?<!\d)(?P<series1>\d{2})\D{0,3}(?P<series2>\d{2})\s*(?P<number>\d{6})(?!\d)"
)
BIRTH_CERT_SERIES_FIRST_RE = re.compile(
    r"(?P<series>[IVXLCМЮАГБВЕЁЖЗИЙКЛНПРСТУФХЦЧШЩЭЮЯA-Z]{1,5}(?:-[IVXLCМЮАГБВЕЁЖЗИЙКЛНПРСТУФХЦЧШЩЭЮЯA-Z]{1,4})?)"
    r"(?:\s*№)?\s*(?P<number>\d{6,10})(?!\d)",
    re.IGNORECASE,
)
BIRTH_CERT_NUMBER_FIRST_RE = re.compile(
    r"№?\s*(?P<number>\d{6,10})\s*(?P<series>[IVXLCМЮАГБВЕЁЖЗИЙКЛНПРСТУФХЦЧШЩЭЮЯA-Z]{1,5}(?:\s*-\s*[IVXLCМЮАГБВЕЁЖЗИЙКЛНПРСТУФХЦЧШЩЭЮЯA-Z]{1,4})?)",
    re.IGNORECASE,
)
PASSPORT_MARKER_RE = re.compile(r"паспорт", re.IGNORECASE)
CERT_MARKER_RE = re.compile(r"свидетель", re.IGNORECASE)
REFERENCE_MARKER_RE = re.compile(r"справка", re.IGNORECASE)
ZAGS_MARKER_RE = re.compile(r"загс|актов\s+гражданского\s+состояния", re.IGNORECASE)
PASSPORT_ISSUER_MARKER_RE = re.compile(r"мвд|уфмс|оуфмс|овд|увд|гровд|вопросам\s+миграции", re.IGNORECASE)
FOREIGN_DOC_MARKER_RE = re.compile(r"израил|ashkelon|ашкелон|министерств|населения", re.IGNORECASE)
BIRTH_CERT_SERIES_CANONICAL_RE = re.compile(r"^[IVXLCDM]+(?:-[А-ЯЁ]{2})?$")
ROMAN_SERIES_RE = re.compile(r"^[IVXLCDM]+$")

LATIN_TO_CYRILLIC_SERIES = str.maketrans(
    {
        "A": "А",
        "B": "В",
        "C": "С",
        "E": "Е",
        "H": "Н",
        "K": "К",
        "M": "М",
        "O": "О",
        "P": "Р",
        "T": "Т",
        "X": "Х",
        "Y": "У",
    }
)


def parse_identity_document_cell(raw_text: str, preferred_type: str | None = None) -> dict:
    raw = normalize_whitespace(raw_text)
    if not raw:
        return {}

    document_type = preferred_type or detect_identity_document_type(raw)
    if document_type == "паспорт":
        return parse_passport_cell(raw)
    if document_type == "справка":
        return parse_reference_cell(raw)
    if document_type == "свидетельство о рождении":
        return parse_birth_certificate_cell(raw)
    return {}


def normalize_identity_document_by_type(document: dict | None) -> dict:
    payload = dict(document or {})
    if not payload:
        return payload

    document_type = (payload.get("document_type") or "").strip().lower()
    if document_type == "паспорт":
        return normalize_registered_passport(payload)
    if document_type == "справка":
        return normalize_reference_document(payload)
    if document_type == "свидетельство о рождении":
        return normalize_birth_certificate_document(payload)
    return payload


def detect_identity_document_type(raw: str) -> str | None:
    lowered = raw.lower()
    if PASSPORT_MARKER_RE.search(lowered):
        return "паспорт"
    if CERT_MARKER_RE.search(lowered):
        return "свидетельство о рождении"
    if REFERENCE_MARKER_RE.search(lowered):
        return "справка"
    if looks_like_birth_certificate_text(raw):
        return "свидетельство о рождении"
    if looks_like_reference_text(raw):
        return "справка"
    if looks_like_passport_text(raw):
        return "паспорт"
    return None


def looks_like_passport_text(raw: str) -> bool:
    lowered = raw.lower()
    has_date = bool(DATE_RE.search(raw))
    has_number = bool(NUMBER_RE.search(raw))
    has_passport_issuer = bool(PASSPORT_ISSUER_MARKER_RE.search(lowered))
    if ZAGS_MARKER_RE.search(lowered) or FOREIGN_DOC_MARKER_RE.search(lowered):
        return False
    return has_date and has_number and has_passport_issuer


def looks_like_birth_certificate_text(raw: str) -> bool:
    lowered = raw.lower()
    has_date = bool(DATE_RE.search(raw))
    has_number = bool(re.search(r"№?\s*\d{6,8}", raw))
    if CERT_MARKER_RE.search(lowered) or ZAGS_MARKER_RE.search(lowered):
        return True
    if FOREIGN_DOC_MARKER_RE.search(lowered) and has_date and has_number:
        return True
    series, _ = extract_birth_certificate_series_and_number(raw)
    return bool(series and has_date and not PASSPORT_ISSUER_MARKER_RE.search(lowered))


def looks_like_reference_text(raw: str) -> bool:
    lowered = raw.lower()
    has_date = bool(DATE_RE.search(raw))
    has_number = bool(NUMBER_RE.search(raw))
    if REFERENCE_MARKER_RE.search(lowered):
        return True
    return has_date and has_number and ("неизвес" in lowered or "конвертац" in lowered)


def parse_passport_cell(raw: str) -> dict:
    normalized_raw = normalize_passport_raw(raw)
    selected_raw, issue_date = select_best_passport_segment(normalized_raw)
    issued_by = extract_issued_by(selected_raw, issue_date)
    series, number = extract_best_passport_series_and_number(selected_raw, issued_by, issue_date)
    if not is_minimally_valid_identity_segment("паспорт", series, number, issued_by, issue_date):
        fallback_raw = build_wide_segment_around_date(
            normalized_raw,
            issue_date,
            marker_patterns=(r"паспорт", r"справка", r"№\s*\d{6}"),
        )
        if fallback_raw and fallback_raw != selected_raw:
            selected_raw = fallback_raw
            issued_by = extract_issued_by(selected_raw, issue_date)
            series, number = extract_best_passport_series_and_number(selected_raw, issued_by, issue_date)

    passport = {
        "raw": selected_raw or normalized_raw,
        "document_type": "паспорт",
        "series": series,
        "number": number,
        "issued_by": issued_by,
        "issue_date": issue_date,
    }
    return normalize_registered_passport(passport)


def parse_reference_cell(raw: str) -> dict:
    normalized = normalize_whitespace(raw)
    selected_raw, issue_date = select_best_passport_segment(normalized)
    issued_by = extract_issued_by(selected_raw, issue_date)
    series, number = extract_best_passport_series_and_number(selected_raw, issued_by, issue_date)
    if not is_minimally_valid_identity_segment("справка", series, number, issued_by, issue_date):
        fallback_raw = build_wide_segment_around_date(
            normalized,
            issue_date,
            marker_patterns=(r"справка", r"№\s*\d{6}"),
        )
        if fallback_raw and fallback_raw != selected_raw:
            selected_raw = fallback_raw
            issued_by = extract_issued_by(selected_raw, issue_date)
            series, number = extract_best_passport_series_and_number(selected_raw, issued_by, issue_date)
    document = {
        "raw": selected_raw or normalized,
        "document_type": "справка",
        "series": series,
        "number": number,
        "issued_by": issued_by,
        "issue_date": issue_date,
    }
    if number and series and issued_by and issue_date:
        document["raw"] = f"справка № {number} {series}, выдан {issued_by} {issue_date}"
    return normalize_reference_document(document)


def parse_birth_certificate_cell(raw: str) -> dict:
    normalized = normalize_whitespace(raw)
    selected_raw, issue_date = select_best_birth_certificate_segment(normalized)
    series, number = extract_birth_certificate_series_and_number(selected_raw)
    issued_by = extract_issued_by(selected_raw, issue_date)
    if not is_minimally_valid_identity_segment("свидетельство о рождении", series, number, issued_by, issue_date):
        fallback_raw = build_wide_segment_around_date(
            normalized,
            issue_date,
            marker_patterns=(r"свидетель", r"№\s*\d{6,8}"),
        )
        if fallback_raw and fallback_raw != selected_raw:
            selected_raw = fallback_raw
            series, number = extract_birth_certificate_series_and_number(selected_raw)
            issued_by = extract_issued_by(selected_raw, issue_date)
    document = {
        "raw": selected_raw or normalized,
        "document_type": "свидетельство о рождении",
        "series": series,
        "number": number,
        "issued_by": issued_by,
        "issue_date": issue_date,
    }
    if number and series and issued_by and issue_date:
        document["raw"] = f"свидетельство о рождении № {number} {series}, выдан {issued_by} {issue_date}"
    return normalize_birth_certificate_document(document)


def extract_passport_series(raw: str) -> str | None:
    match = SERIES_WITH_SPACE_RE.search(raw)
    if match:
        return f"{match.group(1)} {match.group(2)}"

    compact_match = SERIES_COMPACT_RE.search(raw)
    if compact_match:
        value = compact_match.group(1)
        return f"{value[:2]} {value[2:]}"
    return None


def extract_passport_number(raw: str, series: str | None) -> str | None:
    matches = list(NUMBER_RE.finditer(raw))
    if not matches:
        return None

    if series:
        series_digits = series.replace(" ", "")
        series_match = re.search(rf"(?<!\d){re.escape(series_digits[:2])}\s*{re.escape(series_digits[2:])}(?!\d)", raw)
        if series_match:
            following = [match.group(1) for match in matches if match.start() >= series_match.end()]
            if following:
                return following[0]

    # Fallback: prefer the first six-digit group that is not just the compact series.
    for match in matches:
        if series and match.group(1) == series.replace(" ", ""):
            continue
        return match.group(1)
    return None


def extract_passport_series_and_number(raw: str) -> tuple[str | None, str | None]:
    number_series_matches = list(PASSPORT_NUMBER_SERIES_RE.finditer(raw))
    series_number_matches = list(PASSPORT_SERIES_NUMBER_RE.finditer(raw))
    candidates = number_series_matches + series_number_matches
    if candidates:
        match = candidates[-1]
        series = normalize_series(match.group("series"))
        number = match.group("number")
        return series, number
    series = extract_passport_series(raw)
    number = extract_passport_number(raw, series)
    return series, number


def extract_best_passport_series_and_number(
    raw: str,
    issued_by: str | None,
    issue_date: str | None,
) -> tuple[str | None, str | None]:
    candidates = collect_passport_candidates(raw)
    if not candidates:
        return extract_passport_series_and_number(raw)

    issuer_hints = detect_okato_series_prefix_hints(issued_by)
    if issue_date and issuer_hints:
        synthetic = synthesize_passport_candidates_from_hints(candidates, issuer_hints)
        candidates.extend(synthetic)

    best = max(
        candidates,
        key=lambda item: score_passport_candidate(
            item["series"],
            item["number"],
            item["span_start"],
            item["span_end"],
            raw,
            issued_by,
            issue_date,
        ),
    )
    return best["series"], best["number"]


def collect_passport_candidates(raw: str) -> list[dict]:
    candidates: list[dict] = []
    seen: set[tuple[str, str, int, int]] = set()
    for regex in (PASSPORT_NUMBER_SERIES_RE, PASSPORT_SERIES_NUMBER_RE):
        for match in regex.finditer(raw):
            series = normalize_series(match.group("series"))
            number = match.group("number")
            key = (series or "", number or "", match.start(), match.end())
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "series": series,
                    "number": number,
                    "span_start": match.start(),
                    "span_end": match.end(),
                    "synthetic": False,
                }
            )
    for regex in (PASSPORT_NUMBER_FUZZY_SERIES_RE, PASSPORT_SERIES_FUZZY_NUMBER_RE):
        for match in regex.finditer(raw):
            series = normalize_series(f"{match.group('series1')} {match.group('series2')}")
            number = match.group("number")
            key = (series or "", number or "", match.start(), match.end())
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "series": series,
                    "number": number,
                    "span_start": match.start(),
                    "span_end": match.end(),
                    "synthetic": False,
                }
            )
    return candidates


def synthesize_passport_candidates_from_hints(candidates: list[dict], issuer_hints: dict[str, int]) -> list[dict]:
    synthetic: list[dict] = []
    seen: set[tuple[str, str, int, int]] = set()
    for candidate in candidates:
        series = candidate.get("series")
        number = candidate.get("number")
        if not series or not number:
            continue
        blank_year = series[-2:]
        for prefix in issuer_hints:
            synthetic_series = f"{prefix} {blank_year}"
            if synthetic_series == series:
                continue
            key = (synthetic_series, number, candidate["span_start"], candidate["span_end"])
            if key in seen:
                continue
            seen.add(key)
            synthetic.append(
                {
                    "series": synthetic_series,
                    "number": number,
                    "span_start": candidate["span_start"],
                    "span_end": candidate["span_end"],
                    "synthetic": True,
                }
            )
    return synthetic


def score_passport_candidate(
    series: str | None,
    number: str | None,
    span_start: int,
    span_end: int,
    raw: str,
    issued_by: str | None,
    issue_date: str | None,
) -> int:
    if not series or not number:
        return -100

    score = 0
    if "№" in raw[max(0, span_start - 4):span_end]:
        score += 2
    if PASSPORT_MARKER_RE.search(raw[max(0, span_start - 20):span_start + 20]):
        score += 2

    issuer_hints = detect_okato_series_prefix_hints(issued_by)
    region_prefix = series[:2]
    if issuer_hints:
        if region_prefix in issuer_hints:
            score += issuer_hints[region_prefix]
        else:
            score -= 3

    if issue_date:
        issue_year = int(issue_date[-2:])
        blank_year = int(series[-2:])
        delta = (issue_year - blank_year) % 100
        if 0 <= delta <= 20:
            score += 3
        elif delta <= 30:
            score += 1
        else:
            score -= 2

    return score


def extract_issue_date(raw: str) -> str | None:
    matches = DATE_RE.findall(raw)
    if not matches:
        return None
    dated = [(parse_date_value(value), value) for value in matches]
    dated = [item for item in dated if item[0] is not None]
    if dated:
        dated.sort(key=lambda item: item[0])
        return dated[-1][1]
    return matches[-1]


def extract_reference_series(raw: str) -> str | None:
    return extract_passport_series(raw)


def extract_reference_number(raw: str, series: str | None) -> str | None:
    return extract_passport_number(raw, series)


def extract_birth_certificate_series_and_number(raw: str) -> tuple[str | None, str | None]:
    candidates: list[tuple[str | None, str | None]] = []
    for regex in (BIRTH_CERT_NUMBER_FIRST_RE, BIRTH_CERT_SERIES_FIRST_RE):
        for match in regex.finditer(raw):
            series = normalize_birth_certificate_series(match.group("series"))
            number = match.group("number")
            candidates.append((series, number))

    if not candidates:
        return None, None

    best_series, best_number = max(
        candidates,
        key=lambda item: score_birth_certificate_candidate(item[0], item[1]),
    )
    return best_series, best_number


def score_birth_certificate_candidate(series: str | None, number: str | None) -> int:
    if not series or not number:
        return -100

    score = 0
    if "-" in series:
        score += 5
    if BIRTH_CERT_SERIES_CANONICAL_RE.fullmatch(series):
        score += 4
    score += min(len(series), 8)
    if 6 <= len(number) <= 10:
        score += 2
    return score


def normalize_birth_certificate_series(value: str | None) -> str | None:
    if not value:
        return None
    normalized = normalize_whitespace(value).upper()
    normalized = re.sub(r"\s*-\s*", "-", normalized)
    normalized = normalized.replace(" ", "")
    if "-" not in normalized:
        return normalized

    roman_part, letters_part = normalized.split("-", maxsplit=1)
    roman = normalize_birth_certificate_roman_part(roman_part)
    letters = normalize_birth_certificate_letters_part(letters_part)
    candidate = f"{roman}-{letters}" if roman and letters else normalized
    if BIRTH_CERT_SERIES_CANONICAL_RE.fullmatch(candidate):
        return candidate
    return candidate


def normalize_birth_certificate_roman_part(value: str) -> str:
    roman = value.upper().replace("Х", "X").replace("І", "I").replace("ІI", "II")
    roman = roman.replace("У", "V")
    roman = re.sub(r"[^IVXLCDM]", "", roman)
    if ROMAN_SERIES_RE.fullmatch(roman):
        return roman
    return value.upper()


def normalize_birth_certificate_letters_part(value: str) -> str:
    letters = value.upper().translate(LATIN_TO_CYRILLIC_SERIES)
    letters = re.sub(r"[^А-ЯЁ]", "", letters)
    if len(letters) >= 2:
        return letters[:2]
    return letters


def normalize_series(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\s+", "", value)
    if len(digits) == 4 and digits.isdigit():
        return f"{digits[:2]} {digits[2:]}"
    return normalize_whitespace(value)


def select_best_passport_segment(raw: str) -> tuple[str, str | None]:
    issue_date = extract_issue_date(raw)
    if not issue_date:
        return raw, None

    selected_match = select_date_match(raw, issue_date)
    if selected_match is None:
        return raw, issue_date

    start = find_segment_start(raw, selected_match.start(), (r"паспорт", r"справка"))
    end = find_segment_end(raw, selected_match.end())
    segment = normalize_whitespace(raw[start:end])
    return segment or raw, issue_date


def select_best_birth_certificate_segment(raw: str) -> tuple[str, str | None]:
    issue_date = extract_issue_date(raw)
    if not issue_date:
        return raw, None

    selected_match = select_date_match(raw, issue_date)
    if selected_match is None:
        return raw, issue_date

    start = find_segment_start(raw, selected_match.start(), (r"свидетель",))
    end = find_segment_end(raw, selected_match.end())
    segment = normalize_whitespace(raw[start:end])
    return segment or raw, issue_date


def build_wide_segment_around_date(raw: str, issue_date: str | None, marker_patterns: tuple[str, ...]) -> str:
    if not issue_date:
        return raw
    selected_match = select_date_match(raw, issue_date)
    if selected_match is None:
        return raw
    start = find_segment_start(raw, selected_match.start(), marker_patterns)
    end = find_segment_end(raw, selected_match.end())
    return normalize_whitespace(raw[start:end])


def select_date_match(raw: str, chosen_value: str):
    matches = list(DATE_RE.finditer(raw))
    chosen = [match for match in matches if match.group(0) == chosen_value]
    if not chosen:
        return None
    return chosen[-1]


def find_segment_start(raw: str, before_index: int, marker_patterns: tuple[str, ...]) -> int:
    marker_positions = []
    for pattern in marker_patterns:
        marker_positions.extend(match.start() for match in re.finditer(pattern, raw, re.IGNORECASE) if match.start() < before_index)
    start = max(marker_positions) if marker_positions else 0

    previous_date_ends = [match.end() for match in DATE_RE.finditer(raw) if match.end() <= before_index]
    if previous_date_ends and not marker_positions:
        start = max(start, previous_date_ends[-1])
    return start


def find_segment_end(raw: str, after_index: int) -> int:
    next_marker_positions = []
    for pattern in (r"паспорт", r"свидетель", r"справка"):
        next_marker_positions.extend(match.start() for match in re.finditer(pattern, raw, re.IGNORECASE) if match.start() > after_index)
    if next_marker_positions:
        return min(next_marker_positions)
    return len(raw)


def is_minimally_valid_identity_segment(
    document_type: str,
    series: str | None,
    number: str | None,
    issued_by: str | None,
    issue_date: str | None,
) -> bool:
    if document_type == "паспорт":
        return bool(series and number and issue_date)
    if document_type == "справка":
        return bool(number and issue_date)
    if document_type == "свидетельство о рождении":
        return bool(issue_date and issued_by and (number or series))
    return bool(issue_date or issued_by)


def parse_date_value(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%d.%m.%Y")
    except ValueError:
        return None


def extract_issued_by(raw: str, issue_date: str | None) -> str | None:
    matches = list(re.finditer(r"выдан\s+(.+?)(?=\s+\d{2}\.\d{2}\.\d{4}|$)", raw, re.IGNORECASE))
    if matches:
        issued_by = normalize_whitespace(matches[-1].group(1))
        if "когда выдан" in issued_by.lower():
            issued_by = re.sub(r"^.*когда\s+выдан\s*", "", issued_by, flags=re.IGNORECASE)
            issued_by = normalize_whitespace(issued_by)
        nested_matches = list(re.finditer(r"выдан\s+(.+)", issued_by, re.IGNORECASE))
        if nested_matches:
            issued_by = normalize_whitespace(nested_matches[-1].group(1))
        return normalize_registered_issued_by(issued_by, None, issue_date)

    fallback_issued_by = extract_issued_by_without_marker(raw, issue_date)
    if fallback_issued_by:
        return normalize_registered_issued_by(fallback_issued_by, None, issue_date)
    return None


def extract_issued_by_without_marker(raw: str, issue_date: str | None) -> str | None:
    if not issue_date:
        return None

    before_date = raw.split(issue_date, 1)[0]
    before_date = normalize_whitespace(before_date)
    if not before_date:
        return None

    before_date = re.sub(
        r"^(?:паспорт(?:\s+рф)?|свидетельство\s+о\s+рождении|справка)\s*",
        "",
        before_date,
        flags=re.IGNORECASE,
    )
    before_date = re.sub(r"^№\s*\d{6,10}\s*", "", before_date, flags=re.IGNORECASE)
    before_date = re.sub(r"(?<!\d)\d{2}\s*\d{2}\s*\d{6}(?!\d)", "", before_date)
    before_date = re.sub(r"№?\s*\d{6}\s*\d{2}\s*\d{2}(?!\d)", "", before_date)
    before_date = re.sub(
        r"(?<!\d)(?:[IVXLCМЮАГБВЕЁЖЗИЙКЛНПРСТУФХЦЧШЩЭЮЯA-Z]{1,5}(?:\s*-\s*[IVXLCМЮАГБВЕЁЖЗИЙКЛНПРСТУФХЦЧШЩЭЮЯA-Z]{1,4})?)\s*№?\s*\d{6,10}(?!\d)",
        "",
        before_date,
        flags=re.IGNORECASE,
    )
    before_date = re.sub(
        r"№?\s*\d{6,10}\s*(?:[IVXLCМЮАГБВЕЁЖЗИЙКЛНПРСТУФХЦЧШЩЭЮЯA-Z]{1,5}(?:\s*-\s*[IVXLCМЮАГБВЕЁЖЗИЙКЛНПРСТУФХЦЧШЩЭЮЯA-Z]{1,4})?)(?!\d)",
        "",
        before_date,
        flags=re.IGNORECASE,
    )

    fallback = normalize_whitespace(before_date).strip(" ,;:-")
    if not fallback or len(fallback) < 6:
        return None
    if DATE_RE.search(fallback):
        return None
    return fallback


def normalize_reference_document(document: dict) -> dict:
    payload = dict(document or {})
    payload["document_type"] = "справка"
    payload["raw"] = normalize_whitespace(payload.get("raw") or "")
    payload["series"] = normalize_series(payload.get("series"))
    payload["number"] = normalize_reference_number_text(payload.get("number"))
    payload["issued_by"] = normalize_non_passport_issued_by(payload.get("issued_by"))
    if payload.get("number") and payload.get("series") and payload.get("issued_by"):
        payload["raw"] = f"справка № {payload['number']} {payload['series']}, выдан {payload['issued_by']}"
        if payload.get("issue_date"):
            payload["raw"] += f" {payload['issue_date']}"
    return payload


def normalize_birth_certificate_document(document: dict) -> dict:
    payload = dict(document or {})
    payload["document_type"] = "свидетельство о рождении"
    payload["raw"] = normalize_whitespace(payload.get("raw") or "")
    payload["series"] = normalize_birth_certificate_series(payload.get("series"))
    payload["number"] = normalize_birth_certificate_number_text(payload.get("number"))
    payload["issued_by"] = normalize_non_passport_issued_by(payload.get("issued_by"))
    if payload.get("issued_by") and FOREIGN_DOC_MARKER_RE.search(payload["issued_by"]):
        if payload.get("series") and not BIRTH_CERT_SERIES_CANONICAL_RE.fullmatch(payload["series"]):
            payload["series"] = None
    if payload.get("number") and payload.get("series") and payload.get("issued_by"):
        payload["raw"] = f"свидетельство о рождении № {payload['number']} {payload['series']}, выдан {payload['issued_by']}"
        if payload.get("issue_date"):
            payload["raw"] += f" {payload['issue_date']}"
    elif payload.get("number") and payload.get("issued_by"):
        payload["raw"] = f"свидетельство о рождении № {payload['number']}, выдан {payload['issued_by']}"
        if payload.get("issue_date"):
            payload["raw"] += f" {payload['issue_date']}"
    return payload


def normalize_reference_number_text(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    return digits or normalize_whitespace(value)


def normalize_birth_certificate_number_text(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if 6 <= len(digits) <= 10:
        return digits
    return digits or normalize_whitespace(value)


def normalize_non_passport_issued_by(value: str | None) -> str | None:
    if not value:
        return value
    issued_by = normalize_civil_document_issuer_grammar(value) or value
    return normalize_whitespace(issued_by).strip(" ,;:")
