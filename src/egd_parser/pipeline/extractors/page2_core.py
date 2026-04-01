import re

from egd_parser.domain.models.ocr import OCRPageResult
from egd_parser.pipeline.extractors.page2_departures import parse_departure_from_words
from egd_parser.pipeline.extractors.page2_names import (
    DATE_RE,
    NAME_STOP_WORDS,
    extract_name_and_birthday_from_words,
    extract_name_tokens_from_words,
    extract_patronymic,
    group_words_into_lines,
    is_patronymic,
    merge_split_name_parts,
)
from egd_parser.utils.text import normalize_whitespace


RESIDENT_START_RE = re.compile(r"([А-ЯЁ][а-яё-]+)\s+([А-ЯЁ][а-яё-]+)\s+(\d{2}\.\d{2}\.\d{4})")


def extract_page2(ocr_results: list[OCRPageResult]) -> dict:
    resident_pages = []
    second_page = next((page for page in ocr_results if page.page_number == 2), None)
    third_page = next((page for page in ocr_results if page.page_number == 3), None)

    if second_page is not None:
        resident_pages.append(second_page)
    if third_page is not None and has_resident_table_continuation(third_page):
        resident_pages.append(third_page)

    if not resident_pages:
        return {
            "registered_persons_constantly": {"count": 0, "persons": []},
            "registered_persons_temporary": {"count": 0, "persons": []},
            "benefits": extract_benefits("\n".join(page.text for page in ocr_results)),
        }

    joined_text = "\n".join(page.text for page in resident_pages)
    full_document_text = "\n".join(page.text for page in ocr_results)

    return {
        "registered_persons_constantly": extract_registered_persons_constantly(resident_pages),
        "registered_persons_temporary": extract_registered_persons_temporary(joined_text),
        "benefits": extract_benefits(joined_text) or extract_benefits(full_document_text),
    }


def has_resident_table_continuation(page: OCRPageResult) -> bool:
    lowered = page.text.lower().replace("ё", "е")
    if "фамилия" not in lowered:
        return False
    return any(marker in lowered for marker in ("паспорт", "дата ро", "отчество"))


def extract_registered_persons_constantly(pages: list[OCRPageResult]) -> dict:
    from egd_parser.pipeline.extractors.page2_table import parse_resident_rows_with_layout

    layout_persons = parse_resident_rows_with_layout(pages)
    fallback_persons = parse_resident_rows(pages)
    persons = choose_best_resident_parse(layout_persons, fallback_persons)
    return {
        "count": len(persons),
        "persons": persons,
    }


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


def extract_benefits(text: str) -> str | None:
    match = re.search(r"Субсидия\s*:?\s*(нет|имеется|есть)", text, re.IGNORECASE)
    if match:
        return match.group(1).lower()
    normalized = text.lower().replace("ё", "е")
    if "наличие мер социальной поддержки" in normalized and "кроме того" in normalized:
        return "нет"
    if "кроме того, на данной площади зарегистрированы по месту пребывания" in normalized:
        return "нет"
    return None


def parse_resident_chunks(flat_text: str) -> list[dict]:
    matches = list(RESIDENT_START_RE.finditer(flat_text))
    persons: list[dict] = []

    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(flat_text)
        chunk = flat_text[start:end]

        surname = match.group(1)
        name = match.group(2)
        birthday_date = match.group(3)
        patronymic = extract_patronymic(chunk, match.end())
        full_name = normalize_whitespace(" ".join(part for part in (surname, name, patronymic) if part))

        passport = extract_passport_from_chunk(chunk)
        persons.append(
            {
                "full_name": full_name,
                "birthday_date": birthday_date,
                "passport": passport,
            }
        )

    return persons


