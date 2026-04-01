from abc import ABC, abstractmethod

from egd_parser.domain.models.page import PageImage


class PDFRenderer(ABC):
    @abstractmethod
    def render(self, filename: str, content: bytes) -> list[PageImage]:
        raise NotImplementedError
