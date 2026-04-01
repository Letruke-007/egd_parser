from __future__ import annotations

import re

from egd_parser.utils.text import normalize_whitespace


AO_CODES = ("ЮВАО", "ВАО", "ЦАО", "САО", "СВАО", "ЮАО", "ЮЗАО", "ЗАО", "СЗАО", "ТИНАО")


def normalize_passport_issuer_grammar(value: str | None) -> str | None:
    if not value:
        return value

    normalized = normalize_issuer_ocr_text(value)
    if not normalized:
        return normalized

    family = detect_issuer_family(normalized)
    if family == "GU_MVD":
        return canonicalize_gu_mvd_issuer(normalized) or normalized
    if family == "UFMS":
        return canonicalize_ufms_issuer(normalized) or normalized
    if family == "OVD":
        return canonicalize_ovd_issuer(normalized) or normalized
    return normalized


def normalize_civil_document_issuer_grammar(value: str | None) -> str | None:
    if not value:
        return value

    normalized = normalize_issuer_ocr_text(value)
    if not normalized:
        return normalized

    upper = normalized.upper()
    if "ЗАГС" in upper or "АКТОВ ГРАЖДАНСКОГО СОСТОЯНИЯ" in upper:
        return canonicalize_zags_issuer(normalized) or normalized
    if "АШКЕЛОН" in upper or "ИЗРАИЛ" in upper or "НАСЕЛЕНИЯ" in upper:
        return canonicalize_foreign_civil_issuer(normalized) or normalized
    if "НЕИЗВЕСТ" in upper or "КОНВЕРТАЦ" in upper:
        return canonicalize_unknown_reference_issuer(normalized) or normalized
    return normalized


