from dataclasses import dataclass, field

from egd_parser.domain.models.page import PageImage


@dataclass(slots=True)
class ParsedDocument:
    filename: str
    page_count: int
    pages: list[PageImage] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    extracted_data: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