def parse_resident_rows(pages: list[OCRPageResult]) -> list[dict]:
    from egd_parser.pipeline.extractors.page2_table import (
        extract_leading_continuation_departure,
        merge_departure_with_continuation,
        merge_identity_document_with_continuation,
    )

    persons: list[dict] = []
    for page in sorted(pages, key=lambda item: item.page_number):
        if page.page_number > 2 and persons:
            leading_continuation = extract_fallback_leading_continuation_document(page)
            if leading_continuation:
                persons[-1]["passport"] = merge_identity_document_with_continuation(
                    persons[-1].get("passport") or {},
                    leading_continuation,
                )
            leading_departure = extract_leading_continuation_departure(
                page,
                {
                    "page_2": {"top": 1100, "left": 0, "right": 2800},
                    "continuation_page": {"top": 450, "left": 0, "right": 2800},
                    "columns": {
                        "full_name": {"left": 0, "right": 560},
                        "birth_date": {"left": 500, "right": 930},
                        "current_passport": {"left": 1180, "right": 2050},
                        "departure": {"left": 2050, "right": 2800},
                    },
                },
            )
            if leading_departure:
                persons[-1]["departure"] = merge_departure_with_continuation(
                    persons[-1].get("departure") or {},
                    leading_departure,
                )
        persons.extend(parse_resident_rows_on_page(page))
    return persons


def choose_best_resident_parse(primary: list[dict], fallback: list[dict]) -> list[dict]:
    if primary and suspicious_name_count(primary) < suspicious_name_count(fallback):
        return primary
    primary_score = score_resident_parse(primary)
    fallback_score = score_resident_parse(fallback)
    if primary_score >= fallback_score:
        return primary
    return fallback


def score_resident_parse(persons: list[dict]) -> int:
    if not persons:
        return 0

    score = len(persons) * 20
    for person in persons:
        full_name = person.get("full_name") or ""
        birthday_date = person.get("birthday_date") or ""
        passport = person.get("passport") or {}
        score += score_full_name(full_name)
        if DATE_RE.fullmatch(birthday_date):
            score += 5
        if passport.get("raw"):
            score += 4
        if passport.get("number"):
            score += 3
    return score


def score_full_name(full_name: str) -> int:
    if not full_name:
        return -20

    tokens = full_name.split()
    score = 0
    if len(tokens) == 3:
        score += 12
    elif len(tokens) == 2:
        score += 4
    elif len(tokens) > 3:
        score -= 6

    for token in tokens:
        if token in NAME_STOP_WORDS or token in {"Документ", "Федерация", "Российская"}:
            score -= 14
        if not token[:1].isupper():
            score -= 3
        if len(token.strip("-")) < 2:
            score -= 4
        if re.search(r"[A-Za-z]", token):
            score -= 10

    return score


def suspicious_name_count(persons: list[dict]) -> int:
    return sum(1 for person in persons if is_suspicious_full_name(person.get("full_name") or ""))


def is_suspicious_full_name(full_name: str) -> bool:
    if not full_name:
        return True
    tokens = full_name.split()
    if len(tokens) < 3:
        return True
    if len(tokens) > 3:
        return True
    if any(token in NAME_STOP_WORDS for token in tokens):
        return True
    if any(re.search(r"[A-Za-z]", token) for token in tokens):
        return True
    return False


def parse_resident_rows_on_page(page: OCRPageResult) -> list[dict]:
    from egd_parser.pipeline.extractors.page2_table import (
        extend_departure_row_words,
        find_resident_table_end_top,
    )

    words = sorted(page.words, key=lambda item: (item.bbox.top, item.bbox.left))
    temporary_marker = find_resident_table_end_top(words)
    row_anchors = find_resident_row_anchors(words, page.page_number, temporary_marker)

    persons: list[dict] = []
    for index, anchor in enumerate(row_anchors):
        row_top = anchor.bbox.top - 20
        if index + 1 < len(row_anchors):
            row_bottom = row_anchors[index + 1].bbox.top - 20
        else:
            row_bottom = (temporary_marker - 20) if temporary_marker is not None else anchor.bbox.top + 420
        row_words = [word for word in words if row_top <= word.bbox.top < row_bottom]
        departure_context_words = extend_departure_row_words(
            words,
            row_words,
            {
                "full_name": {"left": 0, "right": 560},
                "birth_date": {"left": 500, "right": 930},
                "current_passport": {"left": 1180, "right": 2050},
                "departure": {"left": 2050, "right": 2800},
            },
            row_top,
            row_bottom,
            row_anchors[index + 1].bbox.top if index + 1 < len(row_anchors) else None,
        )
        person = parse_resident_row_words(row_words, page.page_number, departure_context_words)
        if person["full_name"] and person["birthday_date"]:
            persons.append(person)

    return persons


