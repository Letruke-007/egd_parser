from dataclasses import dataclass, field


@dataclass(slots=True)
class ExtractedFields:
    values: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
