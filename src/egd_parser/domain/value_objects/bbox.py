from dataclasses import dataclass


@dataclass(slots=True)
class BoundingBox:
    left: int
    top: int
    width: int
    height: int
