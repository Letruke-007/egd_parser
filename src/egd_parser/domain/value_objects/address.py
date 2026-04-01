from dataclasses import dataclass


@dataclass(slots=True)
class Address:
    raw: str
    street: str | None = None
    house: str | None = None
    building: str | None = None
    apartment: str | None = None
