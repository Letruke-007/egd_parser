from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ManagedBuilding:
    full_address: str
    street: str
    house: str
    building: str | None
    area_sq_m: str
    management_start_date: str


MANAGED_BUILDINGS = [
    ManagedBuilding("г. Москва, ул. Донецкая, д. 1", "ул. Донецкая", "1", None, "17412.20", "01.04.2011"),
    ManagedBuilding("г. Москва, ул. Донецкая, д. 10, к. 1", "ул. Донецкая", "10", "1", "7758.30", "01.03.2016"),
    ManagedBuilding("г. Москва, ул. Донецкая, д. 22", "ул. Донецкая", "22", None, "14162.80", "01.04.2011"),
    ManagedBuilding("г. Москва, Луговой пр-д., д. 12, к. 2", "Луговой пр-д.", "12", "2", "11177.50", "01.07.2023"),
    ManagedBuilding("г. Москва, Люблинская ул., д. 165", "Люблинская ул.", "165", None, "10515.40", "на содержании"),
    ManagedBuilding("г. Москва, ул. Маршала Голованова, д. 2", "ул. Маршала Голованова", "2", None, "10609.00", "01.04.2011"),
    ManagedBuilding("г. Москва, ул. Маршала Голованова, д. 4", "ул. Маршала Голованова", "4", None, "10626.00", "01.04.2011"),
    ManagedBuilding("г. Москва, ул. Маршала Голованова, д. 4А", "ул. Маршала Голованова", "4А", None, "10609.00", "01.04.2011"),
    ManagedBuilding("г. Москва, ул. Маршала Голованова, д. 12", "ул. Маршала Голованова", "12", None, "17686.00", "01.04.2011"),
    ManagedBuilding("г. Москва, ул. Маршала Голованова, д. 14", "ул. Маршала Голованова", "14", None, "10608.00", "01.04.2011"),
    ManagedBuilding("г. Москва, ул. Маршала Голованова, д. 20", "ул. Маршала Голованова", "20", None, "10673.90", "01.12.2020"),
    ManagedBuilding("г. Москва, Новочеркасский бульвар, д. 9", "Новочеркасский бульвар", "9", None, "10774.60", "01.04.2011"),
    ManagedBuilding("г. Москва, Новочеркасский бульвар, д. 11", "Новочеркасский бульвар", "11", None, "7312.00", "01.04.2011"),
    ManagedBuilding("г. Москва, Новочеркасский бульвар, д. 15", "Новочеркасский бульвар", "15", None, "10728.00", "01.04.2011"),
    ManagedBuilding("г. Москва, Новочеркасский бульвар, д. 21", "Новочеркасский бульвар", "21", None, "10656.00", "01.04.2011"),
    ManagedBuilding("г. Москва, ул. Перерва, д. 2", "ул. Перерва", "2", None, "5434.00", "01.01.2012"),
    ManagedBuilding("г. Москва, ул. Перерва, д. 4", "ул. Перерва", "4", None, "5425.00", "01.01.2012"),
    ManagedBuilding("г. Москва, ул. Перерва, д. 6", "ул. Перерва", "6", None, "5455.90", "01.01.2012"),
    ManagedBuilding("г. Москва, ул. Перерва, д. 12", "ул. Перерва", "12", None, "13114.00", "01.04.2011"),
    ManagedBuilding("г. Москва, ул. Перерва, д. 14", "ул. Перерва", "14", None, "10269.00", "01.04.2011"),
    ManagedBuilding("г. Москва, ул. Перерва, д. 20", "ул. Перерва", "20", None, "5961.00", "01.04.2011"),
    ManagedBuilding("г. Москва, ул. Подольская, д. 1", "ул. Подольская", "1", None, "14931.00", "01.01.2012"),
    ManagedBuilding("г. Москва, ул. Подольская, д. 17", "ул. Подольская", "17", None, "14846.00", "01.07.2011"),
    ManagedBuilding("г. Москва, ул. Подольская, д. 25", "ул. Подольская", "25", None, "14574.00", "01.07.2011"),
    ManagedBuilding("г. Москва, ул. Подольская, д. 27, к. 1", "ул. Подольская", "27", "1", "6404.00", "01.07.2011"),
    ManagedBuilding("г. Москва, ул. Подольская, д. 31", "ул. Подольская", "31", None, "8245.00", "01.07.2011"),
    ManagedBuilding("г. Москва, ул. Подольская, д. 33", "ул. Подольская", "33", None, "8401.10", "01.07.2011"),
    ManagedBuilding("г. Москва, 2-я Сокольническая ул., д. 6", "2-я Сокольническая ул.", "6", None, "3623.30", "01.09.2024"),
    ManagedBuilding("г. Москва, Короленко ул., д. 1 к. 9", "Короленко ул.", "1", "9", "2537.70", "01.01.2024"),
    ManagedBuilding("г. Москва, Маленковская ул., д. 10", "Маленковская ул.", "10", None, "5323.50", "01.08.2024"),
    ManagedBuilding("г. Москва, Сокольнический вал, д. 24 к. 2", "Сокольнический вал", "24", "2", "12108.30", "01.06.2024"),
    ManagedBuilding("г. Москва, Сокольнический вал, д. 38", "Сокольнический вал", "38", None, "8403.00", "на содержании"),
    ManagedBuilding("г. Москва, Шумкина ул., д. 13", "Шумкина ул.", "13", None, "4488.50", "01.09.2024"),
    ManagedBuilding("г. Москва, Шумкина ул., д. 15", "Шумкина ул.", "15", None, "4308.70", "01.01.2024"),
    ManagedBuilding("г. Москва, Рязанский пр-кт, д. 85 к. 2", "Рязанский пр-кт", "85", "2", "3615.30", "01.08.2024"),
    ManagedBuilding("г. Москва, Рязанский пр-кт, д. 87 к. 1", "Рязанский пр-кт", "87", "1", "3630.90", "01.08.2024"),
]


def canonicalize_building_address_part(value: str) -> str:
    normalized = value.lower().replace("ё", "е")
    normalized = normalized.replace("бульвар", "б-р")
    normalized = normalized.replace("пр-д.", "пр-д")
    normalized = normalized.replace("пр-кт.", "пр-кт")
    normalized = normalized.replace("ул.", "ул")
    normalized = normalized.replace("д.", "д")
    normalized = normalized.replace("к.", "к")
    normalized = re.sub(r"[^0-9a-zа-я\s-]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def find_buildings_by_street(street: str | None) -> list[ManagedBuilding]:
    if not street:
        return []
    street_key = canonicalize_building_address_part(street)
    return [
        building
        for building in MANAGED_BUILDINGS
        if canonicalize_building_address_part(building.street) == street_key
    ]


def find_building_by_address(street: str | None, house: str | None, building: str | None = None) -> ManagedBuilding | None:
    if not street or not house:
        return None
    street_key = canonicalize_building_address_part(street)
    house_key = canonicalize_building_address_part(house)
    building_key = canonicalize_building_address_part(building) if building else None

    for entry in MANAGED_BUILDINGS:
        if canonicalize_building_address_part(entry.street) != street_key:
            continue
        if canonicalize_building_address_part(entry.house) != house_key:
            continue
        if building_key and canonicalize_building_address_part(entry.building or "") != building_key:
            continue
        return entry
    return None
