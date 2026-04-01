from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


RULES_DIR = Path(__file__).resolve().parents[2] / "domain" / "reference" / "rules"


@lru_cache(maxsize=None)
def load_rule_file(filename: str) -> Any:
    with (RULES_DIR / filename).open(encoding="utf-8") as file:
        return json.load(file)


def get_name_prefix_fixes() -> dict[str, str]:
    return dict(load_rule_file("name_prefix_fixes.json"))


def get_patronymic_fixes() -> dict[str, dict[str, str]]:
    return dict(load_rule_file("patronymic_fixes.json"))


def get_passport_raw_replacements() -> list[dict[str, str]]:
    return list(load_rule_file("passport_raw_replacements.json"))


def get_passport_raw_regex_replacements() -> list[dict[str, str | list[str]]]:
    return list(load_rule_file("passport_raw_regex_replacements.json"))


def get_issuer_pattern_rules() -> list[dict[str, str | list[str]]]:
    return list(load_rule_file("issuer_pattern_rules.json"))


def get_ownership_document_replacements() -> list[dict[str, str]]:
    return list(load_rule_file("ownership_document_replacements.json"))


def get_ownership_document_text_replacements() -> list[dict[str, str]]:
    return list(load_rule_file("ownership_document_text_replacements.json"))


def get_ownership_document_text_regex_replacements() -> list[dict[str, str | list[str]]]:
    return list(load_rule_file("ownership_document_text_regex_replacements.json"))
