from __future__ import annotations

import re
from datetime import date

from egd_parser.utils.text import normalize_whitespace


DEATH_MARKERS = ("по смерти", "дата смерти", "умер", "умерла", "умер(ла)")
FORM6_MARKERS = ("формы 6", "форма 6", "по отрывному талону")
GENERIC_DEPARTURE_MARKERS = ("выбыл", "выбыла", "выбыт", "снят")
ACT_RECORD_RE = re.compile(r"[аa]/?[з3z]\.?\s*(\d{1,21})", re.IGNORECASE)
LONG_ACT_RECORD_RE = re.compile(r"\b(\d{21})\b")
DATE_RE = re.compile(r"\b(\d{2}\.\d{2}\.\d{2,4}|\d{4}\.\d{2}\.\d{2}|\d{4,8}\.\d{4})\b")
ACT_RECORD_DATE_RE = re.compile(r"\bот\s+(\d{2}\.\d{2}\.\d{2,4})", re.IGNORECASE)
OFFICE_RE = re.compile(r"\bоф\.?\s+(.+)$", re.IGNORECASE)
OFFICIAL_SPLIT_RE = re.compile(r"\bоф\.?\s+", re.IGNORECASE)
FOREIGN_OFFICE_RE = re.compile(
    r"\b(регистратор\s+актов\s+гражданского\s+состояния.+|"
    r"глава\s+канцелярии.+|"
    r"registrar.+|"
    r"county\s+clerk.+)$",
    re.IGNORECASE,
)
ADDRESS_TAIL_RE = re.compile(
    r"(?:[А-ЯЁа-яёA-Za-z0-9.-]+\s+)*(?:ул\.|улица|пр-т|проспект|б-р|бульвар|пер\.|переулок|д\.|дом|к\.|корп\.|кв\.|квартира)\s*.+$",
    re.IGNORECASE,
)
EGR_ZAGS_EFFECTIVE_DATE = date(2018, 11, 4)


def parse_departure_from_words(words: list) -> dict | None:
    if not words:
        return None
    ordered_words = sorted(words, key=lambda item: (item.bbox.top, item.bbox.left))
    raw = normalize_whitespace(" ".join(word.text for word in ordered_words))
    return parse_departure_from_text(raw)


def parse_departure_from_text(raw: str | None) -> dict | None:
    text = normalize_departure_raw(raw or "")
    if not text:
        return None

    lowered = text.lower().replace("ё", "е")
    if any(marker in lowered for marker in DEATH_MARKERS):
        return parse_death_departure(text)
    if any(marker in lowered for marker in FORM6_MARKERS):
        return parse_form6_departure(text)
    if any(marker in lowered for marker in GENERIC_DEPARTURE_MARKERS) or ACT_RECORD_RE.search(text):
        return {
            "status": "departed",
            "reason": "other",
            "raw": text,
        }

    return None


def normalize_departure_raw(value: str) -> str:
    text = normalize_whitespace(value)
    text = re.sub(r"\b[aа]/[3зz]\b", "а/з", text, flags=re.IGNORECASE)
    text = re.sub(r"\b[oо0][тtTТ]\b", "от", text, flags=re.IGNORECASE)
    text = re.sub(r"\b[oо0][фfF]\b\.?", "оф.", text, flags=re.IGNORECASE)
    text = re.sub(r"(\d)\s*[oо0][тtTТ]\b", r"\1 от", text, flags=re.IGNORECASE)
    text = re.sub(r"(\d)\s*[oо0][фfF]\b", r"\1 оф.", text, flags=re.IGNORECASE)
    text = glue_split_act_record_number(text)
    return normalize_whitespace(text)


def glue_split_act_record_number(text: str) -> str:
    def _replace(match: re.Match) -> str:
        prefix = match.group(1)
        digits = "".join(group for group in match.groups()[1:] if group)
        return f"{prefix}{digits}"

    pattern = re.compile(r"(а/з\s+)(\d{4,10})\s+(\d{4,10})(?:\s+(\d{1,3}))?", re.IGNORECASE)
    previous = text
    while True:
        updated = pattern.sub(_replace, previous)
        if updated == previous:
            return updated
        previous = updated


