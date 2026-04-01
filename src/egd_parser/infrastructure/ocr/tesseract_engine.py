from egd_parser.domain.models.ocr import OCRPageResult
from egd_parser.domain.models.page import PageImage
from egd_parser.domain.ports.ocr_engine import OCREngine


class TesseractOCREngine(OCREngine):
    def recognize(self, pages: list[PageImage]) -> list[OCRPageResult]:
        # Placeholder: next step will call tesseract CLI and map results to OCRPageResult.
        return [OCRPageResult(page_number=page.number) for page in pages]
