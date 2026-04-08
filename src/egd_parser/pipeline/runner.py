import re

from egd_parser.domain.models.document import ParsedDocument
from egd_parser.infrastructure.ocr.factory import create_ocr_engine
from egd_parser.infrastructure.pdf.poppler_renderer import PopplerPDFRenderer
from egd_parser.infrastructure.settings import get_settings
from egd_parser.pipeline.extractors.page1 import extract_page1
from egd_parser.pipeline.extractors.page2 import extract_page2
from egd_parser.pipeline.extractors.page2_row_ocr import apply_row_reocr_fallback
from egd_parser.pipeline.extractors.page2_residents import (
    annotate_without_registration,
    build_without_registration_trace,
    filter_out_without_registration,
)
from egd_parser.pipeline.layout.page_classifier import classify_pages
from egd_parser.pipeline.normalize.dates import normalize_dates
from egd_parser.pipeline.normalize.rule_registry import (
    get_name_prefix_fixes,
    get_ownership_document_replacements,
    get_patronymic_fixes,
)
from egd_parser.pipeline.preprocess.contrast import enhance_contrast
from egd_parser.pipeline.validate.confidence import (
    score_address_confidence,
    score_date_confidence,
    score_enum_confidence,
    score_identity_document_confidence,
    score_person_name_confidence,
)
from egd_parser.pipeline.validate.required_fields import collect_required_field_warnings
from egd_parser.utils.text import normalize_whitespace


class PipelineRunner:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.renderer = PopplerPDFRenderer()
        self.ocr = create_ocr_engine(self.settings)

    def run(self, filename: str, content: bytes) -> ParsedDocument:
        pages = self.renderer.render(filename=filename, content=content)
        processed_pages = [enhance_contrast(page) for page in pages]
        classified_pages = classify_pages(processed_pages)
        ocr_results = self.ocr.recognize(classified_pages)
        page1_data = extract_page1(ocr_results)
        page2_data = extract_page2(ocr_results)
        page2_data["registered_persons_constantly"] = apply_row_reocr_fallback(
            page2_data.get("registered_persons_constantly", {}),
            classified_pages,
            self.ocr,
        )
        page2_data["registered_persons_constantly"] = annotate_without_registration(
            page2_data.get("registered_persons_constantly", {})
        )
        extracted_data = build_public_payload(page1_data, page2_data)
        normalized_data = normalize_dates(extracted_data)
        warnings = collect_required_field_warnings(normalized_data)
        extraction_trace = build_extraction_trace(normalized_data, page2_data)

        return ParsedDocument(
            filename=filename,
            page_count=len(classified_pages),
            pages=classified_pages,
            warnings=warnings,
            extracted_data=normalized_data,
            metadata={
                "ocr_engine": self.settings.ocr_engine,
                "page_images": [page.image_path for page in classified_pages],
                "ocr_preview": {
                    f"page_{page.page_number}": page.text[:2000]
                    for page in ocr_results
                },
                "extraction_trace": extraction_trace,
            },
        )


def build_public_payload(page1_payload: dict, page2_payload: dict) -> dict:
    page1 = page1_payload.get("page_1", {})
    property_address = build_public_property_address(page1.get("property_address", {}))
    page2 = reconcile_registered_persons(page1, page2_payload)
    page2.pop("__trace__", None)
    owners = [
        {
            "full_name": owner.get("full_name"),
            "ownership_share": owner.get("ownership_share"),
        }
        for owner in page1.get("owners", [])
    ]

    ownership_documents = [normalize_ownership_document(item) for item in page1.get("ownership_documents", [])]

    return {
        "document_type": "egd",
        "page_1": {
            "document_date": page1.get("document_date"),
            "administrative_okrug": page1.get("administrative_okrug"),
            "district": page1.get("district"),
            "passport": build_public_passport(page1.get("passport", {})),
            "property_address": property_address,
            "management_company": {
                "name": page1.get("management_company", {}).get("name"),
            },
            "settlement_type": page1.get("settlement_type"),
            "owners": owners,
            "primary_tenant": page1.get("primary_tenant"),
            "ownership_documents": ownership_documents,
        },
        "page_2": page2,
    }


