from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from egd_parser.domain.models.page import PageImage
from egd_parser.domain.ports.ocr_engine import OCREngine
from egd_parser.pipeline.extractors.page2_departures import parse_departure_from_text
from egd_parser.pipeline.extractors.page2_identity_documents import parse_identity_document_cell
from egd_parser.pipeline.validate.confidence import score_identity_document_confidence
from egd_parser.utils.image import ensure_directory


def apply_row_reocr_fallback(
    persons_block: dict,
    pages: list[PageImage],
    ocr_engine: OCREngine,
) -> dict:
    persons = [dict(person) for person in persons_block.get("persons", [])]
    if not persons:
        return persons_block

    page_map = {page.number: page for page in pages if page.image_path}
    for person in persons:
        if not should_retry_row_ocr(person):
            continue
        page = page_map.get(person.get("__page_number"))
        if page is None:
            continue
        current_document = person.get("passport") or {}
        improved_document = reocr_person_document(person, page, ocr_engine)
        if should_replace_document_with_reocr(current_document, improved_document):
            person["passport"] = improved_document
        improved_departure = reocr_person_departure(person, page, ocr_engine)
        if departure_quality(improved_departure) > departure_quality(person.get("departure")):
            person["departure"] = improved_departure

    patched = dict(persons_block)
    patched["persons"] = persons
    patched["count"] = len(persons)
    return patched


def should_retry_row_ocr(person: dict) -> bool:
    document = person.get("passport") or {}
    if not document:
        return False

    document_type = (document.get("document_type") or "").lower()
    if document_type == "паспорт":
        if not document.get("number") or not document.get("series"):
            return True
        if not document.get("issued_by") and not document.get("issue_date"):
            return True
    elif document_type == "свидетельство о рождении":
        if not document.get("number") or not document.get("issued_by") or not document.get("issue_date"):
            return True
    elif document_type == "справка":
        if not document.get("number") or not document.get("issued_by"):
            return True
    return score_identity_document_confidence(document) < 0.8


def reocr_person_document(person: dict, page: PageImage, ocr_engine: OCREngine) -> dict:
    preferred_type = ((person.get("passport") or {}).get("document_type")) or None
    best_document: dict = {}
    for crop_mode in ("document", "document_wide", "row_right", "row_right_wide"):
        crop_paths = build_document_crops(page, person, crop_mode)
        if not crop_paths:
            continue
        for crop_path in crop_paths:
            crop_page = PageImage(number=person.get("__page_number") or page.number, image_path=str(crop_path))
            ocr_results = ocr_engine.recognize([crop_page])
            if not ocr_results:
                continue
            crop_text = (ocr_results[0].text or "").strip()
            if not crop_text:
                continue
            parsed = parse_identity_document_cell(crop_text, preferred_type=preferred_type)
            if document_quality(parsed) > document_quality(best_document):
                best_document = parsed
    return best_document


def reocr_person_departure(person: dict, page: PageImage, ocr_engine: OCREngine) -> dict:
    if not should_retry_departure_ocr(person):
        return person.get("departure") or {}

    best_departure = person.get("departure") or {}
    for crop_mode in ("departure", "departure_wide", "row_right", "row_right_wide"):
        crop_paths = build_document_crops(page, person, crop_mode)
        if not crop_paths:
            continue
        for crop_path in crop_paths:
            crop_page = PageImage(number=person.get("__page_number") or page.number, image_path=str(crop_path))
            ocr_results = ocr_engine.recognize([crop_page])
            if not ocr_results:
                continue
            crop_text = (ocr_results[0].text or "").strip()
            if not crop_text:
                continue
            parsed = parse_departure_from_text(crop_text)
            if departure_quality(parsed) > departure_quality(best_departure):
                best_departure = parsed
    return best_departure


def build_document_crops(page: PageImage, person: dict, mode: str) -> list[Path]:
    if not page.image_path:
        return []
    try:
        from PIL import Image, ImageFilter, ImageOps
    except ImportError:
        return []

    document_bbox = person.get("__document_bbox") or {}
    departure_bbox = person.get("__departure_bbox") or {}
    row_bbox = person.get("__row_bbox") or {}
    if not document_bbox and not departure_bbox and not row_bbox:
        return []

    with Image.open(page.image_path) as image:
        width, height = image.size
        left, top, right, bottom = compute_crop_bounds(width, height, document_bbox, departure_bbox, row_bbox, mode)
        if right <= left or bottom <= top:
            return []

        cropped = image.crop((left, top, right, bottom)).convert("L")
        variants = []

        base = ImageOps.autocontrast(cropped)
        base = base.resize((max(1, base.width * 2), max(1, base.height * 2)))
        variants.append(("base", base))

        sharp = base.filter(ImageFilter.SHARPEN)
        variants.append(("sharp", sharp))

        threshold = base.point(lambda value: 255 if value > 170 else 0)
        variants.append(("threshold", threshold))

        dark_threshold = base.point(lambda value: 255 if value > 145 else 0)
        variants.append(("threshold_dark", dark_threshold))

        out_dir = ensure_directory(Path("tmp/row_reocr"))
        paths: list[Path] = []
        for suffix, variant in variants:
            out_path = out_dir / f"row_reocr_{mode}_{suffix}_{uuid4().hex}.png"
            variant.save(out_path)
            paths.append(out_path)
        return paths


