from egd_parser.domain.models.ocr import OCRPageResult
from egd_parser.domain.models.page import PageImage
from egd_parser.domain.ports.ocr_engine import OCREngine


class MockOCREngine(OCREngine):
    def recognize(self, pages: list[PageImage]) -> list[OCRPageResult]:
        return [
            OCRPageResult(page_number=page.number, text="", image_path=page.image_path)
            for page in pages
        ]
