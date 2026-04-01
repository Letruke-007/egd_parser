from dataclasses import dataclass, field

from egd_parser.domain.value_objects.bbox import BoundingBox


@dataclass(slots=True)
class OCRWord:
    text: str
    confidence: float
    bbox: BoundingBox


@dataclass(slots=True)
class OCRPageResult:
    page_number: int
    text: str = ""
    image_path: str | None = None
    words: list[OCRWord] = field(default_factory=list)