def compute_crop_bounds(width: int, height: int, document_bbox: dict, departure_bbox: dict, row_bbox: dict, mode: str) -> tuple[int, int, int, int]:
    if mode in {"document", "document_wide"} and document_bbox:
        pad_x = 80 if mode == "document" else 180
        pad_top = 24 if mode == "document" else 40
        pad_bottom = 24 if mode == "document" else 50
        left = max(0, int(document_bbox.get("left", 0)) - pad_x)
        top = max(0, int(document_bbox.get("top", 0)) - pad_top)
        right = min(width, int(document_bbox.get("left", 0) + document_bbox.get("width", 0)) + pad_x)
        bottom = min(height, int(document_bbox.get("top", 0) + document_bbox.get("height", 0)) + pad_bottom)
        return left, top, right, bottom

    if mode in {"departure", "departure_wide"} and departure_bbox:
        pad_x = 80 if mode == "departure" else 180
        pad_top = 24 if mode == "departure" else 40
        pad_bottom = 220 if mode == "departure" else 340
        left = max(0, int(departure_bbox.get("left", 0)) - pad_x)
        top = max(0, int(departure_bbox.get("top", 0)) - pad_top)
        right = min(width, int(departure_bbox.get("left", 0) + departure_bbox.get("width", 0)) + pad_x)
        bottom = min(height, int(departure_bbox.get("top", 0) + departure_bbox.get("height", 0)) + pad_bottom)
        return left, top, right, bottom

    pad_x = 80 if mode == "row_right" else 180
    pad_top = 24 if mode == "row_right" else 40
    pad_bottom = 24 if mode == "row_right" else 50
    left = max(0, int(row_bbox.get("left", 0) + row_bbox.get("width", 0) * 0.45) - pad_x)
    top = max(0, int(row_bbox.get("top", 0)) - pad_top)
    right = min(width, int(row_bbox.get("left", 0) + row_bbox.get("width", 0)) + pad_x)
    bottom = min(height, int(row_bbox.get("top", 0) + row_bbox.get("height", 0)) + pad_bottom)
    return left, top, right, bottom


def document_quality(document: dict | None) -> float:
    if not document:
        return 0.0
    score = score_identity_document_confidence(document)
    document_type = (document.get("document_type") or "").lower()
    series = (document.get("series") or "").strip()
    number = (document.get("number") or "").strip()
    issued_by = (document.get("issued_by") or "").strip()
    issue_date = (document.get("issue_date") or "").strip()
    raw = (document.get("raw") or "").strip()

    if document.get("number"):
        score += 0.2
    if document.get("issued_by"):
        score += 0.2
    if document.get("issue_date"):
        score += 0.2
    if document_type == "паспорт":
        if series and not __import__("re").fullmatch(r"\d{2}\s\d{2}", series):
            score -= 0.6
        if number and not __import__("re").fullmatch(r"\d{6}", number):
            score -= 0.6
        if issue_date and not __import__("re").fullmatch(r"\d{2}\.\d{2}\.\d{4}", issue_date):
            score -= 0.5
    if issued_by:
        if any(token in issued_by for token in ("указывается", "Ф.И.О", "имеются", "человек в семье", "должностного лица")):
            score -= 1.2
        if any(char.isdigit() for char in issued_by):
            score -= 0.5
        if __import__("re").search(r"[A-Za-z]", issued_by):
            score -= 0.5
        if issued_by[:1].islower() or len(issued_by) <= 3:
            score -= 0.5
    if raw and any(token in raw for token in ("указывается", "человек в семье", "имеются тя")):
        score -= 1.0
    return score


def should_replace_document_with_reocr(current_document: dict | None, improved_document: dict | None) -> bool:
    if document_quality(improved_document) <= document_quality(current_document):
        return False

    current_document = current_document or {}
    improved_document = improved_document or {}
    current_number = (current_document.get("number") or "").strip()
    improved_number = (improved_document.get("number") or "").strip()
    current_series = (current_document.get("series") or "").strip()
    improved_series = (improved_document.get("series") or "").strip()

    if current_number and improved_number and current_number != improved_number:
        return False
    if current_series and improved_series and current_series != improved_series and current_number:
        return False
    return True


def should_retry_departure_ocr(person: dict) -> bool:
    departure = person.get("departure") or {}
    if not departure:
        return False
    reason = (departure.get("reason") or "").lower()
    raw = (departure.get("raw") or "").lower()
    if reason == "death":
        if not departure.get("act_record_number"):
            return True
        if departure.get("act_record_number") and len(str(departure.get("act_record_number"))) < 21 and "а/з" in raw:
            return True
        if not departure.get("act_record_date") and (" от" in raw or raw.endswith("от") or "оф." in raw or raw.endswith("а/")):
            return True
    if reason == "form_6_stub" and not departure.get("destination_address"):
        return True
    return False


def departure_quality(departure: dict | None) -> float:
    if not departure:
        return 0.0
    score = 0.0
    reason = departure.get("reason")
    if reason:
        score += 0.5
    if departure.get("death_date") or departure.get("departure_date"):
        score += 0.5
    if departure.get("act_record_number"):
        score += 0.9
        if len(str(departure.get("act_record_number"))) >= 21:
            score += 0.4
    if departure.get("act_record_date"):
        score += 0.4
    if departure.get("issued_by") or departure.get("destination_address"):
        score += 0.5
    validation = departure.get("validation") or {}
    if validation.get("passed") is True:
        score += 0.5
    return score
