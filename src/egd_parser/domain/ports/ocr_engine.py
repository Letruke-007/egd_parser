from abc import ABC, abstractmethod

from egd_parser.domain.models.ocr import OCRPageResult
from egd_parser.domain.models.page import PageImage


class OCREngine(ABC):
    @abstractmethod
    def recognize(self, pages: list[PageImage]) -> list[OCRPageResult]:
        raise NotImplementedError
