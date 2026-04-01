from egd_parser.domain.models.ocr import OCRPageResult
from egd_parser.pipeline.extractors.page2_core import extract_benefits


def extract_page2_benefits(resident_pages: list[OCRPageResult], all_pages: list[OCRPageResult]) -> str | None:
    joined_text = "\n".join(page.text for page in resident_pages)
    full_document_text = "\n".join(page.text for page in all_pages)
    return extract_benefits(joined_text) or extract_benefits(full_document_text)