def build_extraction_trace(public_payload: dict, raw_page2_payload: dict) -> dict:
    raw_trace = raw_page2_payload.get("__trace__", {})
    residents_trace = dict(raw_trace.get("registered_persons_constantly", {}))
    page1 = public_payload.get("page_1", {})
    public_persons = (
        public_payload.get("page_2", {})
        .get("registered_persons_constantly", {})
        .get("persons", [])
    )
    selected_method = residents_trace.get("selected_method", "unknown")

    residents_trace["persons"] = [
        {
            "full_name": person.get("full_name"),
            "full_name_confidence": score_person_name_confidence(person.get("full_name")),
            "birthday_date_confidence": 1.0 if person.get("birthday_date") else 0.0,
            "passport_confidence": score_identity_document_confidence(person.get("passport")),
            "name_source_method": selected_method,
            "passport_source_method": selected_method,
            "source_pages": residents_trace.get("page_numbers", []),
        }
        for person in public_persons
    ]
    residents_trace["without_registration_persons"] = build_without_registration_trace(
        raw_page2_payload.get("registered_persons_constantly", {}).get("persons", [])
    )

    owners = page1.get("owners", [])
    primary_tenant = page1.get("primary_tenant")
    property_address = page1.get("property_address", {})
    address_full = property_address.get("full")
    settlement_type = page1.get("settlement_type")

    return {
        "page_1": {
            "document_date": {
                "value": page1.get("document_date"),
                "confidence": score_date_confidence(page1.get("document_date")),
                "source_method": "page1_anchor",
                "source_pages": [1],
            },
            "property_address": {
                "value": address_full,
                "confidence": score_address_confidence(address_full),
                "source_method": "page1_address_block",
                "source_pages": [1],
            },
            "settlement_type": {
                "value": settlement_type,
                "confidence": score_enum_confidence(settlement_type),
                "source_method": "page1_settlement_block",
                "source_pages": [1],
            },
            "subject": {
                "kind": "owners" if owners else ("primary_tenant" if primary_tenant else None),
                "count": len(owners) if owners else (1 if primary_tenant else 0),
                "confidence": 1.0 if owners or primary_tenant else 0.0,
                "source_method": "page1_rights_block",
                "source_pages": [1],
            },
        },
        "page_2": {
            "registered_persons_constantly": residents_trace,
        }
    }


def normalize_ownership_document(value: str) -> str:
    normalized = value
    for rule in get_ownership_document_replacements():
        normalized = normalized.replace(rule["old"], rule["new"])
    return normalized


def build_public_passport(passport: dict) -> dict:
    normalized = {
        "document_type": None,
        "series": None,
        "number": None,
        "issued_by": None,
        "issue_date": None,
        "raw": None,
    }
    if passport:
        normalized.update(dict(passport))
    document_type = normalized.get("document_type")
    if document_type and document_type.lower().startswith("паспорт"):
        normalized["document_type"] = "паспорт"
    return normalized


def build_public_property_address(address: dict) -> dict:
    public_address = {
        "street": None,
        "house": None,
        "building": None,
        "structure": None,
        "apartment": None,
        "full": None,
    }
    if not address:
        return public_address

    street = expand_public_street_name(address.get("street"))
    house = address.get("house")
    building = address.get("building")
    structure = address.get("structure")
    apartment = address.get("apartment")

    parts = []
    if street:
        parts.append(street)
    if house:
        parts.append(f"дом № {house}")
    if building:
        parts.append(f"корп. {building}")
    if structure:
        parts.append(f"строение {structure}")
    if apartment:
        parts.append(f"кв. {apartment}")

    public_address.update(dict(address))
    public_address["street"] = street
    public_address["full"] = ", ".join(parts) if parts else None
    return public_address


def expand_public_street_name(value: str | None) -> str | None:
    if not value:
        return value
    if value.startswith("б-р "):
        return f"{value[4:]} бульвар"
    if value.startswith("пр-кт "):
        return f"{value[6:]} пр-кт"
    return value


def reconcile_registered_persons(page1: dict, page2: dict) -> dict:
    persons_block = page2.get("registered_persons_constantly", {})
    persons = [dict(person) for person in persons_block.get("persons", [])]
    candidates = [
        owner.get("full_name")
        for owner in page1.get("owners", [])
        if owner.get("full_name")
    ]
    if page1.get("primary_tenant"):
        candidates.append(page1["primary_tenant"])

    used = {person.get("full_name") for person in persons if person.get("full_name") in candidates}
    remaining = [candidate for candidate in candidates if candidate not in used]

    public_persons = []
    for person in persons:
        name = person.get("full_name") or ""
        if should_skip_name_reconciliation(person):
            person["full_name"] = normalize_registered_full_name(person.get("full_name"))
        else:
            matched_candidate = find_best_candidate_name(name, candidates)
            if matched_candidate:
                person["full_name"] = matched_candidate
            elif is_incomplete_registered_name(name) and len(remaining) == 1:
                person["full_name"] = remaining[0]
                used.add(remaining[0])
                remaining = [candidate for candidate in candidates if candidate not in used]
            person["full_name"] = normalize_registered_full_name(person.get("full_name"))
            person = normalize_registered_passport_by_person(person)
            person = merge_page1_subject_passport(page1, person)
        public_persons.append(person)

    public_persons = filter_out_without_registration(public_persons)

    patched = dict(page2)
    patched["registered_persons_constantly"] = {
        "count": len(public_persons),
        "persons": [build_public_person(strip_internal_person_metadata(person)) for person in public_persons],
    }
    return patched