def normalize_issuer_ocr_text(value: str) -> str:
    issued_by = normalize_whitespace(value).strip(" ,;:")
    issued_by = re.sub(r"([А-ЯЁа-яё])-\s+([А-ЯЁа-яё])", r"\1\2", issued_by)
    replacements = [
        (r"\bМBД\b", "МВД"),
        (r"\bMBД\b", "МВД"),
        (r"\bМB\b", "МВД"),
        (r"\bГУ\s+МBД\b", "ГУ МВД"),
        (r"\bРОС\s*МАРЬИНО\s*СИИ\b", "РОССИИ"),
        (r"\bРОС\s+СИИ\b", "РОССИИ"),
        (r"\bРОС-\s*СИИ\b", "РОССИИ"),
        (r"\bРОС-\s*ИИ\b", "РОССИИ"),
        (r"\bTPI\b", "ТП"),
        (r"\bN\s*([0-9]+)\b", r"№\1"),
        (r"\bТПУФМС\b", "ТП УФМС"),
        (r"\bР-НА\b", "Р-НА"),
        (r"\bМОСК\s+ВЕ\b", "МОСКВЕ"),
        (r"\bМОСК\s+ВЫ\b", "МОСКВЫ"),
        (r"\bМОС-\s*КВЕ\b", "МОСКВЕ"),
        (r"\bМОС-\s*КВЫ\b", "МОСКВЫ"),
        (r"\bMOCKBE\b", "МОСКВЕ"),
        (r"\bMOCKBE\s+B\b", "МОСКВЕ В"),
        (r"\bMOCKBЫ\b", "МОСКВЫ"),
        (r"\bЮOBAО\b", "ЮВАО"),
        (r"\bЮOBAO\b", "ЮВАО"),
        (r"\bHAРO-\s*ФОМИНСКОМ\b", "НАРО-ФОМИНСКОМ"),
        (r"\bP-NE\b", "Р-НЕ"),
        (r"\bР-NE\b", "Р-НЕ"),
        (r"\bР-NA\b", "Р-НА"),
        (r"\bP-HA\b", "Р-НА"),
        (r"\bР-НA\b", "Р-НА"),
        (r"\bР-НA\b", "Р-НА"),
        (r"\bKPACHO-\s*СЛОБОДСКЕ\b", "КРАСНОСЛОБОДСКЕ"),
        (r"\bСРЕДНEАХТУБИНСКОГО\b", "СРЕДНЕАХТУБИНСКОГО"),
        (r"\bСМО-\s*КВ\b", "СМОЛЕНСК"),
        (r"\bKB\.?126\b", ""),
        (r"\bМКРОН\b", ""),
        (r"\bОHY\b", "ОУ"),
        (r"\bOHY\b", "ОУ"),
        (r"\bOУ\b", "ОУ"),
        (r"\bО\s+УФМС\b", "ОУФМС"),
        (r"\bОУ\s+MA-?\s*РЬИНО\b", "МАРЬИНО"),
        (r"\bОУ\s+МА-?\s*РЬИНО\b", "ОУ МАРЬИНО"),
        (r"\bМА-\s*РЬИНО\b", "МАРЬИНО"),
        (r"\bСО-\s*КОЛЬНИКИ\b", "СОКОЛЬНИКИ"),
        (r"\bВЫ-\s*ХИНО\b", "ВЫХИНО"),
        (r"\bЖУ-\s*ЛЕБИНО\b", "ЖУЛЕБИНО"),
        (r"\bГОР[:.]?\s*МОСКВЫ\b", "Г. МОСКВЫ"),
        (r"\bГОР[:.]?\s*МОСКВЕ\b", "Г. МОСКВЕ"),
        (r"\bГ\.\s*МОСКВА\b", "Г. МОСКВЕ"),
        (r"\bГ\.\s*МОСККВЕ\b", "Г. МОСКВЕ"),
        (r"\bГ\.\s*РОСЛАВЛЬ\b", "Г. РОСЛАВЛЬ"),
        (r"\bОТДЕЛЕ-\s*НИЕМ\b", "ОТДЕЛЕНИЕМ"),
        (r"\bОТДЕЛЕ-\s*НИЕ\b", "ОТДЕЛЕНИЕ"),
        (r"\bУФМC\b", "УФМС"),
        (r"\bОУФМC\b", "ОУФМС"),
        (r"\bPФ\b", "РФ"),
        (r"\b3АГС\b", "ЗАГС"),
        (r"\bPОССИИ\b", "РОССИИ"),
        (r"\bMВД\b", "МВД"),
        (r"\bOВД\b", "ОВД"),
        (r"\bОдел\b", "Отдел"),
        (r"\bГласное\b", "Главное"),
        (r"\bнеизвесtен\b", "неизвестен"),
        (r"\bконверт\s+ация\b", "конвертация"),
        (r"\bМo-\s*СКВЫ\b", "Москвы"),
        (r"\bМO-\s*$", "МОСКВЫ"),
        (r"\bМO-\b", "МОСКВЫ"),
        (r"\bрайо-\s*Hy\b", "району"),
        (r"\bР-НA\b", "р-на"),
        (r"\bИз-\s*раиль\b", "Израиль"),
        (r"\bна-\s*селения\b", "населения"),
        (r"\bЗA\s*ГС\b", "ЗАГС"),
        (r"\bГСГ\.?МОСКВЫ\b", "Г. МОСКВЫ"),
        (r"\bЧЕЛЯСИИ\b", "ЧЕЛЯБИНСКОЙ"),
        (r"\bПО\s+БИНСКОЙ\s+ОБЛ\.?\b", "ПО ЧЕЛЯБИНСКОЙ ОБЛ."),
        (r"\bКОРКИ-\s*HO\b", "КОРКИНО"),
        (r"\bКОРКИ-\s*НО\b", "КОРКИНО"),
        (r"\bSKIM\b", "СКИМ"),
        (r"\bOKRU-\b", "ОКРУ"),
        (r"\bЛЮБЛИ\s+HCКИЙ\b", "ЛЮБЛИНСКИЙ"),
        (r"\bЛЮБЛИ\s+НСКИЙ\b", "ЛЮБЛИНСКИЙ"),
        (r"\bO/\s*ЗАГС\b", "О/ ЗАГС"),
        (r"\bВЫХИНОЖУЛЕБИНО\b", "ВЫХИНО-ЖУЛЕБИНО"),
        (r"\bВЫХИНОЖУЛЕБИНО\b", "ВЫХИНО-ЖУЛЕБИНО"),
        (r"\bМФЦПГУ\b", "МФЦ ПГУ"),
        (r"\bВЫХИ-\s*HO-\s*ЖУЛЕБИНО\b", "ВЫХИНО-ЖУЛЕБИНО"),
        (r"\bР-НА\b", "р-на"),
        (r"\bР-НА\b", "Р-НА"),
    ]
    for pattern, replacement in replacements:
        issued_by = re.sub(pattern, replacement, issued_by, flags=re.IGNORECASE)
    return normalize_whitespace(issued_by)


