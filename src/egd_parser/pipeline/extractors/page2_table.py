from __future__ import annotations

import re

from egd_parser.domain.models.ocr import OCRPageResult
from egd_parser.pipeline.extractors.page2_departures import parse_departure_from_text, parse_departure_from_words
from egd_parser.pipeline.extractors.page2_identity_documents import parse_identity_document_cell
from egd_parser.pipeline.layout.table_grid import infer_residents_table_grid
from egd_parser.pipeline.layout.variant_detector import detect_page2_variant
from egd_parser.pipeline.layout.regions import get_page_regions
from egd_parser.utils.text import normalize_whitespace


DATE_RE = re.compile(r"\d{2}\.\d{2}\.\d{4}")
NAME_STOP_WORDS = {
    "Россия",
    "Российская",
    "Федерация",
    "Узбекистан",
    "Украина",
    "Москва",
    "Ташкент",
    "Анджелес",
    "Штат",
    "Калифорния",
    "Татарская",
    "Нурлат",
    "Ворошиловград",
    "Алтайского",
    "Барнаул",
    "заявитель",
}

def parse_resident_rows_with_layout(pages: list[OCRPageResult]) -> list[dict]:
    layout = get_page_regions("page2").get("residents_table", {})
    if not layout:
        return []

    variant = detect_page2_variant(pages)
    default_persons = parse_resident_rows_with_specific_layout(pages, layout)
    resolved_layout = resolve_residents_table_layout(pages, infer_residents_table_grid(layout, pages))
    adaptive_persons = default_persons
    if variant.confidence > 0 and resolved_layout != layout:
        adaptive_persons = parse_resident_rows_with_specific_layout(pages, resolved_layout)
    return adaptive_persons


def parse_resident_rows_with_specific_layout(pages: list[OCRPageResult], layout: dict) -> list[dict]:
    persons: list[dict] = []
    for page in sorted(pages, key=lambda item: item.page_number):
        page_persons = parse_resident_rows_on_page_with_layout(page, layout)
        if page.page_number > 2 and persons:
            leading_continuation = extract_leading_continuation_document(page, layout)
            if leading_continuation:
                persons[-1]["passport"] = merge_identity_document_with_continuation(
                    persons[-1].get("passport") or {},
                    leading_continuation,
                )
            leading_departure = extract_leading_continuation_departure(page, layout)
            if leading_departure:
                persons[-1]["departure"] = merge_departure_with_continuation(
                    persons[-1].get("departure") or {},
                    leading_departure,
                )
        persons.extend(page_persons)
    return persons


def resolve_residents_table_layout(pages: list[OCRPageResult], layout: dict) -> dict:
    second_page = next((page for page in pages if page.page_number == 2), None)
    if second_page is None:
        return layout

    words = sorted(second_page.words, key=lambda item: (item.bbox.top, item.bbox.left))
    page_layout = layout["page_2"]
    table_words = [
        word
        for word in words
        if word.bbox.top >= page_layout["top"]
        and word.bbox.left >= page_layout["left"]
        and word.bbox.left < page_layout["right"]
    ]
    if not table_words:
        return layout

    adaptive_columns = build_adaptive_columns(table_words, layout["columns"])
    if not adaptive_columns:
        return layout

    return {
        "page_2": dict(layout["page_2"]),
        "continuation_page": dict(layout["continuation_page"]),
        "columns": adaptive_columns,
    }


def build_adaptive_columns(table_words: list, default_columns: dict) -> dict | None:
    birth_probe = {
        "left": max(0, default_columns["birth_date"]["left"] - 160),
        "right": default_columns["birth_date"]["right"] + 160,
    }
    date_anchors = find_date_anchors_in_column(table_words, birth_probe)
    if not date_anchors:
        return None

    sample_anchors = date_anchors[: min(6, len(date_anchors))]
    birth_lefts: list[int] = []
    birth_rights: list[int] = []
    passport_lefts: list[int] = []
    passport_rights: list[int] = []
    name_rights: list[int] = []

    for index, anchor in enumerate(sample_anchors):
        row_top = anchor.bbox.top - 18
        row_bottom = date_anchors[index + 1].bbox.top - 18 if index + 1 < len(date_anchors) else anchor.bbox.top + 220
        row_words = [word for word in table_words if row_top <= word.bbox.top < row_bottom]
        if not row_words:
            continue

        birth_word = find_primary_date_word(row_words, anchor, birth_probe)
        if birth_word:
            birth_lefts.append(birth_word.bbox.left)
            birth_rights.append(birth_word.bbox.left + birth_word.bbox.width)

        passport_words = find_passport_candidate_words(row_words, default_columns["birth_date"]["right"] - 40)
        if passport_words:
            passport_lefts.append(min(word.bbox.left for word in passport_words))
            passport_rights.append(max(word.bbox.left + word.bbox.width for word in passport_words))

        name_words = [
            word
            for word in row_words
            if word.bbox.left < (birth_word.bbox.left if birth_word else default_columns["birth_date"]["left"])
            and not DATE_RE.search(word.text)
        ]
        if name_words:
            name_rights.append(max(word.bbox.left + word.bbox.width for word in name_words))

    columns = {
        "full_name": dict(default_columns["full_name"]),
        "birth_date": dict(default_columns["birth_date"]),
        "current_passport": dict(default_columns["current_passport"]),
        "departure": dict(default_columns.get("departure", {"left": 2050, "right": 2800})),
    }
    if name_rights:
        columns["full_name"]["right"] = clamp_int(int(median(name_rights)) + 35, 420, 760)
    if birth_lefts and birth_rights:
        columns["birth_date"]["left"] = clamp_int(int(median(birth_lefts)) - 35, 420, 760)
        columns["birth_date"]["right"] = clamp_int(int(median(birth_rights)) + 55, 700, 1050)
    if passport_lefts and passport_rights:
        columns["current_passport"]["left"] = clamp_int(int(median(passport_lefts)) - 30, 900, 1320)
        columns["current_passport"]["right"] = clamp_int(int(median(passport_rights)) + 50, 1250, 2050)

    columns["full_name"]["right"] = min(columns["full_name"]["right"], columns["birth_date"]["left"] - 25)
    columns["birth_date"]["right"] = min(columns["birth_date"]["right"], columns["current_passport"]["left"] - 30)
    columns["birth_date"]["left"] = max(columns["birth_date"]["left"], columns["full_name"]["right"] - 80)
    columns["departure"]["left"] = max(columns["departure"]["left"], columns["current_passport"]["right"] + 10)
    return columns