def extract_fallback_leading_continuation_document(page: OCRPageResult) -> dict:
    from egd_parser.pipeline.extractors.page2_table import (
        extract_current_passport_from_words,
        find_resident_table_end_top,
    )

    words = sorted(page.words, key=lambda item: (item.bbox.top, item.bbox.left))
    temporary_marker = find_resident_table_end_top(words)
    row_anchors = find_resident_row_anchors(words, page.page_number, temporary_marker)
    if not row_anchors:
        return {}

    leading_words = [word for word in words if word.bbox.top < row_anchors[0].bbox.top - 20]
    if not leading_words:
        return {}

    continuation_words = [word for word in leading_words if (word.bbox.left + word.bbox.width) > 880]
    if not continuation_words:
        return {}

    ordered_words = sorted(continuation_words, key=lambda item: (item.bbox.top, item.bbox.left))
    raw_text = normalize_whitespace(" ".join(word.text for word in ordered_words))
    return {
        "raw_text": raw_text,
        "parsed": extract_current_passport_from_words(continuation_words),
    }


def find_resident_row_anchors(words: list, page_number: int, temporary_marker: int | None) -> list:
    anchors = []
    min_top = 1100 if page_number == 2 else 450

    for word in words:
        if word.bbox.top < min_top:
            continue
        if temporary_marker is not None and word.bbox.top >= temporary_marker - 20:
            continue
        if word.bbox.left >= 800:
            continue
        if DATE_RE.search(word.text):
            anchors.append(word)

    return sorted(anchors, key=lambda item: item.bbox.top)


def parse_resident_row_words(row_words: list, page_number: int, departure_context_words: list | None = None) -> dict:
    from egd_parser.pipeline.extractors.page2_table import (
        bounding_box_from_words,
        build_deep_departure_cluster_words,
        build_departure_cluster_words,
        departure_completeness,
        extract_current_passport_from_words,
        is_better_departure_candidate,
        should_extend_death_departure,
    )

    name_words = select_fallback_name_words(row_words)
    current_passport_words = [word for word in row_words if 1180 <= word.bbox.left < 2050]
    departure_source_words = departure_context_words or row_words
    departure_words = [word for word in departure_source_words if word.bbox.left >= 2050]
    selected_departure_words = departure_words

    full_name, birthday_date = extract_name_and_birthday_from_words(name_words)
    passport = extract_current_passport_from_words(current_passport_words)
    departure = parse_departure_from_words(departure_words)
    if not departure:
        departure_cluster_words = build_departure_cluster_words(
            departure_source_words,
            {
                "full_name": {"left": 0, "right": 560},
                "birth_date": {"left": 500, "right": 930},
                "current_passport": {"left": 1180, "right": 2050},
                "departure": {"left": 2050, "right": 2800},
            },
        )
        clustered_departure = parse_departure_from_words(departure_cluster_words)
        if departure_completeness(clustered_departure) > departure_completeness(departure):
            departure = clustered_departure
            selected_departure_words = departure_cluster_words
    if should_extend_death_departure(departure):
        deep_departure_words = build_deep_departure_cluster_words(
            departure_source_words,
            row_words,
            {
                "full_name": {"left": 0, "right": 560},
                "birth_date": {"left": 500, "right": 930},
                "current_passport": {"left": 1180, "right": 2050},
                "departure": {"left": 2050, "right": 2800},
            },
            row_bbox_top(row_words),
            row_bbox_bottom(row_words),
            None,
        )
        deep_departure = parse_departure_from_words(deep_departure_words)
        if is_better_departure_candidate(deep_departure, departure):
            departure = deep_departure
            selected_departure_words = deep_departure_words

    return {
        "full_name": full_name,
        "birthday_date": birthday_date,
        "passport": passport,
        "departure": departure,
        "__page_number": page_number,
        "__row_bbox": bounding_box_from_words(row_words),
        "__document_bbox": bounding_box_from_words(current_passport_words),
        "__departure_bbox": bounding_box_from_words(selected_departure_words),
    }