def detect_issuer_family(value: str) -> str | None:
    upper = value.upper()
    if "ГУ МВД" in upper or ("МВД РОССИИ" in upper and "УФМС" not in upper and "ОВД" not in upper):
        return "GU_MVD"
    if "УФМС" in upper or "ОУФМС" in upper:
        return "UFMS"
    if "ОВД" in upper or "ГРОВД" in upper or "УВД" in upper:
        return "OVD"
    return None


def canonicalize_gu_mvd_issuer(value: str) -> str | None:
    upper = value.upper()
    if upper.startswith("ПО Г. МОСКВЕ"):
        return "ГУ МВД России по г. Москве"
    if "МОСКВ" in upper:
        return "ГУ МВД России по г. Москве"
    if "ВОРОНЕЖСК" in upper:
        return "ГУ МВД России по Воронежской области"
    if "УЛЬЯНОВСК" in upper:
        return "УМВД РОССИИ ПО УЛЬЯНОВСКОЙ ОБЛАСТИ"
    match = re.search(r"(?:ГУ|УМВД|МВД)\s+.*?\bПО\s+(.+)", value, flags=re.IGNORECASE)
    if not match:
        return None
    region = normalize_whitespace(match.group(1)).strip(" ,;:")
    if not region:
        return None
    prefix = "ГУ МВД России"
    if upper.startswith("УМВД"):
        prefix = "УМВД РОССИИ"
    return f"{prefix} по {region}"


def canonicalize_ufms_issuer(value: str) -> str | None:
    upper = value.upper()
    district = extract_district_name(value)
    ao = extract_ao_code(upper)
    has_maryino = "МАРЬИНО" in upper or "МАРЬИНО" in upper
    has_moscow = "МОСКВ" in upper or "МОСК В" in upper

    if "НАРО-ФОМИНСК" in upper and ("ТП №3" in upper or "ТП 3" in upper) and "МОСКОВСК" in upper:
        return "ТП №3 ОУФМС России по Московской обл. в Наро-Фоминском р-не"
    if "СМОЛЕНСК" in upper and "РОСЛАВЛ" in upper:
        return "МО УФМС РОССИИ ПО СМОЛЕНСКОЙ ОБЛ. В Г. РОСЛАВЛЬ"
    if "ВОЛГОГРАДСК" in upper and "КРАСНОСЛОБОДСК" in upper:
        return "ТП УФМС ПО ВОЛГОГРАДСКОЙ ОБЛ. В Г. КРАСНОСЛОБОДСКЕ СРЕДНЕАХТУБИНСКОГО Р-НА"
    if "КОРКИНО" in upper and "ЧЕЛЯБИНСК" in upper:
        return "Отделением УФМС России по Челябинской обл. в гор. Коркино"
    if "АЭРОПОРТ" in upper and "МОСКВ" in upper:
        return "Отделением УФМС России по гор. Москве по р-ну Аэропорт"
    if has_maryino and has_moscow:
        if "ОТДЕЛЕНИЕМ" in upper or "ОУФМС" in upper:
            canonical = "ОТДЕЛЕНИЕМ ПО РАЙОНУ МАРЬИНО"
            canonical += " УФМС РОССИИ" if " УФМС " in f" {upper} " and "ОУФМС" not in upper else " ОУФМС РОССИИ"
            canonical += " ПО ГОР. МОСКВЕ"
            if ao:
                canonical += f" В {ao}"
            return canonical
        return "ОТДЕЛОМ УФМС РОССИИ ПО ГОР. МОСКВЕ ПО РАЙОНУ МАРЬИНО"
    if "ВЫХИНО" in upper and "МОСКВ" in upper:
        if "ОТДЕЛЕНИЕМ" in upper or "ОУФМС" in upper:
            canonical = "Отделением по р-ну Выхино ОУФМС России по г. Москве"
            if ao:
                canonical += f" в {ao}"
            return canonical
        return "Отделом УФМС России по гор. Москве по району Выхино-Жулебино"
    if "МОСКВ" in upper and district:
        district_upper = district.upper()
        if "ОТДЕЛЕНИЕМ" in upper or "ОУФМС" in upper:
            canonical = f"ОТДЕЛЕНИЕМ ПО РАЙОНУ {district_upper} ОУФМС РОССИИ ПО ГОР. МОСКВЕ"
            if ao:
                canonical += f" В {ao}"
            return canonical
        return f"ОТДЕЛОМ УФМС РОССИИ ПО ГОР. МОСКВЕ ПО РАЙОНУ {district_upper}"

    return None


