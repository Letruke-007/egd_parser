from __future__ import annotations

import re


DATE_RE = re.compile(r"\d{2}\.\d{2}\.\d{4}")
PATRONYMIC_AFTER_DATE_RE = re.compile(
    r"\d{2}\.\d{2}\.\d{4}.*?\b([А-ЯЁ][а-яё-]*(?:ич|вич|ович|евич|ична|овна|евна|кызы))\b",
    re.IGNORECASE,
)
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
}

MIXED_NAME_LOOKALIKE_MAP = str.maketrans(
    {
        "A": "А",
        "a": "а",
        "B": "В",
        "C": "С",
        "c": "с",
        "E": "Е",
        "e": "е",
        "H": "Н",
        "I": "І",
        "i": "и",
        "K": "К",
        "M": "М",
        "O": "О",
        "o": "о",
        "P": "Р",
        "p": "р",
        "R": "Р",
        "r": "р",
        "T": "Т",
        "V": "В",
        "v": "в",
        "X": "Х",
        "x": "х",
        "Y": "У",
        "y": "у",
    }
)


def group_words_into_lines(words: list, tolerance: int = 18) -> list[list]:
    lines: list[list] = []
    for word in sorted(words, key=lambda item: (item.bbox.top, item.bbox.left)):
        if not lines:
            lines.append([word])
            continue
        current_top = min(item.bbox.top for item in lines[-1])
        if abs(word.bbox.top - current_top) <= tolerance:
            lines[-1].append(word)
        else:
            lines.append([word])
    return lines


def normalize_name_token_fragment(value: str) -> str:
    if not re.search(r"[A-Za-z]", value):
        return value
    if re.search(r"[А-Яа-яЁё]", value):
        return value.translate(MIXED_NAME_LOOKALIKE_MAP)

    compact = re.sub(r"[^A-Za-z-]", "", value)
    if not compact or len(compact) > 4 or not compact[:1].isupper():
        return value
    return value.translate(MIXED_NAME_LOOKALIKE_MAP)


def normalize_name_text(value: str) -> str:
    return re.sub(
        r"[A-Za-zА-Яа-яЁё-]+",
        lambda match: normalize_name_token_fragment(match.group(0)),
        value,
    )


def extract_name_and_birthday_from_words(words: list) -> tuple[str | None, str | None]:
    ordered_words = sorted(words, key=lambda item: (item.bbox.top, item.bbox.left))
    joined = normalize_name_text(" ".join(word.text for word in ordered_words))
    birthday_match = DATE_RE.search(joined)
    birthday_date = birthday_match.group(0) if birthday_match else None
    if not birthday_match:
        return None, None

    birthday_anchor = next((word for word in ordered_words if DATE_RE.search(word.text)), None)
    positional_tokens = extract_name_tokens_left_of_birthday(ordered_words, birthday_anchor)
    if len(positional_tokens) >= 3:
        return " ".join(positional_tokens[:3]), birthday_date

    before_date = joined[: birthday_match.start()]
    after_date = joined[birthday_match.end() :]

    prefix_tokens = [
        token
        for token in merge_split_name_parts(re.findall(r"[А-ЯЁа-яё-]+", before_date))
        if token[:1].isupper() and token not in NAME_STOP_WORDS and len(token.strip("-")) >= 2
    ]
    suffix_tokens = [
        token
        for token in merge_split_name_parts(re.findall(r"[А-ЯЁа-яё-]+", after_date))
        if token not in NAME_STOP_WORDS
    ]

    surname = prefix_tokens[0] if prefix_tokens else None
    name = prefix_tokens[1] if len(prefix_tokens) > 1 else None
    patronymic = next((token for token in suffix_tokens if is_patronymic(token)), None)

    if name and name.endswith("-"):
        continuation = next((token for token in suffix_tokens if token.islower()), None)
        if continuation:
            name = f"{name[:-1]}{continuation}"
        else:
            name = name.rstrip("-")

    if name is None and len(prefix_tokens) > 1:
        name = prefix_tokens[1]

    if surname is None and len(suffix_tokens) >= 3:
        surname, name, patronymic = suffix_tokens[:3]
    elif surname is not None and patronymic is None:
        fallback_tokens = extract_name_tokens_from_words(ordered_words)
        if len(fallback_tokens) >= 3:
            surname, name, patronymic = fallback_tokens[:3]

    full_name = " ".join(part for part in (surname, name, patronymic) if part) or None
    return full_name, birthday_date


def is_patronymic(value: str) -> bool:
    lowered = value.lower()
    return lowered.endswith(("ич", "вич", "ович", "евич", "ична", "овна", "евна", "кызы"))


def merge_split_name_parts(tokens: list[str]) -> list[str]:
    merged: list[str] = []
    index = 0
    while index < len(tokens):
        token = normalize_name_token_fragment(tokens[index])
        if token.endswith("-") and index + 1 < len(tokens):
            continuation = normalize_name_token_fragment(tokens[index + 1])
            merged.append(f"{token[:-1]}{continuation.lower()}")
            index += 2
            continue
        merged.append(token)
        index += 1
    return merged


def extract_name_tokens_from_words(words: list) -> list[str]:
    raw_tokens: list[str] = []
    for word in words:
        if word.bbox.left >= 650:
            continue
        normalized = normalize_name_text(word.text)
        for token in re.findall(r"[А-ЯЁа-яё-]+", normalized):
            raw_tokens.append(token)
    merged = merge_split_name_parts(raw_tokens)
    return [
        token
        for token in merged
        if token[:1].isupper() and token not in NAME_STOP_WORDS and len(token.strip("-")) >= 2
    ]


def extract_name_tokens_left_of_birthday(words: list, birthday_anchor) -> list[str]:
    if birthday_anchor is None:
        return []

    max_left = max(0, birthday_anchor.bbox.left - 20)
    positional_words = [
        word
        for word in words
        if not DATE_RE.search(word.text)
        and word.bbox.left < max_left
    ]
    return extract_name_tokens_from_words(positional_words)


def extract_patronymic(chunk: str, start_index: int) -> str | None:
    del start_index
    match = PATRONYMIC_AFTER_DATE_RE.search(chunk)
    if not match:
        return None
    return match.group(1)