def parse_death_departure(text: str) -> dict:
    death_date = extract_named_date(
        text,
        ("дата смерти", "умер(ла)", "умерла", "умер", "по смерти"),
    ) or extract_first_date(text)
    act_record_number = extract_act_record_number(text)
    act_record_date = normalize_partial_date(find_group(ACT_RECORD_DATE_RE, text, 1))
    issued_by = extract_office(text)
    cleaned_raw = strip_death_address_tail(text)
    cleaned_raw = trim_raw_prefix_before_death_date(cleaned_raw, death_date)
    validation = validate_death_act_record(act_record_number, act_record_date or death_date)

    payload = {
        "status": "departed",
        "reason": "death",
        "raw": cleaned_raw,
        "death_date": death_date,
        "act_record_number": act_record_number,
        "act_record_date": act_record_date,
        "issued_by": issued_by,
        "validation": validation,
    }
    return {key: value for key, value in payload.items() if value not in (None, "", {})}


def parse_form6_departure(text: str) -> dict:
    departure_date = extract_last_date(text)
    destination_address = extract_form6_address(text)
    cleaned_raw = strip_form6_document_noise(text)
    payload = {
        "status": "departed",
        "reason": "form_6_stub",
        "raw": cleaned_raw,
        "departure_date": departure_date,
        "destination_address": destination_address,
    }
    return {key: value for key, value in payload.items() if value not in (None, "", {})}


def extract_form6_address(text: str) -> str | None:
    lowered = text.lower()
    marker_index = lowered.find("формы 6")
    if marker_index == -1:
        marker_index = lowered.find("форма 6")
    if marker_index == -1:
        return None
    tail = normalize_whitespace(text[marker_index:])
    tail = re.sub(r"^.*?форм[аы]\s*6[, ]*", "", tail, flags=re.IGNORECASE)
    tail = re.sub(r",?\s*\d{2}\.?\d{2}\.\d{4}\s*$", "", tail)
    tail = re.sub(r",?\s*\d{8}\.\d{4}\s*$", "", tail)
    tail = re.sub(r"\bсвидетель(?:ство)?\b.*$", "", tail, flags=re.IGNORECASE)
    return tail.strip(" ,") or None


def extract_office(text: str) -> str | None:
    office = find_group(OFFICE_RE, text, 1)
    if not office:
        office = find_group(FOREIGN_OFFICE_RE, text, 1)
    if not office:
        return None
    office = normalize_whitespace(office)
    office = re.sub(r"\s+\d{2}\.\d{2}\.\d{4}\s*$", "", office)
    office = re.sub(r"\s+\d{2}\.\d{2}\.\d{2}\s*$", "", office)
    office = ADDRESS_TAIL_RE.sub("", office).strip(" ,")
    return office.strip(" ,") or None


def strip_death_address_tail(text: str) -> str:
    cleaned = normalize_whitespace(text)
    if "оф." in cleaned.lower():
        parts = OFFICIAL_SPLIT_RE.split(cleaned, maxsplit=1)
        if len(parts) == 2:
            prefix, suffix = parts
            suffix = normalize_whitespace(suffix)
            suffix = re.sub(r"\s+\d{2}\.\d{2}\.\d{4}\s*$", "", suffix)
            suffix = re.sub(r"\s+\d{2}\.\d{2}\.\d{2}\s*$", "", suffix)
            suffix = ADDRESS_TAIL_RE.sub("", suffix).strip(" ,")
            return normalize_whitespace(f"{prefix} оф. {suffix}")
    return ADDRESS_TAIL_RE.sub("", cleaned).strip(" ,")


def trim_raw_prefix_before_death_date(text: str, death_date: str | None) -> str:
    if not death_date:
        return text
    lowered = text.lower().replace("ё", "е")
    for marker in ("дата смерти", "умер(ла)", "умерла", "умер", "по смерти"):
        marker_index = lowered.find(marker)
        if marker_index == -1:
            continue
        date_index = text.find(death_date)
        if date_index != -1 and date_index >= marker_index:
            return normalize_whitespace(text[marker_index:])
    return text