def find_primary_date_word(row_words: list, anchor, birth_probe: dict):
    candidates = []
    for word in row_words:
        if word_center_x(word) < birth_probe["left"] or word_center_x(word) >= birth_probe["right"]:
            continue
        if not DATE_RE.search(word.text):
            continue
        candidates.append(word)
    if not candidates:
        return anchor
    candidates.sort(key=lambda item: (abs(item.bbox.top - anchor.bbox.top), item.bbox.left))
    return candidates[0]


def find_passport_candidate_words(row_words: list, min_left: int) -> list:
    candidates = []
    for word in row_words:
        if (word.bbox.left + word.bbox.width) <= min_left:
            continue
        text = word.text
        lowered = text.lower()
        if (
            "паспорт" in lowered
            or "свидетель" in lowered
            or "выдан" in lowered
            or "мвд" in lowered
            or "овд" in lowered
            or "уфмс" in lowered
            or "№" in text
            or re.search(r"\d{6}", text)
        ):
            candidates.append(word)
    return candidates


def parse_resident_rows_on_page_with_layout(page: OCRPageResult, layout: dict) -> list[dict]:
    words = sorted(page.words, key=lambda item: (item.bbox.top, item.bbox.left))
    temporary_marker = find_resident_table_end_top(words)
    page_layout = layout["page_2"] if page.page_number == 2 else layout["continuation_page"]
    columns = layout["columns"]

    table_words = [
        word
        for word in words
        if word.bbox.top >= page_layout["top"]
        and word.bbox.left >= page_layout["left"]
        and word.bbox.left < page_layout["right"]
        and (temporary_marker is None or word.bbox.top < temporary_marker - 20)
    ]
    if not table_words:
        return []

    row_anchors = find_date_anchors_in_column(table_words, columns["birth_date"])
    if not row_anchors:
        return []

    persons: list[dict] = []
    for index, anchor in enumerate(row_anchors):
        row_top = anchor.bbox.top - 18
        row_bottom = (
            row_anchors[index + 1].bbox.top - 18
            if index + 1 < len(row_anchors)
            else ((temporary_marker - 20) if temporary_marker is not None else anchor.bbox.top + 700)
        )
        next_anchor_top = row_anchors[index + 1].bbox.top if index + 1 < len(row_anchors) else None
        row_words = [word for word in table_words if row_top <= word.bbox.top < row_bottom]
        row_columns = derive_row_column_bounds(row_words, columns, anchor)
        departure_context_words = extend_departure_row_words(
            table_words,
            row_words,
            row_columns,
            row_top,
            row_bottom,
            next_anchor_top,
        )
        name_words = select_name_column_words(row_words, row_columns["full_name"])
        birth_date_words = select_birth_date_words(row_words, row_columns["birth_date"])
        current_passport_words = select_passport_column_words(row_words, row_columns["current_passport"])
        departure_words = select_departure_column_words(departure_context_words, row_columns["departure"])
        current_passport_words = enrich_passport_column_words(row_words, current_passport_words, row_columns)
        selected_document_words = current_passport_words
        selected_departure_words = departure_words

        birthday_date = extract_date_from_words(birth_date_words)
        full_name = extract_name_from_name_column(name_words)
        passport = extract_current_passport_from_words(current_passport_words)
        departure = parse_departure_from_words(departure_words)
        if not departure:
            departure_cluster_words = build_departure_cluster_words(departure_context_words, row_columns)
            clustered_departure = parse_departure_from_words(departure_cluster_words)
            if departure_completeness(clustered_departure) > departure_completeness(departure):
                departure = clustered_departure
                selected_departure_words = departure_cluster_words
        if should_extend_death_departure(departure):
            deep_departure_words = build_deep_departure_cluster_words(
                table_words,
                row_words,
                row_columns,
                row_top,
                row_bottom,
                next_anchor_top,
            )
            deep_departure = parse_departure_from_words(deep_departure_words)
            if is_better_departure_candidate(deep_departure, departure):
                departure = deep_departure
                selected_departure_words = deep_departure_words
        if not is_document_parse_strong(passport):
            clustered_words = build_document_cluster_words(row_words, row_columns)
            clustered_passport = extract_current_passport_from_words(clustered_words)
            if identity_document_completeness(clustered_passport) > identity_document_completeness(passport):
                passport = clustered_passport
                selected_document_words = clustered_words

        if page.page_number > 2 and index == 0 and is_continuation_tail(full_name, name_words):
            continue
        if full_name and birthday_date:
            departure_raw_text = " ".join(word.text for word in sorted(selected_departure_words, key=lambda item: (item.bbox.top, item.bbox.left)))
            persons.append(
                {
                    "full_name": full_name,
                    "birthday_date": birthday_date,
                    "passport": passport,
                    "departure": departure,
                    "__departure_raw_text": departure_raw_text,
                    "__page_number": page.page_number,
                    "__row_bbox": bounding_box_from_words(row_words),
                    "__document_bbox": bounding_box_from_words(selected_document_words),
                    "__departure_bbox": bounding_box_from_words(selected_departure_words),
                }
            )
    return persons


