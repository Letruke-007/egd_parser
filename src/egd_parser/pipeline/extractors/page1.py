import re
from typing import Iterable

from egd_parser.domain.models.ocr import OCRPageResult
from egd_parser.domain.reference.buildings import (
    MANAGED_BUILDINGS,
    find_building_by_address,
    find_buildings_by_street,
)
from egd_parser.domain.reference.moscow import (
    ADMINISTRATIVE_OKRUGS,
    MOSCOW_DISTRICTS,
    SETTLEMENT_TYPES,
)
from egd_parser.pipeline.normalize.issuer_grammar import normalize_passport_issuer_grammar
from egd_parser.pipeline.normalize.rule_registry import (
    get_ownership_document_text_regex_replacements,
    get_ownership_document_text_replacements,
)
from egd_parser.pipeline.extractors.page2_identity_documents import (
    extract_birth_certificate_series_and_number,
    parse_identity_document_cell,
)
from egd_parser.utils.region_ocr import read_crop_text
from egd_parser.utils.text import normalize_whitespace

DATE_RE = re.compile(r"(\d{2}\.\d{2}\.\d{4})")
AREA_RE = re.compile(
    r"Площадь\s+жилого\s+помещения.*?:\s*([0-9]+[,.][0-9]{1,2})",
    re.IGNORECASE,
)
PHONE_RE = re.compile(r"(\+7\s*\(?\d{3}\)?\s*\d[\d\-()]{6,})")
DOC_START_RE = re.compile(
    r"^(ордер|обменный ордер|договор|свидетельство|св-во|выписка|решение|акт|регистрационное удостоверение)",
    re.IGNORECASE,
)
OWNER_RE = re.compile(
    r"^([А-ЯЁ][а-яё-]+(?:\s+[А-ЯЁ][а-яё-]+){2})\s+"
    r"(без\s+опред\.?\s+долей|[0-9]+(?:[,.][0-9]{1,2})?)$"
)


def extract_page1(ocr_results: list[OCRPageResult]) -> dict:
    first_page = next((page for page in ocr_results if page.page_number == 1), None)
    if first_page is None:
        return {"document_type": "egd", "page_1": {}}

    text = first_page.text
    settlement_type = extract_settlement_type(text)
    page_data = {
        "applicant_name": extract_applicant_name(text),
        "document_date": extract_document_date(first_page),
        "administrative_okrug": extract_administrative_okrug(text),
        "district": extract_district(text),
        "passport": extract_passport_data(text),
        "property_address": extract_property_address(first_page),
        "management_company": extract_management_company(text),
        "settlement_type": settlement_type,
        "owners": extract_owners(text, settlement_type),
        "primary_tenant": extract_primary_tenant(text, settlement_type),
        "ownership_documents": extract_ownership_documents(text),
        "total_area_sq_m": extract_total_area(ocr_results),
    }

    return {
        "document_type": "egd",
        "page_1": page_data,
    }


def extract_document_date(page: OCRPageResult) -> str | None:
    for line in build_top_lines(page.words, max_top=700):
        normalized_from_line = normalize_ocr_date_fragment(line)
        if normalized_from_line:
            return normalized_from_line
        match = DATE_RE.search(line)
        if match:
            return match.group(1)
        compact_match = re.search(r"\b[0-9A-ZА-Я]{8}\b", line, re.IGNORECASE)
        if compact_match:
            normalized = normalize_ocr_date_token(compact_match.group(0))
            if normalized:
                return normalized

    top_chunk = page.text[:500]
    normalized_from_chunk = normalize_ocr_date_fragment(top_chunk)
    if normalized_from_chunk:
        return normalized_from_chunk
    match = DATE_RE.search(top_chunk)
    if match:
        return match.group(1)
    compact_match = re.search(r"\b(\d{2})\.(\d{2})(\d{4})\b", top_chunk)
    if compact_match:
        return f"{compact_match.group(1)}.{compact_match.group(2)}.{compact_match.group(3)}"
    return None