def select_fallback_name_words(row_words: list) -> list:
    candidates = [word for word in row_words if word.bbox.left < 900]
    if not candidates:
        return []

    selected: list = []
    for line_words in group_words_into_lines(candidates):
        ordered_line = sorted(line_words, key=lambda item: item.bbox.left)
        if not ordered_line:
            continue

        base_left = ordered_line[0].bbox.left
        max_left = min(650, base_left + 520)
        last_right = ordered_line[0].bbox.left + ordered_line[0].bbox.width

        if ordered_line[0].bbox.left < max_left:
            selected.append(ordered_line[0])

        for word in ordered_line[1:]:
            gap = word.bbox.left - last_right
            if word.bbox.left >= max_left or gap > 260:
                continue
            selected.append(word)
            last_right = max(last_right, word.bbox.left + word.bbox.width)

    return selected


def normalize_passport_raw(value: str) -> str:
    from egd_parser.pipeline.extractors.page2_passports import normalize_passport_raw as passports_normalize_passport_raw

    return passports_normalize_passport_raw(value)


def normalize_registered_passport(passport: dict) -> dict:
    from egd_parser.pipeline.extractors.page2_passports import normalize_registered_passport as passports_normalize_registered_passport

    return passports_normalize_registered_passport(passport)


def row_bbox_top(words: list) -> int:
    return min((word.bbox.top for word in words), default=0)


def row_bbox_bottom(words: list) -> int:
    return max((word.bbox.top + word.bbox.height for word in words), default=0)


def normalize_registered_issued_by(
    value: str | None,
    number: str | None,
    issue_date: str | None,
) -> str | None:
    from egd_parser.pipeline.extractors.page2_passports import normalize_registered_issued_by as passports_normalize_registered_issued_by

    return passports_normalize_registered_issued_by(value, number, issue_date)


def extract_passport_from_chunk(chunk: str) -> dict:
    if "паспорт рф" not in chunk.lower():
        return {}

    passport_entries = list(
        re.finditer(
            r"Ng\s*(?P<number>\d{6})\s+(?P<series1>\d{2}).{0,20}?(?P<series2>\d{2}),\s*выдан\s+(?P<issued_by>.+?)\s+(?P<issue_date>\d{2}\.\d{2}\.\d{4})",
            chunk,
            re.IGNORECASE,
        )
    )
    if not passport_entries:
        return {}
    entry = passport_entries[0]
    raw = normalize_whitespace(entry.group(0))

    return {
        "raw": raw,
        "document_type": "паспорт",
        "series": f"{entry.group('series1')} {entry.group('series2')}",
        "number": entry.group("number"),
        "issued_by": normalize_whitespace(entry.group("issued_by")),
        "issue_date": entry.group("issue_date"),
    }


def extract_between(text: str, start_marker: str, end_marker: str) -> str:
    normalized = text.replace("\r", "\n")
    start_index = normalized.lower().find(start_marker.lower())
    if start_index == -1:
        return ""
    end_index = normalized.lower().find(end_marker.lower(), start_index)
    if end_index == -1:
        end_index = len(normalized)
    return normalized[start_index:end_index]