def derive_row_column_bounds(row_words: list, default_columns: dict, anchor) -> dict:
    columns = {
        "full_name": dict(default_columns["full_name"]),
        "birth_date": dict(default_columns["birth_date"]),
        "current_passport": dict(default_columns["current_passport"]),
        "departure": dict(default_columns.get("departure", {"left": 2050, "right": 2800})),
    }
    if not row_words:
        return columns

    birth_word = find_primary_date_word(row_words, anchor, default_columns["birth_date"])
    if birth_word:
        birth_left = birth_word.bbox.left
        birth_right = birth_word.bbox.left + birth_word.bbox.width
        columns["birth_date"]["left"] = clamp_int(birth_left - 18, default_columns["birth_date"]["left"] - 120, default_columns["birth_date"]["left"] + 80)
        columns["birth_date"]["right"] = clamp_int(birth_right + 28, default_columns["birth_date"]["right"] - 120, default_columns["birth_date"]["right"] + 120)
        columns["full_name"]["right"] = min(columns["full_name"]["right"], columns["birth_date"]["left"] - 16)

    passport_start = infer_row_passport_start(row_words, columns["birth_date"]["right"], default_columns["current_passport"]["left"])
    if passport_start is not None:
        columns["current_passport"]["left"] = clamp_int(passport_start - 12, default_columns["current_passport"]["left"] - 180, default_columns["current_passport"]["left"] + 120)
        columns["birth_date"]["right"] = min(columns["birth_date"]["right"], columns["current_passport"]["left"] - 20)

    columns["full_name"]["right"] = max(columns["full_name"]["right"], columns["full_name"]["left"] + 140)
    columns["birth_date"]["left"] = max(columns["birth_date"]["left"], columns["full_name"]["right"] - 40)
    columns["birth_date"]["right"] = max(columns["birth_date"]["right"], columns["birth_date"]["left"] + 90)
    columns["current_passport"]["left"] = max(columns["current_passport"]["left"], columns["birth_date"]["right"] + 20)
    columns["current_passport"]["right"] = min(columns["current_passport"]["right"], columns["departure"]["left"] - 10)
    columns["departure"]["left"] = max(columns["departure"]["left"], columns["current_passport"]["right"] + 10)
    return columns


def infer_row_passport_start(row_words: list, min_left: int, default_left: int) -> int | None:
    passport_words = find_passport_candidate_words(row_words, min_left)
    if passport_words:
        return min(word.bbox.left for word in passport_words)

    right_side_words = [
        word
        for word in row_words
        if word.bbox.left >= min_left and (re.search(r"\d{6}", word.text) or DATE_RE.search(word.text))
    ]
    if right_side_words:
        return min(word.bbox.left for word in right_side_words)

    return default_left


def extract_leading_continuation_document(page: OCRPageResult, layout: dict) -> dict:
    if page.page_number <= 2:
        return {}

    words = sorted(page.words, key=lambda item: (item.bbox.top, item.bbox.left))
    temporary_marker = find_resident_table_end_top(words)
    page_layout = layout["continuation_page"]
    columns = layout["columns"]
    continuation_top = max(0, page_layout["top"] - 220)
    table_words = [
        word
        for word in words
        if word.bbox.top >= continuation_top
        and word.bbox.left >= page_layout["left"]
        and word.bbox.left < page_layout["right"]
        and (temporary_marker is None or word.bbox.top < temporary_marker - 20)
    ]
    if not table_words:
        return {}

    row_anchors = find_date_anchors_in_column(table_words, columns["birth_date"])
    if row_anchors:
        leading_words = [word for word in table_words if word.bbox.top < row_anchors[0].bbox.top - 18]
    else:
        header_bottom = find_continuation_header_bottom(table_words, page_layout["top"])
        leading_words = [word for word in table_words if word.bbox.top >= header_bottom]
    if not leading_words:
        return {}
    continuation_left = max(page_layout["left"], columns["current_passport"]["left"] - 40)
    continuation_words = [
        word
        for word in leading_words
        if (word.bbox.left + word.bbox.width) > continuation_left
    ]
    if not continuation_words:
        return {}
    if not row_anchors:
        continuation_words = select_leftmost_continuation_cluster(continuation_words)
    ordered_words = sorted(continuation_words, key=lambda item: (item.bbox.top, item.bbox.left))
    continuation_raw = normalize_whitespace(" ".join(word.text for word in ordered_words))
    only_dates = DATE_RE.findall(continuation_raw)
    if len(only_dates) == 1:
        parsed = extract_current_passport_from_words(continuation_words)
        if parsed.get("issue_date") == only_dates[0] and not parsed.get("number"):
            return {
                "raw_text": only_dates[0],
                "parsed": {
                    "document_type": "паспорт",
                    "series": None,
                    "number": None,
                    "issued_by": None,
                    "issue_date": only_dates[0],
                    "raw": only_dates[0],
                },
            }
    return {
        "raw_text": continuation_raw,
        "parsed": extract_current_passport_from_words(continuation_words),
    }


def find_continuation_header_bottom(words: list, default_top: int) -> int:
    if not words:
        return default_top
    header_markers = (
        "фамилия",
        "отчество",
        "дата ро",
        "место ро",
        "родствен",
        "серия пас",
        "с какого",
        "дата реги",
        "куда и ко",
        "выдан",
        "москве",
    )
    header_words = [
        word
        for word in words
        if word.bbox.top < default_top
        and any(marker in word.text.lower() for marker in header_markers)
    ]
    if not header_words:
        return default_top
    return max(word.bbox.top for word in header_words) + 24


