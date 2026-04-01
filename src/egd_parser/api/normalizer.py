"""Convert EGD ParseResponse to unified parsed_document format."""

from __future__ import annotations
from typing import Any


def _split_name(full_name: str | None) -> dict[str, str | None]:
    if not full_name:
        return {"last_name": None, "first_name": None, "middle_name": None}
    parts = full_name.strip().split()
    return {
        "last_name": parts[0] if len(parts) > 0 else None,
        "first_name": parts[1] if len(parts) > 1 else None,
        "middle_name": parts[2] if len(parts) > 2 else None,
    }


def _normalize_identity(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if not doc or not any(doc.get(k) for k in ("series", "number", "issued_by")):
        return None
    return {
        "document_type": doc.get("document_type"),
        "series": doc.get("series"),
        "number": doc.get("number"),
        "issued_by": doc.get("issued_by"),
        "issue_date": doc.get("issue_date"),
    }


def _normalize_departure(dep: dict[str, Any] | None) -> dict[str, Any] | None:
    if not dep or not dep.get("status"):
        return None
    return {
        "status": dep.get("status"),
        "reason": dep.get("reason"),
        "death_date": dep.get("death_date"),
        "departure_date": dep.get("departure_date"),
    }


def _normalize_persons(data: dict[str, Any]) -> list[dict[str, Any]]:
    persons = []
    page_1 = data.get("page_1", {})
    page_2 = data.get("page_2", {})

    passport = page_1.get("passport", {})
    for i, owner in enumerate(page_1.get("owners", [])):
        person = {
            "role": "owner",
            "full_name": owner.get("full_name"),
            **_split_name(owner.get("full_name")),
            "birthday_date": None,
            "ownership_share": owner.get("ownership_share"),
            "identity": _normalize_identity(passport) if i == 0 else None,
            "departure": None,
        }
        persons.append(person)

    if page_1.get("primary_tenant"):
        persons.append({
            "role": "tenant",
            "full_name": page_1["primary_tenant"],
            **_split_name(page_1["primary_tenant"]),
            "birthday_date": None,
            "ownership_share": None,
            "identity": _normalize_identity(passport) if not page_1.get("owners") else None,
            "departure": None,
        })

    for reg_type, role in [
        ("registered_persons_constantly", "registered_permanent"),
        ("registered_persons_temporary", "registered_temporary"),
    ]:
        block = page_2.get(reg_type, {})
        for p in block.get("persons", []):
            persons.append({
                "role": role,
                "full_name": p.get("full_name"),
                **_split_name(p.get("full_name")),
                "birthday_date": p.get("birthday_date"),
                "ownership_share": None,
                "identity": _normalize_identity(p.get("passport")),
                "departure": _normalize_departure(p.get("departure")),
            })

    return persons


def normalize(response: dict[str, Any]) -> dict[str, Any]:
    """Convert EGD ParseResponse dict to unified parsed_document format."""
    data = response.get("extracted_data", {})
    page_1 = data.get("page_1", {})
    page_2 = data.get("page_2", {})
    address = page_1.get("property_address", {})

    return {
        "document_type": "egd",
        "source_filename": response.get("filename"),
        "address": {
            "raw": address.get("full"),
            "street": address.get("street"),
            "house": address.get("house"),
            "building": address.get("building"),
            "structure": address.get("structure"),
            "apartment": address.get("apartment"),
        },
        "persons": _normalize_persons(data),
        "management_company": (page_1.get("management_company") or {}).get("name"),
        "property_type": page_1.get("settlement_type"),
        "benefits": page_2.get("benefits"),
        "billing": None,
        "administrative_okrug": page_1.get("administrative_okrug"),
        "district": page_1.get("district"),
        "total_area_sq_m": page_1.get("total_area_sq_m"),
        "document_date": page_1.get("document_date"),
        "validations": response.get("metadata", {}).get("extraction_trace"),
        "metadata": {
            "ocr_engine": response.get("metadata", {}).get("ocr_engine"),
            "pages": response.get("pages"),
            "warnings": response.get("warnings"),
            "ownership_documents": page_1.get("ownership_documents"),
        },
    }
