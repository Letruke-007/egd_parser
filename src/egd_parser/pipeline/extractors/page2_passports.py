from __future__ import annotations

import re

from egd_parser.pipeline.normalize.rule_registry import (
    get_issuer_pattern_rules,
    get_passport_raw_regex_replacements,
    get_passport_raw_replacements,
)
from egd_parser.pipeline.normalize.issuer_grammar import normalize_passport_issuer_grammar
from egd_parser.utils.text import normalize_whitespace


DATE_RE = re.compile(r"\d{2}\.\d{2}\.\d{4}")


def normalize_passport_raw(value: str) -> str:
    raw = normalize_whitespace(value)
    for rule in get_passport_raw_regex_replacements():
        flags = 0
        for flag_name in rule.get("flags", []):
            flags |= getattr(re, str(flag_name))
        raw = re.sub(
            str(rule["pattern"]),
            str(rule["replacement"]),
            raw,
            count=int(rule.get("count", 0)),
            flags=flags,
        )
    for rule in get_passport_raw_replacements():
        raw = raw.replace(str(rule["old"]), str(rule["new"]))
    return normalize_whitespace(raw).strip(" ,;")


def normalize_registered_passport(passport: dict) -> dict:
    if not passport.get("number"):
        return passport

    issued_by = normalize_registered_issued_by(
        passport.get("issued_by"),
        passport.get("number"),
        passport.get("issue_date"),
    )
    passport["issued_by"] = issued_by
    passport["document_type"] = "паспорт"

    raw_text = passport.get("raw") or ""
    if raw_text:
        from egd_parser.pipeline.extractors.page2_identity_documents import (
            extract_best_passport_series_and_number,
        )

        best_series, best_number = extract_best_passport_series_and_number(
            raw_text,
            issued_by,
            passport.get("issue_date"),
        )
        if best_number == passport.get("number") and best_series:
            passport["series"] = best_series

    if passport.get("number") and passport.get("series") and issued_by and passport.get("issue_date"):
        passport["raw"] = (
            f"паспорт РФ № {passport['number']} {passport['series']}, "
            f"выдан {issued_by} {passport['issue_date']}"
        )
    return passport


def normalize_registered_issued_by(
    value: str | None,
    number: str | None,
    issue_date: str | None,
) -> str | None:
    if not value:
        return value

    normalized = normalize_passport_issuer_grammar(value) or normalize_whitespace(value)
    normalized = normalized.replace("ГОР.", "ГОР.")
    normalized = normalized.replace("г. Москвы", "г. Москве")
    if normalized.lower().startswith("по г. москве"):
        return "ГУ МВД России по г. Москве"
    for rule in get_issuer_pattern_rules():
        contains_all = rule.get("contains_all", [])
        if all(fragment in normalized for fragment in contains_all):
            return str(rule["value"])
    return normalized
