from egd_parser.domain.models.ocr import OCRPageResult


def extract_page1_header(ocr_results: list[OCRPageResult]) -> dict:
    return {
        "document_type": "egd",
        "ocr_pages": len(ocr_results),
    }