def strip_internal_person_metadata(person: dict) -> dict:
    return {key: value for key, value in person.items() if not key.startswith("__")}


def merge_page1_subject_passport(page1: dict, person: dict) -> dict:
    page1_passport = build_public_passport(page1.get("passport", {}))
    if not page1_passport:
        return person

    resident_passport = person.get("passport") or {}
    if should_prefer_page1_identity_document_by_number(page1_passport, resident_passport):
        person["passport"] = dict(page1_passport)
        return person

    person_name = person.get("full_name")
    if not person_name:
        return person

    subject_name = page1.get("applicant_name") or page1.get("primary_tenant")
    if not subject_name and len(page1.get("owners", [])) == 1:
        subject_name = page1["owners"][0].get("full_name")

    if not subject_name:
        return person

    if canonicalize_name(person_name) != canonicalize_name(subject_name):
        return person

    if should_prefer_page1_identity_document(page1_passport, resident_passport):
        person["passport"] = dict(page1_passport)
    return person


def same_identity_document_family(left: dict, right: dict) -> bool:
    left_type = str(left.get("document_type") or "").strip().lower()
    right_type = str(right.get("document_type") or "").strip().lower()
    if not left_type or not right_type:
        return True
    return left_type == right_type


def should_prefer_page1_identity_document(page1_document: dict, resident_document: dict) -> bool:
    if not same_identity_document_family(page1_document, resident_document):
        return False

    page1_score = score_identity_document_confidence(page1_document)
    resident_score = score_identity_document_confidence(resident_document)
    if page1_score > resident_score:
        return True

    page1_issued_by = normalize_whitespace(str(page1_document.get("issued_by") or ""))
    resident_issued_by = normalize_whitespace(str(resident_document.get("issued_by") or ""))
    if page1_score == resident_score and page1_issued_by and resident_issued_by:
        if len(page1_issued_by) > len(resident_issued_by) and page1_issued_by.startswith(resident_issued_by):
            return True
    return False


def should_prefer_page1_identity_document_by_number(page1_document: dict, resident_document: dict) -> bool:
    if not same_identity_document_family(page1_document, resident_document):
        return False

    page1_number = normalize_whitespace(str(page1_document.get("number") or ""))
    resident_number = normalize_whitespace(str(resident_document.get("number") or ""))
    if not page1_number or page1_number != resident_number:
        return False

    page1_series = normalize_whitespace(str(page1_document.get("series") or ""))
    resident_series = normalize_whitespace(str(resident_document.get("series") or ""))
    resident_issued_by = normalize_whitespace(str(resident_document.get("issued_by") or ""))

    if page1_series and resident_series and page1_series != resident_series:
        return True
    if resident_issued_by and (
        any(char.isdigit() for char in resident_issued_by)
        or any(token in resident_issued_by.lower() for token in ("ул.", "дом", "кв.", "мкр"))
        or any(token in resident_issued_by for token in ("MOCK", "MVD", "HC", "p-ne", "p/o"))
    ):
        return True

    return should_prefer_page1_identity_document(page1_document, resident_document)


def is_incomplete_registered_name(value: str) -> bool:
    if not value:
        return True
    if value.count(" ") < 2:
        return True
    if "-" in value:
        return True
    return False


def find_best_candidate_name(value: str, candidates: list[str]) -> str | None:
    if not value:
        return None

    normalized_value = canonicalize_name(value)
    value_parts = normalized_value.split()
    if not value_parts:
        return None

    surname_candidates = set(value_parts)
    best_match = None
    best_score = 0

    for candidate in candidates:
        normalized_candidate = canonicalize_name(candidate)
        candidate_parts = normalized_candidate.split()
        if len(candidate_parts) < 2:
            continue
        if candidate_parts[0] not in surname_candidates:
            continue

        score = 1
        if len(value_parts) >= 2 and len(candidate_parts) >= 2:
            if candidate_parts[1].startswith(value_parts[1]) or value_parts[1].startswith(candidate_parts[1]):
                score += 1
        if len(value_parts) >= 3 and len(candidate_parts) >= 3:
            if candidate_parts[2].startswith(value_parts[2]) or value_parts[2].startswith(candidate_parts[2]):
                score += 1
        if score > best_score:
            best_score = score
            best_match = candidate

    if len(value_parts) >= 3 and best_score >= 3:
        return best_match

    if len(value_parts) == 2 and best_score >= 2:
        return best_match

    if best_score == 1:
        matching_by_surname = [
            candidate
            for candidate in candidates
            if canonicalize_name(candidate).split() and canonicalize_name(candidate).split()[0] in surname_candidates
        ]
        if len(matching_by_surname) == 1 and is_incomplete_registered_name(value):
            return matching_by_surname[0]

    return None