def select_leftmost_continuation_cluster(words: list) -> list:
    if not words:
        return words
    left_positions = sorted(set(word.bbox.left for word in words))
    split_point = None
    for previous_left, current_left in zip(left_positions, left_positions[1:]):
        if current_left - previous_left >= 160:
            split_point = previous_left + ((current_left - previous_left) // 2)
            break
    if split_point is not None:
        filtered = [word for word in words if word.bbox.left < split_point]
        if filtered:
            return sorted(filtered, key=lambda item: (item.bbox.top, item.bbox.left))

    clusters = cluster_words_by_horizontal_gap(words)
    if not clusters:
        return words
    clusters = sorted(
        clusters,
        key=lambda cluster: min(word.bbox.left for word in cluster),
    )
    return sorted(clusters[0], key=lambda item: (item.bbox.top, item.bbox.left))


def extract_leading_continuation_departure(page: OCRPageResult, layout: dict) -> dict:
    if page.page_number <= 2:
        return {}

    words = sorted(page.words, key=lambda item: (item.bbox.top, item.bbox.left))
    temporary_marker = find_resident_table_end_top(words)
    page_layout = layout["continuation_page"]
    columns = layout["columns"]
    continuation_top = max(0, page_layout["top"] - 220)
    table_words = [
        word
        for word in words
        if word.bbox.top >= continuation_top
        and word.bbox.left >= page_layout["left"]
        and word.bbox.left < page_layout["right"]
        and (temporary_marker is None or word.bbox.top < temporary_marker - 20)
    ]
    if not table_words:
        return {}

    row_anchors = find_date_anchors_in_column(table_words, columns["birth_date"])
    if not row_anchors:
        return {}

    leading_words = [word for word in table_words if word.bbox.top < row_anchors[0].bbox.top - 18]
    if not leading_words:
        return {}

    continuation_words = [
        word
        for word in leading_words
        if (word.bbox.left + word.bbox.width) > columns["departure"]["left"] - 40
    ]
    if not continuation_words:
        return {}
    ordered_words = sorted(continuation_words, key=lambda item: (item.bbox.top, item.bbox.left))
    continuation_raw = normalize_whitespace(" ".join(word.text for word in ordered_words))
    return {
        "raw_text": continuation_raw,
        "parsed": parse_departure_from_words(continuation_words),
    }


def find_resident_table_end_top(words: list) -> int | None:
    stop_markers = ("Кроме того", "Наниматель", "Наличие мер", "Субсидия", "Еще проживает")
    candidates = [word.bbox.top for word in words if any(marker in word.text for marker in stop_markers)]
    return min(candidates) if candidates else None


def find_date_anchors_in_column(words: list, column: dict) -> list:
    anchors = []
    seen_tops: list[int] = []
    for word in sorted(words, key=lambda item: (item.bbox.top, item.bbox.left)):
        if word_center_x(word) < column["left"] or word_center_x(word) >= column["right"]:
            continue
        if not DATE_RE.search(word.text):
            continue
        if any(abs(word.bbox.top - top) <= 12 for top in seen_tops):
            continue
        seen_tops.append(word.bbox.top)
        anchors.append(word)
    return anchors


def select_passport_column_words(words: list, column: dict) -> list:
    return [word for word in words if word.bbox.left < column["right"] and (word.bbox.left + word.bbox.width) > column["left"]]


def enrich_passport_column_words(row_words: list, selected_words: list, columns: dict) -> list:
    if not row_words:
        return selected_words

    if has_document_head(selected_words):
        return selected_words

    expanded_min_left = max(columns["birth_date"]["right"] - 220, columns["birth_date"]["left"] + 40)
    candidate_words = [
        word
        for word in row_words
        if (word.bbox.left + word.bbox.width) > expanded_min_left and word.bbox.left < columns["current_passport"]["right"]
    ]
    if not candidate_words:
        return selected_words

    merged: dict[tuple[int, int, int, str], object] = {}
    for word in selected_words + candidate_words:
        key = (word.bbox.left, word.bbox.top, word.bbox.width, word.text)
        merged[key] = word
    return sorted(merged.values(), key=lambda item: (item.bbox.top, item.bbox.left))


def has_document_head(words: list) -> bool:
    if not words:
        return False
    raw = normalize_whitespace(" ".join(word.text for word in sorted(words, key=lambda item: (item.bbox.top, item.bbox.left))))
    lowered = raw.lower()
    return (
        "паспорт" in lowered
        or "свидетель" in lowered
        or "справка" in lowered
        or bool(re.search(r"№\s*\d{6}", raw))
    )


def build_document_cluster_words(row_words: list, columns: dict) -> list:
    if not row_words:
        return []

    anchor = find_document_anchor_word(row_words, columns)
    if anchor is None:
        return []

    min_left = max(columns["birth_date"]["right"] - 40, anchor.bbox.left - 24)
    cluster = [
        word
        for word in row_words
        if (word.bbox.left + word.bbox.width) > min_left
        and word.bbox.left < columns["departure"]["left"]
    ]
    return sorted(cluster, key=lambda item: (item.bbox.top, item.bbox.left))


def find_document_anchor_word(row_words: list, columns: dict):
    candidates = []
    min_left = columns["birth_date"]["right"] - 80
    for word in row_words:
        if (word.bbox.left + word.bbox.width) <= min_left:
            continue
        score = document_anchor_score(word.text)
        if score <= 0:
            continue
        candidates.append((score, word.bbox.left, word))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates[0][2]


def document_anchor_score(text: str) -> int:
    lowered = text.lower()
    if "паспорт" in lowered:
        return 5
    if "свидетель" in lowered:
        return 5
    if "справка" in lowered:
        return 5
    if re.search(r"№\s*\d{6,8}", text):
        return 4
    if re.search(r"\d{6}", text):
        return 3
    if "выдан" in lowered:
        return 2
    if DATE_RE.search(text):
        return 1
    return 0


def is_document_parse_strong(document: dict) -> bool:
    if not document:
        return False
    return bool(document.get("number") and document.get("issue_date"))


def select_name_column_words(words: list, column: dict) -> list:
    # Layout inference can place the right edge of the name column a bit too
    # close to the birthday column on page 2. Allow a small spillover so the
    # patronymic is not dropped when the OCR word starts slightly to the right.
    right_tolerance = 180
    return [
        word
        for word in words
        if word.bbox.left < column["right"] + right_tolerance
        and (word.bbox.left + word.bbox.width) > column["left"]
    ]


def select_birth_date_words(words: list, column: dict) -> list:
    selected = []
    for word in words:
        if DATE_RE.search(word.text):
            if word.bbox.left < column["right"] and (word.bbox.left + word.bbox.width) > column["left"]:
                selected.append(word)
            continue
        if word_center_x(word) >= column["left"] and word_center_x(word) < column["right"]:
            selected.append(word)
    return selected


def select_departure_column_words(words: list, column: dict) -> list:
    return [
        word
        for word in words
        if word.bbox.left < column["right"] and (word.bbox.left + word.bbox.width) > column["left"]
    ]


def extend_departure_row_words(
    table_words: list,
    row_words: list,
    columns: dict,
    row_top: int,
    row_bottom: int,
    next_anchor_top: int | None,
) -> list:
    if not row_words:
        return row_words
    base_departure_words = select_departure_column_words(row_words, columns["departure"])
    if not looks_like_departure_prefix(base_departure_words):
        return row_words
    extra_bottom = row_bottom + 180
    if next_anchor_top is not None:
        extra_bottom = min(extra_bottom, next_anchor_top + 90)
    min_left = max(columns["current_passport"]["right"] - 20, columns["departure"]["left"] - 120)
    extended = [
        word
        for word in table_words
        if row_top <= word.bbox.top < extra_bottom
        and (word.bbox.left + word.bbox.width) > min_left
    ]
    if not extended:
        return row_words
    return sorted(extended, key=lambda item: (item.bbox.top, item.bbox.left))


def looks_like_departure_prefix(words: list) -> bool:
    if not words:
        return False
    text = normalize_whitespace(" ".join(word.text for word in sorted(words, key=lambda item: (item.bbox.top, item.bbox.left))))
    lowered = text.lower().replace("ё", "е")
    markers = (
        "по смерти",
        "дата смерти",
        "умер",
        "умерла",
        "умер(ла)",
        "формы 6",
        "форма 6",
        "отрывному талону",
        "а/з",
        "а/",
    )
    return any(marker in lowered for marker in markers)


def build_deep_departure_cluster_words(
    table_words: list,
    row_words: list,
    columns: dict,
    row_top: int,
    row_bottom: int,
    next_anchor_top: int | None,
) -> list:
    if not row_words:
        return []
    upper = row_top
    lower = row_bottom + 320
    if next_anchor_top is not None:
        lower = min(lower, next_anchor_top + 260)
    min_left = columns["departure"]["left"] - 30
    deep_words = [
        word
        for word in table_words
        if upper <= word.bbox.top < lower
        and (word.bbox.left + word.bbox.width) > min_left
    ]
    return sorted(deep_words, key=lambda item: (item.bbox.top, item.bbox.left))


def should_extend_death_departure(departure: dict | None) -> bool:
    if not departure or departure.get("reason") != "death":
        return False
    act_number = str(departure.get("act_record_number") or "")
    raw = (departure.get("raw") or "").lower()
    if not act_number:
        return True
    if len(act_number) < 21 and ("а/" in raw or "а/з" in raw or departure.get("act_record_date")):
        return True
    return False


def is_better_departure_candidate(candidate: dict | None, current: dict | None) -> bool:
    if departure_completeness(candidate) > departure_completeness(current):
        return True
    if not candidate:
        return False
    current_number = str((current or {}).get("act_record_number") or "")
    candidate_number = str(candidate.get("act_record_number") or "")
    if len(candidate_number) > len(current_number):
        return True
    if candidate.get("act_record_date") and not (current or {}).get("act_record_date"):
        return True
    if candidate.get("issued_by") and not (current or {}).get("issued_by"):
        return True
    return False


def build_departure_cluster_words(row_words: list, columns: dict) -> list:
    if not row_words:
        return []

    anchor = find_departure_anchor_word(row_words, columns)
    if anchor is not None:
        min_left = max(columns["current_passport"]["right"] - 20, anchor.bbox.left - 30)
        clustered = [
            word
            for word in row_words
            if (word.bbox.left + word.bbox.width) > min_left
        ]
        return sorted(clustered, key=lambda item: (item.bbox.top, item.bbox.left))

    right_limit = max(columns["current_passport"]["right"] + 80, columns["departure"]["left"] - 80)
    right_side_words = [
        word
        for word in row_words
        if (word.bbox.left + word.bbox.width) > right_limit
    ]
    if not right_side_words:
        return []

    return sorted(filter_rightmost_word_cluster(right_side_words), key=lambda item: (item.bbox.top, item.bbox.left))


def find_departure_anchor_word(row_words: list, columns: dict):
    candidates = []
    min_left = columns["current_passport"]["right"] - 40
    for word in row_words:
        if (word.bbox.left + word.bbox.width) <= min_left:
            continue
        score = departure_anchor_score(word.text)
        if score <= 0:
            continue
        candidates.append((score, word.bbox.left, word))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates[0][2]


def departure_anchor_score(text: str) -> int:
    lowered = text.lower().replace("ё", "е")
    if "смерт" in lowered or "умер" in lowered:
        return 6
    if "формы 6" in lowered or "форма 6" in lowered or "отрывному талону" in lowered:
        return 6
    if "а/з" in lowered or "аз" == lowered:
        return 5
    if "оф." in lowered or "загс" in lowered:
        return 4
    if re.search(r"\b\d{21}\b", text):
        return 5
    return 0


def filter_rightmost_word_cluster(words: list) -> list:
    if not words:
        return []
    ordered = sorted(words, key=lambda item: (item.bbox.top, item.bbox.left))
    left_values = sorted(word.bbox.left for word in ordered)
    pivot = left_values[max(0, len(left_values) // 2)]
    return [word for word in ordered if word.bbox.left >= pivot - 60]


def departure_completeness(departure: dict | None) -> int:
    if not departure:
        return 0
    score = 0
    if departure.get("reason"):
        score += 1
    if departure.get("death_date") or departure.get("departure_date"):
        score += 1
    if departure.get("act_record_number"):
        score += 1
    if departure.get("issued_by") or departure.get("destination_address"):
        score += 1
    return score


def extract_date_from_words(words: list) -> str | None:
    for word in sorted(words, key=lambda item: (item.bbox.top, item.bbox.left)):
        match = DATE_RE.search(word.text)
        if match:
            return match.group(0)
    return None


def extract_name_from_name_column(words: list) -> str | None:
    if not words:
        return None
    ordered_words = sorted(filter_name_cluster_words(words), key=lambda item: (item.bbox.top, item.bbox.left))
    tokens: list[str] = []
    for word in ordered_words:
        visible_text = word.text
        date_match = DATE_RE.search(visible_text)
        if date_match:
            visible_text = visible_text[: date_match.start()]
        visible_text = normalize_mixed_script_name_text(visible_text)
        for token in re.findall(r"[А-ЯЁа-яё-]+", visible_text):
            tokens.extend(split_mixed_case_token(token))

    merged = merge_split_name_parts(tokens)
    filtered = []
    for token in merged:
        stripped = token.strip("-")
        if len(stripped) < 2 or stripped in NAME_STOP_WORDS or not stripped[:1].isupper():
            continue
        filtered.append(stripped)

    cleaned = collapse_name_token_noise(filtered)
    if len(cleaned) >= 3:
        return " ".join(cleaned[:3])
    return " ".join(cleaned) if cleaned else None


def filter_name_cluster_words(words: list) -> list:
    if not words:
        return []
    filtered: list = []
    for line_words in group_words_into_lines(words):
        ordered_line = sorted(line_words, key=lambda item: item.bbox.left)
        if not ordered_line:
            continue
        base_left = ordered_line[0].bbox.left
        last_right = ordered_line[0].bbox.left + ordered_line[0].bbox.width
        filtered.append(ordered_line[0])
        for word in ordered_line[1:]:
            center_x = word_center_x(word)
            gap = word.bbox.left - last_right
            if center_x > 860 or word.bbox.left > base_left + 520 or gap > 260:
                continue
            filtered.append(word)
            last_right = max(last_right, word.bbox.left + word.bbox.width)
    return filtered


def group_words_into_lines(words: list, tolerance: int = 18) -> list[list]:
    lines: list[list] = []
    for word in sorted(words, key=lambda item: (item.bbox.top, item.bbox.left)):
        if not lines:
            lines.append([word])
            continue
        current_top = min(item.bbox.top for item in lines[-1])
        if abs(word.bbox.top - current_top) <= tolerance:
            lines[-1].append(word)
        else:
            lines.append([word])
    return lines


def word_center_x(word) -> float:
    return word.bbox.left + (word.bbox.width / 2)


def collapse_name_token_noise(tokens: list[str]) -> list[str]:
    cleaned: list[str] = []
    for token in tokens:
        if token in {"Документ", "Федерация", "Российская", "заявитель"}:
            continue
        if cleaned and token == cleaned[-1]:
            continue
        if cleaned and len(token) <= 3 and not is_patronymic(token):
            continue
        cleaned.append(token)
    return cleaned


def split_mixed_case_token(token: str) -> list[str]:
    if not token:
        return []
    if token.count("-") == 1 and token.endswith("-"):
        return [token]
    parts = re.findall(r"[А-ЯЁ][а-яё-]*", token)
    if len(parts) >= 2 and "".join(parts) == token.replace("-", ""):
        return parts
    return [token]


def normalize_mixed_script_name_text(value: str) -> str:
    from egd_parser.pipeline.extractors.page2_names import normalize_name_text

    return normalize_name_text(value)


def is_continuation_tail(full_name: str | None, name_words: list) -> bool:
    if not name_words or not full_name:
        return True
    tokens = full_name.split()
    if len(tokens) < 2 or any(token in NAME_STOP_WORDS for token in tokens):
        return True
    return tokens[0] in {"Российская", "Федерация"}


def extract_current_passport_from_words(words: list) -> dict:
    if not words:
        return {}
    ordered_words = sorted(words, key=lambda item: (item.bbox.top, item.bbox.left))
    primary_words = select_primary_document_cluster(ordered_words)
    raw = normalize_whitespace(" ".join(word.text for word in primary_words))
    from egd_parser.pipeline.extractors.page2_identity_documents import (
        looks_like_birth_certificate_text,
        looks_like_reference_text,
    )

    document = parse_identity_document_cell(raw)
    if document:
        return document
    if primary_words != ordered_words:
        full_raw = normalize_whitespace(" ".join(word.text for word in ordered_words))
        full_document = parse_identity_document_cell(full_raw)
        if identity_document_completeness(full_document) > identity_document_completeness(document):
            return full_document
    if looks_like_birth_certificate_continuation(raw) or looks_like_birth_certificate_text(raw):
        return parse_identity_document_cell(f"свидетельство о рождении {raw}", preferred_type="свидетельство о рождении")
    if looks_like_reference_continuation(raw) or looks_like_reference_text(raw):
        return parse_identity_document_cell(f"справка {raw}", preferred_type="справка")
    if looks_like_passport_continuation(raw):
        return parse_identity_document_cell(f"паспорт РФ {raw}")
    return {}


def select_primary_document_cluster(words: list) -> list:
    if not words:
        return []
    anchor_split = split_words_by_repeated_document_head(words)
    if anchor_split:
        return anchor_split
    clusters = cluster_words_by_horizontal_gap(words)
    if len(clusters) <= 1:
        return words

    scored_clusters = []
    for cluster in clusters:
        raw = normalize_whitespace(" ".join(word.text for word in sorted(cluster, key=lambda item: (item.bbox.top, item.bbox.left))))
        score = score_document_cluster(raw)
        left = min(word.bbox.left for word in cluster)
        scored_clusters.append((score, left, cluster))

    document_like_clusters = [item for item in scored_clusters if item[0] > 0]
    if not document_like_clusters:
        return words
    document_like_clusters.sort(key=lambda item: (-item[0], item[1]))
    best_score = document_like_clusters[0][0]
    leftmost_best = min(item[1] for item in document_like_clusters if item[0] == best_score)
    for score, left, cluster in sorted(document_like_clusters, key=lambda item: item[1]):
        if score >= max(2, best_score - 1) and left <= leftmost_best + 120:
            return sorted(cluster, key=lambda item: (item.bbox.top, item.bbox.left))
    return sorted(document_like_clusters[0][2], key=lambda item: (item.bbox.top, item.bbox.left))


def split_words_by_repeated_document_head(words: list) -> list:
    ordered = sorted(words, key=lambda item: (item.bbox.top, item.bbox.left))
    anchors = sorted(
        [word for word in ordered if document_anchor_score(word.text) >= 4],
        key=lambda item: (item.bbox.left, item.bbox.top),
    )
    if len(anchors) < 2:
        return []

    first_anchor = anchors[0]
    for anchor in anchors[1:]:
        horizontal_gap = anchor.bbox.left - first_anchor.bbox.left
        if horizontal_gap < 220:
            continue
        cutoff = anchor.bbox.left - 30
        selected = [word for word in ordered if word.bbox.left < cutoff]
        if selected:
            return selected
    return []


def cluster_words_by_horizontal_gap(words: list, gap_threshold: int = 140) -> list[list]:
    sorted_words = sorted(words, key=lambda item: (item.bbox.left, item.bbox.top))
    clusters: list[list] = []
    current_cluster: list = []
    current_right = None
    for word in sorted_words:
        word_left = word.bbox.left
        word_right = word.bbox.left + word.bbox.width
        if not current_cluster:
            current_cluster = [word]
            current_right = word_right
            continue
        if current_right is not None and word_left - current_right > gap_threshold:
            clusters.append(current_cluster)
            current_cluster = [word]
            current_right = word_right
            continue
        current_cluster.append(word)
        current_right = max(current_right or word_right, word_right)
    if current_cluster:
        clusters.append(current_cluster)
    return clusters


def score_document_cluster(raw: str) -> int:
    lowered = raw.lower()
    score = 0
    if "паспорт" in lowered:
        score += 4
    if "свидетель" in lowered:
        score += 4
    if "справка" in lowered:
        score += 4
    if "выдан" in lowered:
        score += 2
    if re.search(r"№\s*\d{6,10}", raw):
        score += 3
    elif re.search(r"\d{6}", raw):
        score += 2
    if DATE_RE.search(raw):
        score += 1
    if any(marker in lowered for marker in ("мвд", "уфмс", "овд", "загс")):
        score += 1
    return score


def merge_identity_document_with_continuation(previous_document: dict, continuation: dict) -> dict:
    previous_document = previous_document or {}
    continuation_raw = normalize_whitespace((continuation or {}).get("raw_text", ""))
    continuation_parsed = dict((continuation or {}).get("parsed") or {})

    if not continuation_raw and not continuation_parsed:
        return previous_document
    if not previous_document:
        return continuation_parsed or previous_document

    previous_raw = normalize_whitespace(previous_document.get("raw", ""))
    merged_candidate = previous_raw
    if continuation_raw:
        merged_candidate = normalize_whitespace(f"{previous_raw} {continuation_raw}").strip()

    preferred_type = previous_document.get("document_type")
    merged_parsed = parse_identity_document_cell(merged_candidate, preferred_type=preferred_type) if merged_candidate else {}
    if preferred_type == "паспорт" and DATE_RE.fullmatch(continuation_raw):
        date_only_candidate = dict(previous_document)
        date_only_candidate["issue_date"] = continuation_raw
        if date_only_candidate.get("number") and date_only_candidate.get("series") and date_only_candidate.get("issued_by"):
            date_only_candidate["raw"] = (
                f"паспорт РФ № {date_only_candidate['number']} {date_only_candidate['series']}, "
                f"выдан {date_only_candidate['issued_by']} {continuation_raw}"
            )
        candidates = [previous_document, continuation_parsed, merged_parsed, date_only_candidate]
        return max(candidates, key=identity_document_merge_score)
    if preferred_type == "паспорт":
        enriched_candidate = enrich_passport_continuation(previous_document, continuation_parsed, merged_parsed)
        candidates = [previous_document, continuation_parsed, merged_parsed, enriched_candidate]
        return max(candidates, key=identity_document_merge_score)
    if preferred_type in {"свидетельство о рождении", "справка"}:
        merged_parsed = enrich_non_passport_continuation(previous_document, merged_parsed)
    candidates = [previous_document]
    if preferred_type:
        if continuation_parsed and continuation_parsed.get("document_type") == preferred_type:
            candidates.append(continuation_parsed)
        if merged_parsed and merged_parsed.get("document_type") == preferred_type:
            candidates.append(merged_parsed)
        if len(candidates) == 1:
            candidates.extend([continuation_parsed, merged_parsed])
    else:
        candidates.extend([continuation_parsed, merged_parsed])
    return max(candidates, key=identity_document_merge_score)


def enrich_passport_continuation(previous_document: dict, continuation_parsed: dict, merged_parsed: dict) -> dict:
    if not previous_document:
        return merged_parsed or continuation_parsed or previous_document

    enriched = dict(previous_document)
    merged_issuer = normalize_whitespace((merged_parsed or {}).get("issued_by") or "")
    continuation_issuer = normalize_whitespace((continuation_parsed or {}).get("issued_by") or "")
    if (continuation_parsed or {}).get("document_type") == "паспорт":
        candidate_issuer = continuation_issuer or merged_issuer
    else:
        candidate_issuer = merged_issuer or continuation_issuer
    if candidate_issuer and len(candidate_issuer) > len(normalize_whitespace(enriched.get("issued_by") or "")):
        enriched["issued_by"] = candidate_issuer

    merged_issue_date = (merged_parsed or {}).get("issue_date")
    continuation_issue_date = (continuation_parsed or {}).get("issue_date")
    if merged_issue_date and DATE_RE.fullmatch(str(merged_issue_date)):
        enriched["issue_date"] = merged_issue_date
    elif continuation_issue_date and DATE_RE.fullmatch(str(continuation_issue_date)):
        enriched["issue_date"] = continuation_issue_date

    if enriched.get("number") and enriched.get("series"):
        raw_parts = [f"паспорт РФ № {enriched['number']} {enriched['series']}"]
        if enriched.get("issued_by"):
            raw_parts.append(f"выдан {enriched['issued_by']}")
        if enriched.get("issue_date"):
            raw_parts.append(str(enriched["issue_date"]))
        enriched["raw"] = normalize_whitespace(" ".join(raw_parts))
    return enriched


def merge_departure_with_continuation(previous_departure: dict, continuation: dict) -> dict:
    previous_departure = previous_departure or {}
    continuation_raw = normalize_whitespace((continuation or {}).get("raw_text", ""))
    continuation_parsed = dict((continuation or {}).get("parsed") or {})

    if not continuation_raw and not continuation_parsed:
        return previous_departure
    if not previous_departure:
        return continuation_parsed or previous_departure

    previous_raw = normalize_whitespace(previous_departure.get("raw", ""))
    merged_raw = normalize_whitespace(f"{previous_raw} {continuation_raw}").strip()
    merged_parsed = parse_departure_from_text(merged_raw) if merged_raw else {}

    candidates = [previous_departure, continuation_parsed, merged_parsed]
    return max(candidates, key=departure_candidate_completeness)


def departure_candidate_completeness(departure: dict | None) -> int:
    if not departure:
        return 0
    score = departure_completeness(departure)
    number = str(departure.get("act_record_number") or "")
    if len(number) >= 21:
        score += 2
    if departure.get("act_record_date"):
        score += 1
    if departure.get("issued_by"):
        score += 1
    return score


def enrich_non_passport_continuation(previous_document: dict, merged_parsed: dict) -> dict:
    if not previous_document or not merged_parsed:
        return merged_parsed
    previous_issued_by = normalize_whitespace(previous_document.get("issued_by") or "")
    merged_issued_by = normalize_whitespace(merged_parsed.get("issued_by") or "")
    from egd_parser.pipeline.extractors.page2_identity_documents import normalize_non_passport_issued_by

    enriched = dict(previous_document)
    if merged_parsed.get("issue_date") and not enriched.get("issue_date"):
        enriched["issue_date"] = merged_parsed.get("issue_date")
    if merged_parsed.get("number") and not enriched.get("number"):
        enriched["number"] = merged_parsed.get("number")
    if merged_parsed.get("series") and birth_series_quality(merged_parsed.get("series")) > birth_series_quality(enriched.get("series")):
        enriched["series"] = merged_parsed.get("series")

    if previous_issued_by and merged_issued_by and looks_like_continuation_issued_by_fragment(merged_issued_by):
        enriched["issued_by"] = normalize_non_passport_issued_by(f"{previous_issued_by} {merged_issued_by}")
    elif merged_issued_by and not previous_issued_by:
        enriched["issued_by"] = normalize_non_passport_issued_by(merged_issued_by)

    if enriched.get("number") and enriched.get("series") and enriched.get("issued_by"):
        enriched["raw"] = (
            f"{enriched.get('document_type')} № {enriched['number']} {enriched['series']}, "
            f"выдан {enriched['issued_by']}"
        )
        if enriched.get("issue_date"):
            enriched["raw"] += f" {enriched['issue_date']}"
    return enriched


def looks_like_continuation_issued_by_fragment(value: str) -> bool:
    lowered = value.lower()
    if lowered.startswith(("скому", "району", "города", "области", "территориаль", "агентства", "загс")):
        return True
    return not value[:1].isupper()


def birth_series_quality(value: str | None) -> int:
    if not value:
        return 0
    normalized = normalize_whitespace(value)
    if re.fullmatch(r"(I|II|III|IV|V|VI|VII|VIII|IX|X)-[А-ЯЁ]{2}", normalized):
        return 3
    if re.fullmatch(r"(I|II|III|IV|V|VI|VII|VIII|IX|X)-[А-ЯЁ]?", normalized):
        return 2
    return 1


def identity_document_completeness(document: dict | None) -> int:
    if not document:
        return 0
    score = 0
    if document.get("document_type"):
        score += 1
    if document.get("series"):
        score += 1
    if document.get("number"):
        score += 1
    if document.get("issued_by"):
        score += 1
    if document.get("issue_date"):
        score += 1
    return score


def identity_document_merge_score(document: dict | None) -> int:
    if not document:
        return 0

    score = identity_document_completeness(document) * 10
    document_type = str(document.get("document_type") or "").lower()
    series = normalize_whitespace(str(document.get("series") or ""))
    number = normalize_whitespace(str(document.get("number") or ""))
    issued_by = normalize_whitespace(str(document.get("issued_by") or ""))
    issue_date = normalize_whitespace(str(document.get("issue_date") or ""))
    raw = normalize_whitespace(str(document.get("raw") or ""))

    if raw:
        score += min(len(raw.split()), 10)

    if document_type == "паспорт":
        if re.fullmatch(r"\d{2}\s\d{2}", series):
            score += 6
        elif series:
            score -= 4
        if re.fullmatch(r"\d{6}", number):
            score += 6
        elif number:
            score -= 4
        if DATE_RE.fullmatch(issue_date):
            score += 6
        elif issue_date:
            score -= 4
        if issued_by:
            score += min(len(issued_by.split()), 8)
            if any(marker in issued_by.upper() for marker in ("ГУ МВД", "МВД", "УФМС", "ОУФМС", "ОВД")):
                score += 4
            if re.search(r"[A-Za-z]", issued_by):
                score -= 8
            if issued_by[:1].islower() or len(issued_by) <= 3:
                score -= 8
            if any(token in issued_by for token in ("p/ne", "p-н", "RAЙ", "гоrо", " HC", "MVD", "Mock", "MOCK")):
                score -= 6

    if document_type == "свидетельство о рождении":
        if re.fullmatch(r"(I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII|XIII|XIV)-[А-ЯЁ]{2}", series):
            score += 5
        elif series:
            score -= 2
        if re.fullmatch(r"\d{6}", number):
            score += 4
        elif number:
            score -= 3
        if issued_by:
            if "ЗАГС" in issued_by.upper():
                score += 4
            if re.search(r"[A-Za-z]", issued_by):
                score -= 6

    return score


def bounding_box_from_words(words: list) -> dict | None:
    if not words:
        return None
    left = min(word.bbox.left for word in words)
    top = min(word.bbox.top for word in words)
    right = max(word.bbox.left + word.bbox.width for word in words)
    bottom = max(word.bbox.top + word.bbox.height for word in words)
    return {
        "left": int(left),
        "top": int(top),
        "width": int(right - left),
        "height": int(bottom - top),
    }


def looks_like_passport_continuation(raw: str) -> bool:
    lowered = raw.lower()
    return bool(
        re.search(r"№\s*\d{6}\s+\d{2}\s+\d{2}", raw)
        and DATE_RE.search(raw)
        and ("выдан" in lowered or "овд" in lowered or "мвд" in lowered or "уфмс" in lowered)
        and "загс" not in lowered
    )


def looks_like_birth_certificate_continuation(raw: str) -> bool:
    lowered = raw.lower()
    return bool(
        re.search(r"№\s*\d{6,8}", raw)
        and DATE_RE.search(raw)
        and ("загс" in lowered or "свидетель" in lowered or "актов гражданского состояния" in lowered)
    )


def looks_like_reference_continuation(raw: str) -> bool:
    lowered = raw.lower()
    return bool(
        re.search(r"№?\s*\d{6}", raw)
        and DATE_RE.search(raw)
        and ("справк" in lowered or "неизвес" in lowered or "конвертац" in lowered)
    )


def normalize_passport_raw(value: str) -> str:
    from egd_parser.pipeline.extractors.page2_identity_documents import normalize_passport_raw as identity_normalize_passport_raw

    return identity_normalize_passport_raw(value)


def is_patronymic(token: str) -> bool:
    from egd_parser.pipeline.extractors.page2_core import is_patronymic as core_is_patronymic

    return core_is_patronymic(token)


def merge_split_name_parts(tokens: list[str]) -> list[str]:
    from egd_parser.pipeline.extractors.page2_core import merge_split_name_parts as core_merge_split_name_parts

    return core_merge_split_name_parts(tokens)


def median(values: list[int]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2


def clamp_int(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, value))