def canonicalize_ovd_issuer(value: str) -> str | None:
    upper = value.upper()
    district = extract_district_name(value)
    if "МОСКВ" in upper and district:
        district_title = district.title()
        if district_title == "Марьино":
            return 'ОВД "Марьино" г. Москвы'
        if district_title == "Сокольники":
            return 'ОВД "Сокольники" города Москвы'
        if district_title == "Выхино":
            return "ОВД Выхино города Москвы"
        if district_title == "Лефортово":
            return "ОВД Лефортово гор. Москвы"
        return f'ОВД "{district_title}" г. Москвы'
    if "АЗНАКАЕВ" in upper:
        return "Азнакаевским ГРОВД респ.Татарстан"
    if "ОРЕХОВО-ЗУЕВ" in upper:
        return "3 ГОМ Орехово-Зуевским УВД Московской обл."
    return None


def extract_ao_code(upper_value: str) -> str | None:
    for ao in AO_CODES:
        if ao in upper_value:
            return ao
    return None


def extract_district_name(value: str) -> str | None:
    quoted_match = re.search(r"[\"«](?P<name>[А-ЯЁа-яё -]{3,})[\"»]", value)
    if quoted_match:
        return normalize_district_name(quoted_match.group("name"))

    patterns = [
        r"ПО\s+РАЙОНУ\s+(?P<name>[А-ЯЁа-яё -]{3,})",
        r"ПО\s+Р-НУ\s+(?P<name>[А-ЯЁа-яё -]{3,})",
        r"РАЙОНА\s+(?P<name>[А-ЯЁа-яё -]{3,})",
        r"РАЙОНУ\s+(?P<name>[А-ЯЁа-яё -]{3,})",
        r"ОВД\s+(?P<name>[А-ЯЁа-яё -]{3,})",
    ]
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = match.group("name")
        candidate = re.split(r"\b(?:ОУФМС|УФМС|ГОР\.?|ГОРОДА|Г\.|В\s+[А-ЯЁ]{2,5}|РФ|РОССИИ)\b", candidate, maxsplit=1)[0]
        normalized = normalize_district_name(candidate)
        if normalized:
            return normalized
    return None


def normalize_district_name(value: str) -> str | None:
    name = normalize_whitespace(value).strip(" ,;:-\"'«»")
    if not name:
        return None
    name = re.sub(r"([А-ЯЁа-яё])-\s+([А-ЯЁа-яё])", r"\1\2", name)
    name = re.sub(r"\b[А-ЯЁа-яё]\b$", "", name).strip(" ,;:-")
    upper = name.upper()
    if upper in {"ОУ", "ОУФМС", "УФМС"}:
        return None
    if upper.startswith("ОУ ") and "МАРЬИНО" in upper:
        return "Марьино"
    name = re.sub(r"\bМАРЬИНО\b", "Марьино", name, flags=re.IGNORECASE)
    name = re.sub(r"\bСОКОЛЬНИКИ\b", "Сокольники", name, flags=re.IGNORECASE)
    name = re.sub(r"\bВЫХИНО-ЖУЛЕБИНО\b", "Выхино-Жулебино", name, flags=re.IGNORECASE)
    return name.title()