def strip_form6_document_noise(text: str) -> str:
    cleaned = normalize_whitespace(text)
    cleaned = re.sub(r"\bсвидетель(?:ство)?\b.*$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" ,")


def extract_act_record_number(text: str) -> str | None:
    segmented = extract_segmented_act_record_number(text)
    if segmented:
        return segmented
    extended_match = re.search(
        r"[аa]/?[з3z]\.?\s*((?:\d{4,10}\s*){1,3}\d{0,3})\s*(?:от|оф\.?)",
        text,
        re.IGNORECASE,
    )
    if extended_match:
        digits = re.sub(r"\D", "", extended_match.group(1))
        if digits:
            return digits
    value = find_group(ACT_RECORD_RE, text, 1)
    if value:
        return value
    return find_group(LONG_ACT_RECORD_RE, text, 1)


def extract_segmented_act_record_number(text: str) -> str | None:
    match = re.search(r"[аa]/?[з3z]\.?\s+(.+?)(?:\bот\b|\bоф\.?\b|$)", text, re.IGNORECASE)
    if not match:
        return None

    segment = match.group(1)
    tokens = re.split(r"\s+", segment)
    numeric_chunks: list[str] = []
    trailing_digit: str | None = None
    for token in tokens:
        cleaned = token.strip(" ,.;:()[]{}")
        if not cleaned:
            continue
        if re.fullmatch(r"\d{3,21}", cleaned):
            numeric_chunks.append(cleaned)
            continue
        if re.fullmatch(r"\d", cleaned):
            trailing_digit = cleaned
            continue

    if not numeric_chunks:
        return None

    candidate = "".join(numeric_chunks)
    if trailing_digit and len(candidate) in {10, 20}:
        candidate += trailing_digit

    if len(candidate) >= 21:
        return candidate[:21]
    if len(candidate) >= 13:
        return candidate
    return None


def extract_named_date(text: str, markers: tuple[str, ...]) -> str | None:
    lowered = text.lower().replace("ё", "е")
    for marker in markers:
        index = lowered.find(marker)
        if index == -1:
            continue
        fragment = text[index:index + 140]
        for stop_marker in ("а/з", "a/3", "от ", "oт "):
            stop_index = fragment.lower().find(stop_marker)
            if stop_index != -1:
                fragment = fragment[:stop_index]
                break
        date_text = extract_last_date(fragment)
        if date_text:
            return date_text
    return None


def extract_first_date(text: str) -> str | None:
    for match in DATE_RE.finditer(text):
        normalized = normalize_partial_date(match.group(1))
        if normalized:
            return normalized
    return None


def extract_last_date(text: str) -> str | None:
    matches = [normalize_partial_date(match.group(1)) for match in DATE_RE.finditer(text)]
    matches = [item for item in matches if item]
    return matches[-1] if matches else None


def normalize_partial_date(value: str | None) -> str | None:
    if not value:
        return None
    compact = value.strip()
    if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", compact):
        return compact
    if re.fullmatch(r"\d{2}\.\d{2}\.\d{2}", compact):
        year = int(compact[-2:])
        return f"{compact[:6]}20{year:02d}"
    if re.fullmatch(r"\d{8}\.\d{4}", compact):
        return f"{compact[:2]}.{compact[2:4]}.{compact[-4:]}"
    return None


def validate_death_act_record(number: str | None, reference_date_text: str | None) -> dict:
    if not number:
        return {
            "scheme": "unknown",
            "applicable": False,
            "passed": None,
        }

    reference_date = parse_date(reference_date_text)
    if len(number) == 21 and reference_date and reference_date >= EGR_ZAGS_EFFECTIVE_DATE:
        passed = validate_egr_zags_death_record(number)
        return {
            "scheme": "egr_zags_2018",
            "applicable": True,
            "passed": passed,
        }

    return {
        "scheme": "pre_egr_local_record",
        "applicable": False,
        "passed": None,
    }


def validate_egr_zags_death_record(number: str) -> bool:
    if len(number) != 21 or not number.isdigit():
        return False
    if number[1] != "7":
        return False
    return calculate_luhn_check_digit(number[:20]) == int(number[20])


def calculate_luhn_check_digit(base: str) -> int:
    weights = [1, 2] * 10
    total = 0
    for digit, weight in zip(base, weights, strict=True):
        value = int(digit) * weight
        if value > 9:
            value -= 9
        total += value
    return (-total) % 10


def parse_date(value: str | None) -> date | None:
    normalized = normalize_partial_date(value)
    if not normalized:
        return None
    day, month, year = normalized.split(".")
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def find_group(pattern: re.Pattern, text: str, index: int) -> str | None:
    match = pattern.search(text)
    return match.group(index) if match else None