def extract_passport_data(text: str) -> dict:
    all_lines = cleaned_lines(text)
    lines = slice_lines_between_markers(
        text,
        start_markers=[["паспортные", "данные"]],
        end_markers=[["сведения", "ранее", "выданном", "паспорте"], ["информация", "причине", "замены", "паспорта"]],
    )
    if not lines:
        return {}

    start_index = find_line_index(all_lines, ["паспортные", "данные"])
    end_index = find_line_index(all_lines, ["сведения", "ранее", "выданном", "паспорте"])
    window = all_lines[start_index + 1 : end_index if end_index != -1 else start_index + 8]
    current_lines = take_current_passport_lines(window)
    block = normalize_for_parsing(" ".join(current_lines))
    raw = normalize_whitespace(" ".join(current_lines))
    generic_document = parse_identity_document_cell(raw)
    document_type = extract_passport_document_type(block)
    series_number_match = re.search(r"(\d{2})\s+(\d{2})\s+(\d{6})", block)
    issue_date = first_date(block)

    issued_by = None
    issued_by_match = re.search(
        r"выдан\s+(.+?)(?=\s+\d{2}\.\d{2}\.\d{4}|$)",
        block,
        re.IGNORECASE,
    )
    if issued_by_match:
        issued_by = normalize_issued_by(issued_by_match.group(1))
        locality_match = re.search(r"[\"'«]?\b([А-ЯЁ][а-яё-]+)\b[\"'»]?$", raw)
        if locality_match and issued_by and canonicalize(issued_by) == canonicalize("ОВД г Москвы"):
            issued_by = f'ОВД "{locality_match.group(1)}" г. Москвы'

    result = {
        "raw": raw,
        "document_type": generic_document.get("document_type") or document_type,
        "series": generic_document.get("series") or (f"{series_number_match.group(1)} {series_number_match.group(2)}" if series_number_match else None),
        "number": generic_document.get("number") or (series_number_match.group(3) if series_number_match else None),
        "issued_by": generic_document.get("issued_by") or issued_by,
        "issue_date": generic_document.get("issue_date") or issue_date,
    }
    if result["document_type"] == "свидетельство о рождении":
        birth_series, birth_number = extract_birth_certificate_series_and_number(raw)
        if birth_series and ("-" in birth_series or len(birth_series) >= 4):
            result["series"] = birth_series
        if birth_number:
            result["number"] = birth_number
    if (
        result["document_type"]
        and result["series"]
        and result["number"]
        and result["issued_by"]
        and result["issue_date"]
        and result["document_type"] == "паспорт РФ"
    ):
        result["raw"] = (
            f"паспорт РФ {result['series']} {result['number']} "
            f"выдан {result['issued_by']} {result['issue_date']}"
        )
    return result if any(value for key, value in result.items() if key != "raw") else {}


def extract_property_address(page: OCRPageResult) -> dict:
    text = page.text
    all_lines = cleaned_lines(text)
    address_anchor = find_line_index(
        all_lines,
        ["по", "адресу"],
    )
    if address_anchor == -1:
        address_anchor = find_line_index(
            all_lines,
            ["жилого", "помещения"],
        )
    end_index = find_line_index(all_lines, ["прежнее", "наименование", "адреса"])
    if address_anchor != -1:
        lines = all_lines[address_anchor + 1 : end_index if end_index != -1 else address_anchor + 10]
    else:
        lines = slice_lines_between_markers(
            text,
            start_markers=[["без", "регистрации", "по", "адресу"], ["ненужное", "зачеркнуть"]],
            end_markers=[["прежнее", "наименование", "адреса"]],
        )
    if not lines:
        return {}
    lines = trim_to_relevant_address_lines(lines)
    street_line = next((line for line in lines if is_property_street_line(line)), None)
    if not street_line:
        return {}
    parsed = normalize_for_parsing(" ".join(lines))
    house = search_token(parsed, r"дом\s*(?:№|ng|no)?\s*(?P<value>[\w/-]+)")
    building = search_token(parsed, r"кор(?:п|п\.|п:|:)?\s*(?P<value>[\w/-]+)")
    structure = search_token(parsed, r"строение\s*(?P<value>[\w/-]+)")
    apartment = search_token(parsed, r"кв\.?\s*(?P<value>\d+)")
    leading_number = find_address_leading_number(lines)
    if apartment is None and leading_number:
        apartment = leading_number
    if apartment is None:
        apartment = find_standalone_number(lines, exclude={house} if house else None)
    if (house is None or house == "N") and apartment != leading_number and page.image_path and page.words:
        house = extract_house_from_region(page.words, page.image_path) or house
    if house == "N":
        house = None

    street = normalize_street(street_line)
    house, building = resolve_property_address_by_reference(street, house, building)
    block = "\n".join(lines)

    return {
        "raw": normalize_whitespace(block),
        "full": compose_address(street, house, building, structure, apartment),
        "street": street,
        "house": house,
        "building": building,
        "structure": structure,
        "apartment": apartment,
    }


def resolve_property_address_by_reference(
    street: str | None,
    house: str | None,
    building: str | None,
) -> tuple[str | None, str | None]:
    if not street:
        return house, building

    exact_match = find_building_by_address(street, house, building)
    if exact_match:
        return exact_match.house, exact_match.building

    candidates = find_buildings_by_street(street)
    if not candidates:
        return house, building

    if house and not building:
        by_house = [candidate for candidate in candidates if candidate.house == house]
        if len(by_house) == 1:
            return by_house[0].house, by_house[0].building

    if building and not house:
        by_building = [candidate for candidate in candidates if (candidate.building or "") == building]
        if len(by_building) == 1:
            return by_building[0].house, by_building[0].building

    if not house and not building and len(candidates) == 1:
        return candidates[0].house, candidates[0].building

    return house, building


