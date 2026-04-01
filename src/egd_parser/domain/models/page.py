from dataclasses import dataclass


@dataclass(slots=True)
class PageImage:
    number: int
    width: int = 0
    height: int = 0
    image_path: str | None = None
    source_pdf: str | None = None