def canonicalize_name(value: str) -> str:
    normalized = value.replace("-", " ")
    normalized = " ".join(part for part in normalized.split() if part)
    return normalized.lower()


def should_skip_name_reconciliation(person: dict) -> bool:
    birthday_date = person.get("birthday_date") or ""
    passport = person.get("passport") or {}
    full_name = person.get("full_name") or ""

    if passport.get("raw"):
        return False
    if not is_incomplete_registered_name(full_name):
        return False
    if len(birthday_date) != 10:
        return False

    year_text = birthday_date[-4:]
    if not year_text.isdigit():
        return False
    return int(year_text) >= 2010


def normalize_registered_full_name(value: str | None) -> str | None:
    if not value:
        return value
    normalized = normalize_broken_registered_name_text(value)
    for prefix, replacement in get_name_prefix_fixes().items():
        if normalized.startswith(prefix):
            return replacement
    tokens = normalized.split()
    if len(tokens) != 3:
        return normalized

    patronymic = tokens[2]
    patronymic_fixes = get_patronymic_fixes()
    if patronymic in patronymic_fixes:
        gender_key = "female" if tokens[0].endswith(("ова", "ева", "ина")) else "male"
        tokens[2] = patronymic_fixes[patronymic][gender_key]
    else:
        fixed_patronymic = fix_broken_patronymic_token(tokens[2], is_likely_female_name(tokens))
        if fixed_patronymic:
            tokens[2] = fixed_patronymic

    return " ".join(tokens)


def normalize_broken_registered_name_text(value: str) -> str:
    normalized = value.replace("ВалентинаФоминична", "Валентина Фоминична")
    tokens = normalized.split()
    if len(tokens) == 3 and tokens[2] and not tokens[2][:1].isupper():
        merged = f"{tokens[1]}{tokens[2]}"
        merged = re.sub(r"([а-яё])([А-ЯЁ])", r"\1 \2", merged)
        merged_parts = merged.split()
        if len(merged_parts) == 2:
            return " ".join([tokens[0], *merged_parts])
    return normalized


def fix_broken_patronymic_token(value: str, is_female: bool) -> str | None:
    stripped = value.strip("-")
    if len(stripped) < 3:
        return None

    replacements = (
        ("ьеб", "ьевна" if is_female else "ьевич"),
        ("еб", "евна" if is_female else "евич"),
        ("об", "овна" if is_female else "ович"),
        ("б", "вна" if is_female else "вич"),
    )
    lowered = stripped.lower()
    for bad_suffix, good_suffix in replacements:
        if lowered.endswith(bad_suffix):
            base = stripped[: -len(bad_suffix)]
            if base:
                return f"{base}{good_suffix}"
    return None


def is_likely_female_name(tokens: list[str]) -> bool:
    surname = tokens[0] if tokens else ""
    first_name = tokens[1] if len(tokens) > 1 else ""
    if surname.endswith(("ова", "ева", "ина", "ая")):
        return True
    return first_name.endswith(("а", "я", "на"))


def normalize_registered_passport_by_person(person: dict) -> dict:
    passport = dict(person.get("passport") or {})

    if passport:
        from egd_parser.pipeline.extractors.page2_identity_documents import (
            normalize_identity_document_by_type,
        )

        passport = normalize_identity_document_by_type(passport)

    person["passport"] = passport
    return person


def build_public_person(person: dict) -> dict:
    return {
        "full_name": person.get("full_name"),
        "birthday_date": person.get("birthday_date"),
        "passport": build_public_passport(person.get("passport", {})),
        "departure": build_public_departure(person.get("departure", {})),
    }


def build_public_departure(departure: dict) -> dict:
    normalized = {
        "status": None,
        "reason": None,
        "raw": None,
        "death_date": None,
        "departure_date": None,
        "act_record_number": None,
        "act_record_date": None,
        "issued_by": None,
        "destination_address": None,
        "validation": {
            "scheme": None,
            "applicable": None,
            "passed": None,
        },
    }
    if departure:
        normalized.update({key: value for key, value in departure.items() if key != "validation"})
        validation = departure.get("validation") or {}
        normalized["validation"].update(validation)
    return normalized