def extract_management_company(text: str) -> dict:
    lines = slice_lines_between_markers(
        text,
        start_markers=[["организация", "функции", "управления", "домом"]],
        end_markers=[["вид", "заселения"]],
    )
    if not lines:
        return {}
    lines = [line.strip(" :") for line in lines if line.strip(" :")]
    if not lines:
        return {}

    name = normalize_company_name(lines[0])
    tail = " ".join(sorted(lines[1:], key=management_line_priority)) if len(lines) > 1 else ""
    phone_match = PHONE_RE.search(tail)
    phone = normalize_phone(phone_match.group(1)) if phone_match else None

    address = extract_company_address(tail)

    return {
        "name": name,
        "address": address,
        "phone": phone,
    }


def extract_settlement_type(text: str) -> str | None:
    lines = slice_lines_between_markers(
        text,
        start_markers=[["вид", "заселения"]],
        end_markers=[
            ["лицевой", "счет"],
            ["владельца", "права"],
            ["на", "основании"],
        ],
    )
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("("):
            continue
        normalized_line = canonicalize(stripped)
        if "социальный наем" in normalized_line or "социальный найм" in normalized_line:
            return "социальный наем"
        matched_line_value = match_reference(stripped, SETTLEMENT_TYPES)
        if matched_line_value:
            return matched_line_value
    for line in lines:
        matched_line_value = match_reference(line, SETTLEMENT_TYPES)
        if matched_line_value:
            return matched_line_value
    block = " ".join(lines)
    normalized = canonicalize(block)
    if "социальный наем" in normalized or "социальный найм" in normalized:
        return "социальный наем"
    matched = match_reference(block, SETTLEMENT_TYPES) if block else None
    if matched:
        return matched

    text_normalized = canonicalize(text)
    if "заявитель является собственником жилого помещения" in text_normalized:
        return "частная собственность"
    return None


def extract_administrative_okrug(text: str) -> str | None:
    line = first_line_with(text, "административный округ")
    if not line:
        return match_reference(text, ADMINISTRATIVE_OKRUGS)
    line = re.split(r"\bрайон\b", line, maxsplit=1, flags=re.IGNORECASE)[0]
    return match_reference(line, ADMINISTRATIVE_OKRUGS)


def extract_district(text: str) -> str | None:
    match = re.search(r"\bрайон\s+([А-ЯЁа-яё\-\s]+)", text, re.IGNORECASE)
    if match:
        candidate = match.group(1).splitlines()[0]
        candidate = re.split(r"\s{2,}", candidate, maxsplit=1)[0]
        matched = match_reference(candidate, MOSCOW_DISTRICTS)
        if matched:
            return matched
    line = first_line_with(text, "район")
    return match_reference(line or text, MOSCOW_DISTRICTS)


def extract_owners(text: str, settlement_type: str | None = None) -> list[dict]:
    if is_non_owner_occupancy(settlement_type):
        return []
    owners: list[dict] = []
    all_lines = cleaned_lines(text)
    start_index = find_line_index(all_lines, ["доля", "в", "праве", "собственности"])
    if start_index == -1:
        start_index = find_line_index(all_lines, ["владельца", "права"])
    end_index = find_line_index(all_lines, ["на", "основании"])

    if start_index != -1 and end_index != -1 and end_index > start_index:
        lines = all_lines[start_index + 1 : end_index]
    else:
        settlement_index = find_line_index(all_lines, ["вид", "заселения"])
        if settlement_index != -1 and end_index != -1 and end_index > settlement_index:
            lines = all_lines[settlement_index + 1 : end_index]
        else:
            lines = slice_lines_between_markers(
                text,
                start_markers=[["заселения"], ["частная", "собственность"]],
                end_markers=[["на", "основании"]],
            )
    if not lines:
        return owners

    names = [line for line in lines if is_full_name(line)]
    shares = [normalize_share(line) for line in lines if is_share_line(line)]

    for index, full_name in enumerate(names):
        share = shares[index] if index < len(shares) else None
        owners.append(
            {
                "full_name": full_name,
                "ownership_share": share,
            }
        )

    if len(owners) == 1 and owners[0]["ownership_share"] is None and is_private_property(settlement_type):
        owners[0]["ownership_share"] = "100.00"
    if not owners and is_private_property(settlement_type):
        applicant_name = extract_applicant_name(text)
        if applicant_name:
            return [
                {
                    "full_name": applicant_name,
                    "ownership_share": "100.00",
                }
            ]

    return owners


def extract_primary_tenant(text: str, settlement_type: str | None = None) -> str | None:
    if not is_non_owner_occupancy(settlement_type):
        return None

    lines = slice_lines_between_markers(
        text,
        start_markers=[["вид", "заселения"]],
        end_markers=[["на", "основании"]],
    )
    for line in lines:
        if is_full_name(line):
            return line
    return None