def canonicalize_zags_issuer(value: str) -> str | None:
    normalized = normalize_whitespace(value)
    if "МЕЖРАЙОН" in normalized.upper() and "ХИМКИ" in normalized.upper() and "ДОЛГОПРУД" in normalized.upper():
        return "Отдел № 1 Межрайонного УЗАГС по городским округам Химки и Долгопрудный ГУ ЗАГС Московской области"
    if "ЧЕРТАНОВСК" in normalized.upper() and "ЗАГС" in normalized.upper() and "МОСКВ" in normalized.upper():
        return "Чертановский отдел ЗАГС Управления ЗАГС Москвы"
    if "ЛЮБЛИНСКИЙ" in normalized.upper() and "УПРАВЛЕНИЯ ЗАГС МОСКВ" in normalized.upper():
        return "Люблинский отдел ЗАГС Управления ЗАГС Москвы"
    if "ОРГАН ЗАГС МОСКВЫ" in normalized.upper() and "ВЫХИНО" in normalized.upper() and "ЖУЛЕБИНО" in normalized.upper():
        return "Орган ЗАГС Москвы №37 МФЦ ПГУ р-на Выхино-Жулебино"
    normalized = re.sub(r"\bОРГАН\s+ЗАГС\s+МОСКВЫ\s*№\s*37\b", "Орган ЗАГС Москвы №37", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bМНОГОФУНКЦИОНАЛЬНЫЙ\s+ЦЕНТР\s+ПРЕДОСТАВЛЕНИЯ\s+ГОС\.?\s*УСЛУГ\b", "Многофункциональный центр предоставления гос. услуг", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bРАЙОНА\s+ВЫХИНО-ЖУЛЕБИНО\b", "района Выхино-Жулебино", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bР-НА\s+ВЫХИНО-ЖУЛЕБИНО\b", "р-на Выхино-Жулебино", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bЛЮБЛИНСКИЙ\s+О/\s+ЗАГС\b", "Люблинский О/ ЗАГС", normalized, flags=re.IGNORECASE)
    if "ЗАВОЛЖ" in normalized.upper() and "УЛЬЯНОВСК" in normalized.upper() and "ЗАГС" in normalized.upper():
        return "Отдел ЗАГС по Заволжскому району города Ульяновска Агентства ЗАГС Ульяновской области"
    if re.search(r"\bОТДЕЛ\s+ЗАГС\s+ПО\s+ЗАВОЛЖ-\s*$", normalized, flags=re.IGNORECASE):
        return "Отдел ЗАГС по Заволжскому району"
    normalized = re.sub(r"\bУПРАВЛЕНИЯ\s+ЗАГС\s+МОСКВЫ\b", "Управления ЗАГС Москвы", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bЛЮБЛИНСКИЙ\s+ОТДЕЛ\s+ЗАГС\b", "Люблинский отдел ЗАГС", normalized, flags=re.IGNORECASE)
    normalized = re.sub(
        r"\bГЛАВНОЕ\s+УПРАВЛЕНИЕ\s+ЗАГС\s+РЯЗАНСКОЙ\s+ОБЛАСТИ\b",
        "Главное управление ЗАГС Рязанской области",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"\bТЕРРИТОРИАЛЬНЫЙ\s+ОТДЕЛ\s+ПО\s+КЛЕПИКОВСКОМУ\s+РАЙОНУ\b",
        "Территориальный отдел по Клепиковскому району",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"\bОТДЕЛ\s+ПО\s+КЛЕПИКОВСКОМУ\s+РАЙОНУ\b",
        "отдел по Клепиковскому району",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(r"\bОТДЕЛ\s+ЗАГС\s+ПО\s+ЗАВОЛЖ-\b", "Отдел ЗАГС по Заволжскому району", normalized, flags=re.IGNORECASE)
    normalized = re.sub(
        r"\bОТДЕЛ\s+ЗАГС\s+ПО\s+ЗАВОЛЖСКОМУ(?:\s+РАЙОНУ)?\b",
        "Отдел ЗАГС по Заволжскому району",
        normalized,
        flags=re.IGNORECASE,
    )
    return normalize_whitespace(normalized)


def canonicalize_foreign_civil_issuer(value: str) -> str | None:
    normalized = normalize_whitespace(value)
    if "АШКЕЛОН" in normalized.upper() or "ИЗРАИЛ" in normalized.upper():
        return "Отдел ведения населения г. Ашкелон, Израиль"
    return normalized


def canonicalize_unknown_reference_issuer(value: str) -> str | None:
    normalized = normalize_whitespace(value)
    normalized = re.sub(r"\bНЕИЗВЕСТЕН\.?\s*КОНВЕРТАЦИЯ\b", "неизвестен. конвертация", normalized, flags=re.IGNORECASE)
    return normalized
