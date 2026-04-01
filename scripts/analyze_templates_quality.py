from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from egd_parser.pipeline.normalize.rule_registry import load_rule_file


NAME_STOP_WORDS = {
    "Россия",
    "Российская",
    "Федерация",
    "Узбекистан",
    "Украина",
    "Москва",
    "Ташкент",
    "Анджелес",
    "Штат",
    "Калифорния",
    "Татарская",
    "Нурлат",
    "Ворошиловград",
    "Алтайского",
    "Барнаул",
    "заявитель",
    "Баку",
    "Ереван",
    "Kamo",
    "Камо",
    "Армения",
}
PATRONYMIC_SUFFIXES = ("ич", "вич", "ович", "евич", "ична", "овна", "евна", "кызы")


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/analyze_templates_quality.py /path/to/templates_parse_cache.json")
        return 1

    cache_path = Path(sys.argv[1])
    rows = json.loads(cache_path.read_text(encoding="utf-8"))
    allowlist = set(load_rule_file("quality_name_allowlist.json"))

    summary = {
        "files": len(rows),
        "ok_files": 0,
        "error_files": 0,
        "persons_total": 0,
        "suspicious_total": 0,
        "missing_patronymic": 0,
        "place_in_name": 0,
        "latin_in_name": 0,
        "digits_in_name": 0,
        "bad_token_count": 0,
        "non_patronymic_third_token": 0,
    }
    issues: list[dict] = []

    for row in rows:
        if row.get("status") != "ok":
            summary["error_files"] += 1
            issues.append(
                {
                    "file": row.get("file"),
                    "role": "parse",
                    "full_name": None,
                    "issues": [f"parse_error:{row.get('error_type')}:{row.get('error')}"],
                }
            )
            continue

        summary["ok_files"] += 1
        data = row.get("data") or {}
        page1 = data.get("page_1", {}) if isinstance(data, dict) else {}
        page2 = data.get("page_2", {}) if isinstance(data, dict) else {}

        persons: list[dict] = []
        for owner in page1.get("owners", []) or []:
            append_person(persons, owner, "owner")
        append_person(persons, page1.get("primary_tenant"), "tenant")
        for resident in page2.get("registered_persons_constantly", {}).get("persons", []) or []:
            append_person(persons, resident, "registered_permanent")

        for person in persons:
            full_name = (person.get("full_name") or "").strip()
            if not full_name:
                continue
            summary["persons_total"] += 1
            if full_name in allowlist:
                continue

            tokens = tokenize_name(full_name)
            person_issues: list[str] = []

            if len(tokens) not in {2, 3}:
                person_issues.append(f"token_count={len(tokens)}")
                summary["bad_token_count"] += 1
            if any(re.search(r"[A-Za-z]", token) for token in tokens):
                person_issues.append("latin_in_name")
                summary["latin_in_name"] += 1
            if any(any(char.isdigit() for char in token) for token in tokens):
                person_issues.append("digits_in_name")
                summary["digits_in_name"] += 1

            place_tokens = sorted({token for token in tokens if token in NAME_STOP_WORDS})
            if place_tokens:
                person_issues.append("place_token=" + ",".join(place_tokens))
                summary["place_in_name"] += 1

            if len(tokens) == 2:
                person_issues.append("missing_patronymic")
                summary["missing_patronymic"] += 1
            if len(tokens) == 3 and not tokens[2].lower().endswith(PATRONYMIC_SUFFIXES):
                person_issues.append("non_patronymic_third_token")
                summary["non_patronymic_third_token"] += 1
            if any(token and not token[:1].isupper() for token in tokens):
                person_issues.append("bad_caps")

            if person_issues:
                summary["suspicious_total"] += 1
                issues.append(
                    {
                        "file": row.get("file"),
                        "role": person.get("role"),
                        "full_name": full_name,
                        "issues": person_issues,
                    }
                )

    report = {"summary": summary, "issues": issues}
    print(json.dumps(report, ensure_ascii=False))
    return 0


def append_person(bucket: list[dict], person: dict | str | None, default_role: str) -> None:
    if not person:
        return
    if isinstance(person, str):
        bucket.append({"role": default_role, "full_name": person})
        return
    if isinstance(person, dict):
        bucket.append({"role": person.get("role") or default_role, "full_name": person.get("full_name")})


def tokenize_name(value: str) -> list[str]:
    return [token.strip(" ,.;:()[]{}\"'") for token in value.split() if token.strip(" ,.;:()[]{}\"'")]


if __name__ == "__main__":
    raise SystemExit(main())