def extract_ownership_documents(text: str) -> list[str]:
    lines = slice_lines_between_markers(
        text,
        start_markers=[["на", "основании"]],
        end_markers=[["характеристика", "занимаемого", "жилого", "помещения"]],
    )
    if not lines:
        return []
    lines = normalize_document_lines(lines)

    documents: list[str] = []
    current = ""

    for line in lines:
        if is_document_stop_line(line):
            continue
        if DOC_START_RE.match(line):
            if current:
                documents.append(clean_document_text(current))
            current = line
            continue
        if current:
            current = join_document_line(current, line)

    if current:
        documents.append(clean_document_text(current))

    return [document for document in documents if document]


def extract_total_area(ocr_results: list[OCRPageResult]) -> str | None:
    for page in sorted(ocr_results, key=lambda item: item.page_number):
        match = AREA_RE.search(page.text[:2500])
        if match:
            return normalize_decimal_string(match.group(1))
    return None


def match_reference(text: str, reference_values: Iterable[str]) -> str | None:
    prepared_text = canonicalize(text)
    matches = []
    for value in reference_values:
        candidate = canonicalize(value)
        if re.search(rf"(?<!\S){re.escape(candidate)}(?!\S)", prepared_text):
            matches.append(value)
    if not matches:
        return None
    return max(matches, key=lambda value: len(canonicalize(value)))


def extract_between(text: str, start_marker: str, end_marker: str) -> str:
    normalized = text.replace("\r", "\n")
    start_index = normalized.lower().find(start_marker.lower())
    if start_index == -1:
        return ""
    start_index += len(start_marker)
    end_index = normalized.lower().find(end_marker.lower(), start_index)
    if end_index == -1:
        end_index = len(normalized)
    return normalized[start_index:end_index].strip()


def cleaned_lines(text: str) -> list[str]:
    lines = []
    for line in text.splitlines():
        normalized = normalize_whitespace(line)
        if normalized and not set(normalized) <= {"_", "-"}:
            lines.append(normalized)
    return lines


def normalize_for_parsing(text: str) -> str:
    normalized = normalize_whitespace(text)
    normalized = re.sub(r"\b[uU][лЛ]\.?", "ул. ", normalized)
    normalized = re.sub(r"\bul\.\b", "ул. ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\b[KК][BВ]\.?\s*", "кв. ", normalized)
    normalized = normalized.replace("дом.", "дом")
    normalized = normalized.replace("дом №", "дом ")
    normalized = normalized.replace("дом Ng", "дом ")
    normalized = normalized.replace("дом No", "дом ")
    normalized = normalized.replace("кор.", "корп.")
    normalized = normalized.replace("кор:", "корп. ")
    normalized = normalized.replace("ул:", "ул. ")
    normalized = normalized.replace("г:", "г. ")
    normalized = normalized.replace("б-р;", "б-р")
    normalized = normalized.replace("б-р,", "б-р")
    normalized = re.sub(r"\b(\d{6})\s+г\b", r"\1", normalized, flags=re.IGNORECASE)
    return normalized


def normalize_street(value: str) -> str:
    street = normalize_whitespace(value).strip(",")
    street = normalize_cyrillic_lookalikes(street)
    street = re.sub(r"\b[uU][лЛ]\.?", "ул.", street)
    street = re.sub(r"\bul\.\b", "ул.", street, flags=re.IGNORECASE)
    street = re.sub(r"^ul\.\s+", "ул. ", street, flags=re.IGNORECASE)
    street = re.sub(r"^uл\.\s+", "ул. ", street, flags=re.IGNORECASE)
    street = street.rstrip(":;,")
    street = re.sub(r"\bул\s+\.", "ул.", street, flags=re.IGNORECASE)
    street = re.sub(r"\bбульв\.?\b", "бульвар", street, flags=re.IGNORECASE)
    street = re.sub(r"^ул\.\s+(.+?)\s+бульвар$", r"б-р \1", street, flags=re.IGNORECASE)
    street = re.sub(r"^ул\.\s+(.+?)\s+просп\.?$", r"пр-кт \1", street, flags=re.IGNORECASE)
    patterns = (
        (r"^(?:ул(?:ица)?\.?\s+)?(.+?)\s+ул(?:ица)?\.?[:;,]?$", "ул. {body}"),
        (r"^(?:пр(?:-?кт|осп(?:ект)?)\.?\s+)?(.+?)\s+(?:пр(?:-?кт|осп(?:ект)?)\.?)$", "пр-кт {body}"),
        (r"^(?:б-р\s+)?(.+?)\s+бульвар\.?$", "б-р {body}"),
        (r"^(?:пер(?:еулок)?\.?\s+)?(.+?)\s+пер(?:еулок)?\.?$", "пер. {body}"),
        (r"^(?:ш(?:оссе)?\.?\s+)?(.+?)\s+шоссе\.?$", "ш. {body}"),
        (r"^(?:пр(?:оезд)?\.?\s+)?(.+?)\s+проезд\.?$", "пр. {body}"),
    )
    for pattern, template in patterns:
        match = re.match(pattern, street, flags=re.IGNORECASE)
        if match:
            street = template.format(body=match.group(1))
            break
    street = re.sub(r"^ул(?:ица)?\.?\s+", "ул. ", street, flags=re.IGNORECASE)
    street = re.sub(r"^ул\.\s+ул\.\s+", "ул. ", street, flags=re.IGNORECASE)
    street = re.sub(r"^просп(?:ект)?\.?\s+", "пр-кт ", street, flags=re.IGNORECASE)
    street = re.sub(r"^пр-кт\s+пр-кт\s+", "пр-кт ", street, flags=re.IGNORECASE)
    street = re.sub(r"(?:\s|,)+ул(?:ица)?\.?$", "", street, flags=re.IGNORECASE)
    street = re.sub(r"\s+,", ",", street)
    street = normalize_whitespace(street).rstrip(":;,")
    street = re.sub(r"\bул(?:ица)?\.?$", "", street, flags=re.IGNORECASE).strip(" ,;:")
    return normalize_whitespace(street)


def normalize_cyrillic_lookalikes(value: str) -> str:
    if not re.search(r"[А-Яа-яЁё]", value) or not re.search(r"[A-Za-z]", value):
        return value
    mapping = str.maketrans(
        {
            "A": "А",
            "a": "а",
            "B": "В",
            "C": "С",
            "c": "с",
            "E": "Е",
            "e": "е",
            "H": "Н",
            "K": "К",
            "M": "М",
            "O": "О",
            "o": "о",
            "P": "Р",
            "p": "р",
            "T": "Т",
            "X": "Х",
            "x": "х",
            "Y": "У",
            "y": "у",
        }
    )
    return value.translate(mapping)


def clean_optional_token(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    cleaned = re.sub(r"(?<=\d)[A](?=$)", "А", cleaned)
    cleaned = re.sub(r"(?<=\d)[a](?=$)", "а", cleaned)
    if not cleaned or set(cleaned) == {"_"}:
        return None
    if canonicalize(cleaned) in {"корп", "строение", "кв", "дом"}:
        return None
    if len(cleaned) == 1 and not cleaned.isdigit():
        return None
    return cleaned


def compose_address(
    street: str | None,
    house: str | None,
    building: str | None,
    structure: str | None,
    apartment: str | None,
) -> str | None:
    parts = []
    if street:
        parts.append(street)
    if house:
        parts.append(f"дом {house}")
    if building:
        parts.append(f"корп. {building}")
    if structure:
        parts.append(f"строение {structure}")
    if apartment:
        parts.append(f"кв. {apartment}")
    return ", ".join(parts) if parts else None


def normalize_company_address(value: str) -> str:
    address = normalize_whitespace(value).strip(" ,;")
    address = re.sub(r"\bдом\.\s*", "дом ", address, flags=re.IGNORECASE)
    address = re.sub(r"\bдом:\s*", "дом ", address, flags=re.IGNORECASE)
    address = re.sub(r"\bкор\.\s*", "корп. ", address, flags=re.IGNORECASE)
    address = re.sub(r"\bкорп\.\s*", "корп. ", address, flags=re.IGNORECASE)
    address = re.sub(r"\bкор:\s*", "корп. ", address, flags=re.IGNORECASE)
    address = re.sub(r"\bул\.\s+([А-ЯЁа-яё-]+)\s+бульвар\b", r"б-р \1", address, flags=re.IGNORECASE)
    address = re.sub(r"\s+,", ",", address)
    return address


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits.startswith("7"):
        return f"+7({digits[1:4]}){digits[4:7]}-{digits[7:9]}-{digits[9:11]}"
    return value


def normalize_share(value: str) -> str:
    share = normalize_whitespace(value).lower()
    if "без" in share:
        return "без опред. долей"
    return normalize_decimal_string(value)


def normalize_decimal_string(value: str) -> str:
    normalized = value.replace(",", ".")
    if "." not in normalized:
        return f"{normalized}.00"
    integer, fractional = normalized.split(".", maxsplit=1)
    return f"{integer}.{fractional[:2].ljust(2, '0')}"


def normalize_ocr_date_token(value: str) -> str | None:
    mapping = str.maketrans(
        {
            "O": "0",
            "О": "0",
            "I": "1",
            "L": "1",
            "Z": "7",
            "S": "5",
            "B": "8",
        }
    )
    normalized = value.upper().translate(mapping)
    normalized = re.sub(r"[^0-9]", "", normalized)
    if len(normalized) != 8:
        return None
    day = int(normalized[:2])
    month = int(normalized[2:4])
    year = int(normalized[4:])
    if not (1 <= day <= 31 and 1 <= month <= 12 and 2000 <= year <= 2099):
        return None
    return f"{normalized[:2]}.{normalized[2:4]}.{normalized[4:]}"


def normalize_ocr_date_fragment(value: str) -> str | None:
    mapping = str.maketrans(
        {
            "O": "0",
            "О": "0",
            "I": "1",
            "L": "1",
            "l": "1",
            "|": "1",
            "Z": "7",
            "S": "5",
            "B": "8",
        }
    )
    normalized = value.translate(mapping)
    normalized = re.sub(r"[^0-9.\s]", "", normalized)

    dotted_match = re.search(r"(\d{2,3})\.(\d{2,3})\.(\d{4})", normalized)
    if dotted_match:
        day = dotted_match.group(1)
        month = dotted_match.group(2)
        if len(day) == 3 and day.startswith("1"):
            day = day[1:]
        if len(month) == 3 and month.startswith("1"):
            month = month[1:]
        day_int = int(day)
        month_int = int(month)
        year_int = int(dotted_match.group(3))
        if 1 <= day_int <= 31 and 1 <= month_int <= 12 and 2000 <= year_int <= 2099:
            return f"{day.zfill(2)}.{month.zfill(2)}.{dotted_match.group(3)}"

    compact_match = re.search(r"(\d{2})\s*[.\s]?\s*(\d{2})\s*[.\s]?\s*(\d{4})", normalized)
    if compact_match:
        day = int(compact_match.group(1))
        month = int(compact_match.group(2))
        year = int(compact_match.group(3))
        if 1 <= day <= 31 and 1 <= month <= 12 and 2000 <= year <= 2099:
            return f"{compact_match.group(1)}.{compact_match.group(2)}.{compact_match.group(3)}"

    return None


def canonicalize(value: str) -> str:
    normalized = value.lower().replace("ё", "е")
    normalized = re.sub(r"[-–—]+", " ", normalized)
    normalized = re.sub(r"[^0-9a-zа-я\s]+", " ", normalized)
    return normalize_whitespace(normalized)


def first_line_with(text: str, marker: str) -> str | None:
    for line in cleaned_lines(text):
        if marker.lower() in line.lower():
            return line
    return None


def extract_applicant_name(text: str) -> str | None:
    all_lines = cleaned_lines(text)
    passport_index = find_line_index(all_lines, ["паспортные", "данные"])
    window = all_lines[: passport_index if passport_index != -1 else 20]
    for line in window:
        candidate = line.split(",")[0].strip()
        if is_full_name(candidate):
            return candidate
    return None


def build_top_lines(words: list, max_top: int) -> list[str]:
    relevant = [word for word in words if word.bbox.top <= max_top]
    if not relevant:
        return []
    relevant.sort(key=lambda word: (word.bbox.top, word.bbox.left))
    lines: list[list] = []
    for word in relevant:
        if not lines or abs(lines[-1][0].bbox.top - word.bbox.top) > 30:
            lines.append([word])
        else:
            lines[-1].append(word)
    return [" ".join(word.text for word in line) for line in lines]


def slice_lines_between_markers(
    text: str,
    start_markers: list[list[str]],
    end_markers: list[list[str]],
) -> list[str]:
    lines = cleaned_lines(text)
    start_index = 0

    for index, line in enumerate(lines):
        if any(line_matches_tokens(line, tokens) for tokens in start_markers):
            start_index = index + 1

    for index in range(start_index, len(lines)):
        if any(line_matches_tokens(lines[index], tokens) for tokens in end_markers):
            return lines[start_index:index]

    return lines[start_index:]


def search_token(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    return clean_optional_token(match.group("value"))


def find_standalone_number(lines: list[str], exclude: set[str] | None = None) -> str | None:
    excluded = exclude or set()
    for line in lines:
        if re.fullmatch(r"\d{1,6}", line) and line not in excluded:
            return line
    return None


def find_address_leading_number(lines: list[str]) -> str | None:
    for line in lines[:2]:
        if re.fullmatch(r"\d{1,4}", line):
            return line
    return None


def is_property_street_line(value: str) -> bool:
    normalized = canonicalize(normalize_for_parsing(value))
    return any(marker in normalized for marker in ("ул", "б р", "бульвар", "просп", "пер", "ш "))


def is_full_name(value: str) -> bool:
    return bool(re.fullmatch(r"[А-ЯЁ][а-яё-]+(?:\s+[А-ЯЁ][а-яё-]+){2}", value))


def is_share_line(value: str) -> bool:
    normalized = normalize_whitespace(value).lower()
    return "без опред" in normalized or bool(re.fullmatch(r"\d+(?:[,.]\d{1,2})?", normalized))


def extract_company_address(text: str) -> str | None:
    normalized = normalize_for_parsing(text)
    normalized = re.sub(r"^адрес\s*:\s*", "", normalized, flags=re.IGNORECASE)
    normalized = PHONE_RE.sub("", normalized)
    normalized = re.sub(r"[,;]?\s*телефон\s*:?", "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bг\s+москва\b", "г. Москва", normalized, flags=re.IGNORECASE)
    normalized = normalize_whitespace(normalized)
    normalized = re.sub(r"\bкорп\.\s*(?=,|$)", "корп. ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bкорп\.\s+(\d{1,3})\b", r"корп. \1", normalized, flags=re.IGNORECASE)

    postal_match = re.search(r"\b\d{6}\b", normalized)
    street_match = re.search(
        r"(ул[.:]?\s*[А-ЯЁа-яё0-9 .-]+?(?:\s+б-р)?)(?=\s+дом|,?\s+дом|$)",
        normalized,
        re.IGNORECASE,
    )
    house = search_token(normalized, r"дом[:\s]*(?P<value>[\w/-]+)")
    if house is None:
        fallback_house = re.search(r"\b(\d{1,3})\b(?=,\s*кор[:\s]|,\s*корп|\s+кор[:\s]|\s+корп)", normalized, re.IGNORECASE)
        if fallback_house:
            house = clean_optional_token(fallback_house.group(1))
    building = search_token(normalized, r"корп\.?\s*(?P<value>[\w/-]+)")
    if building is None:
        fallback_building = re.search(r"\bкор[:\s]*([0-9]{1,3})\b", normalized, re.IGNORECASE)
        if fallback_building:
            building = clean_optional_token(fallback_building.group(1))
    if building:
        building = re.sub(r"[^0-9/-].*$", "", building)

    parts = []
    if postal_match:
        parts.append(postal_match.group(0))
    if "страна россия" in normalized.lower():
        parts.append("страна Россия")
    if "г. москва" in normalized.lower() or "г москва" in normalized.lower() or "москва" in normalized.lower():
        parts.append("г. Москва")
    if street_match:
        parts.append(normalize_street(street_match.group(1)))
    if house:
        parts.append(f"дом {house}")
    if building:
        parts.append(f"корп. {building}")

    if not parts:
        return normalize_company_address(normalized)
    return deduplicate_address_parts(parts)


def normalize_company_name(value: str) -> str:
    normalized = normalize_whitespace(value.replace(":", ""))
    normalized = re.sub(r"^О00\b", "ООО", normalized)
    normalized = normalized.replace("<", "\"").replace(">", "\"")
    normalized = re.sub(r"(?<=\s)c(?=\s)", "с", normalized)
    normalized = re.sub(r"Домами[хж]$", "Домами\"", normalized)
    normalized = re.sub(r"ж$", "\"", normalized)
    normalized = normalized.rstrip("'\"")
    if normalized.count('"') % 2 == 1:
        normalized = f'{normalized}"'
    return normalized


def is_social_tenancy(settlement_type: str | None) -> bool:
    if not settlement_type:
        return False
    normalized = canonicalize(settlement_type)
    return "социальный наем" in normalized or "социальный найм" in normalized


def is_non_owner_occupancy(settlement_type: str | None) -> bool:
    if not settlement_type:
        return False
    normalized = canonicalize(settlement_type)
    return any(
        marker in normalized
        for marker in (
            "социальный наем",
            "социальный найм",
            "безвозмездное пользование",
            "коммерческий наем",
            "коммерческий найм",
        )
    )


def is_private_property(settlement_type: str | None) -> bool:
    if not settlement_type:
        return False
    return canonicalize(settlement_type) == canonicalize("частная собственность")


def extract_passport_document_type(text: str) -> str | None:
    lowered = canonicalize(text)
    if "паспорт рф" in lowered:
        return "паспорт РФ"
    if "паспорт гражданина рф" in lowered:
        return "паспорт гражданина РФ"
    if lowered.startswith("справка") or "справка " in lowered:
        return "справка"
    return None


def is_document_continuation(line: str) -> bool:
    normalized = canonicalize(line)
    if any(
        marker in normalized
        for marker in (
            "субар",
            "иной",
            "основан",
            "лицев",
            "суда",
            "решен",
            "oama",
            "дата",
            "кем выдан",
            "указы",
        )
    ):
        return False
    return bool(re.match(r"^[а-яёa-z0-9]", line.strip(), flags=re.IGNORECASE))


def is_document_stop_line(line: str) -> bool:
    normalized = canonicalize(line)
    return line.startswith("(") or any(
        marker in normalized
        for marker in (
            "указы",
            "oama",
            "дата",
            "кем выдан",
            "иной документ",
            "основанием для открытия",
            "лицевого счета",
            "субар",
        )
    )


def join_document_line(current: str, line: str) -> str:
    if current.rstrip().endswith("-"):
        return f"{current.rstrip('- ').rstrip()}{line.lstrip()}"
    return f"{current} {line}"


def clean_document_text(value: str) -> str:
    cleaned = normalize_whitespace(value)
    for rule in get_ownership_document_text_regex_replacements():
        flags = 0
        for flag_name in rule.get("flags", []):
            flags |= getattr(re, str(flag_name))
        cleaned = re.sub(str(rule["pattern"]), str(rule["replacement"]), cleaned, flags=flags)
    for rule in get_ownership_document_text_replacements():
        cleaned = cleaned.replace(str(rule["old"]), str(rule["new"]))
    return cleaned.strip(" ,;")


def last_date(value: str) -> str | None:
    matches = DATE_RE.findall(value)
    return matches[-1] if matches else None


def first_date(value: str) -> str | None:
    matches = DATE_RE.findall(value)
    return matches[0] if matches else None


def normalize_issued_by(value: str) -> str:
    issued_by = normalize_passport_issuer_grammar(value) or normalize_whitespace(value).strip(" ,;:")
    issued_by = re.sub(r"\bгор:\s*москвы\b", "г. Москвы", issued_by, flags=re.IGNORECASE)
    issued_by = re.sub(r"\bгор\.\s*москвы\b", "г. Москвы", issued_by, flags=re.IGNORECASE)
    issued_by = re.sub(r"\bг\.\s*москкве\b", "г. Москве", issued_by, flags=re.IGNORECASE)
    issued_by = re.sub(r"\bг\.\s*москва\b", "г. Москве", issued_by, flags=re.IGNORECASE)
    issued_by = re.sub(r"\bмосккве\b", "Москве", issued_by, flags=re.IGNORECASE)
    return issued_by


def take_current_passport_lines(lines: list[str]) -> list[str]:
    current: list[str] = []
    seen_passport = False
    for index, line in enumerate(lines):
        normalized = canonicalize(line)
        if "паспорт" in normalized and seen_passport:
            break
        if "паспорт" in normalized:
            seen_passport = True
        if seen_passport:
            current.append(line)
            if first_date(line):
                next_line = lines[index + 1] if index + 1 < len(lines) else None
                if next_line:
                    next_normalized = canonicalize(next_line)
                    if (
                        "паспорт" not in next_normalized
                        and re.fullmatch(r"[\"'«]?[А-ЯЁа-яё-]{3,}[\"'»]?", next_line.strip())
                    ):
                        current.append(next_line)
                break
    return current or lines[:2]


def extract_house_from_region(words: list, image_path: str) -> str | None:
    dom_word = None
    for word in sorted(words, key=lambda item: (item.bbox.top, item.bbox.left)):
        if "дом" in canonicalize(word.text) and 1300 <= word.bbox.top <= 1700:
            dom_word = word
            break
    if dom_word is None:
        return None

    candidates: list[int] = []
    for width in (220, 320, 450):
        crop_text = read_crop_text(
            image_path,
            (
                dom_word.bbox.left + dom_word.bbox.width,
                dom_word.bbox.top - 20,
                dom_word.bbox.left + dom_word.bbox.width + width,
                dom_word.bbox.top + dom_word.bbox.height + 30,
            ),
            allowlist="0123456789",
        )
        for group in re.findall(r"\d{1,3}", crop_text):
            normalized = group.lstrip("0") or "0"
            if normalized.isdigit() and 0 < int(normalized) <= 999:
                candidates.append(int(normalized))
    if not candidates:
        return None
    return str(min(candidates))


def find_line_index(lines: list[str], tokens: list[str]) -> int:
    for index, line in enumerate(lines):
        if line_matches_tokens(line, tokens):
            return index
    return -1


def trim_to_relevant_address_lines(lines: list[str]) -> list[str]:
    trimmed: list[str] = []
    started = False
    for line in lines:
        normalized = canonicalize(normalize_for_parsing(line))
        if not started and not any(token in normalized for token in ("дом", "ул", "кв", "корп", "строение")):
            continue
        started = True
        trimmed.append(line)
        if len(trimmed) >= 6:
            break
    return trimmed


def deduplicate_address_parts(parts: list[str]) -> str:
    deduplicated: list[str] = []
    seen: set[str] = set()
    for part in parts:
        key = canonicalize(part)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(part)
    return ", ".join(deduplicated)


def line_matches_tokens(line: str, tokens: list[str]) -> bool:
    normalized = canonicalize(line)
    return all(canonicalize(token) in normalized for token in tokens)


def management_line_priority(line: str) -> tuple[int, str]:
    normalized = canonicalize(line)
    if normalized.startswith("адрес"):
        return (0, normalized)
    if "ул" in normalized or "москва" in normalized or "россия" in normalized:
        return (1, normalized)
    if "б р" in normalized or "б р" in normalized.replace("-", " "):
        return (2, normalized)
    if "дом" in normalized or "кор" in normalized:
        return (3, normalized)
    if "телефон" in normalized:
        return (4, normalized)
    return (5, normalized)


def normalize_document_lines(lines: list[str]) -> list[str]:
    normalized_lines: list[str] = []
    pending_prefix = ""
    for index, line in enumerate(lines):
        current = normalize_whitespace(line)
        candidate = canonicalize(current)
        next_line = normalize_whitespace(lines[index + 1]) if index + 1 < len(lines) else ""
        next_candidate = canonicalize(next_line)
        if candidate.startswith("государственного реестра") and next_candidate.startswith("выписка"):
            pending_prefix = current
            continue
        if pending_prefix and candidate.startswith("выписка"):
            current = f"{current} {pending_prefix}"
            pending_prefix = ""
        normalized_lines.append(current)
    if pending_prefix:
        normalized_lines.append(pending_prefix)
    return normalized_lines
