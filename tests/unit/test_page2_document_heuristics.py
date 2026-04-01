from egd_parser.domain.models.ocr import OCRWord
from egd_parser.domain.value_objects.bbox import BoundingBox
from egd_parser.pipeline.extractors.page2_identity_documents import extract_issued_by_without_marker
from egd_parser.pipeline.extractors.page2_table import (
    extract_current_passport_from_words,
    enrich_passport_continuation,
    merge_identity_document_with_continuation,
    select_leftmost_continuation_cluster,
    select_primary_document_cluster,
)
from egd_parser.pipeline.extractors.page2_passports import normalize_registered_passport
from egd_parser.pipeline.runner import merge_page1_subject_passport


def make_word(text: str, left: int, top: int, width: int = 120, height: int = 24) -> OCRWord:
    return OCRWord(
        text=text,
        confidence=0.99,
        bbox=BoundingBox(left=left, top=top, width=width, height=height),
    )


def test_extract_issued_by_without_marker_recovers_birth_certificate_issuer() -> None:
    raw = "IV-МЮ № 711341 Люблинский отдел ЗАГС Управления ЗАГС Москвы 19.05.2009"
    assert extract_issued_by_without_marker(raw, "19.05.2009") == "Люблинский отдел ЗАГС Управления ЗАГС Москвы"


def test_select_primary_document_cluster_prefers_left_document_column() -> None:
    words = [
        make_word("паспорт", left=1180, top=100, width=120),
        make_word("РФ", left=1310, top=100, width=60),
        make_word("№", left=1180, top=136, width=30),
        make_word("114735", left=1220, top=136, width=120),
        make_word("45", left=1360, top=136, width=50),
        make_word("23", left=1420, top=136, width=50),
        make_word("ГУ", left=1180, top=172, width=50),
        make_word("МВД", left=1240, top=172, width=80),
        make_word("России", left=1330, top=172, width=110),
        make_word("01.09.2022", left=1180, top=208, width=150),
        make_word("паспорт", left=1660, top=100, width=120),
        make_word("РФ", left=1790, top=100, width=60),
        make_word("№", left=1660, top=136, width=30),
        make_word("514299", left=1700, top=136, width=120),
        make_word("45", left=1840, top=136, width=50),
        make_word("23", left=1900, top=136, width=50),
    ]

    selected = select_primary_document_cluster(words)
    selected_text = " ".join(word.text for word in selected)

    assert "114735" in selected_text
    assert "514299" not in selected_text


def test_extract_current_passport_from_words_uses_left_document_cluster() -> None:
    words = [
        make_word("паспорт", left=1180, top=100, width=120),
        make_word("РФ", left=1310, top=100, width=60),
        make_word("№", left=1180, top=136, width=30),
        make_word("114735", left=1220, top=136, width=120),
        make_word("45", left=1360, top=136, width=50),
        make_word("23", left=1420, top=136, width=50),
        make_word("ГУ", left=1180, top=172, width=50),
        make_word("МВД", left=1240, top=172, width=80),
        make_word("России", left=1330, top=172, width=110),
        make_word("по", left=1450, top=172, width=40),
        make_word("г.", left=1500, top=172, width=30),
        make_word("Москве", left=1540, top=172, width=110),
        make_word("01.09.2022", left=1180, top=208, width=150),
        make_word("паспорт", left=1660, top=100, width=120),
        make_word("РФ", left=1790, top=100, width=60),
        make_word("№", left=1660, top=136, width=30),
        make_word("514299", left=1700, top=136, width=120),
        make_word("45", left=1840, top=136, width=50),
        make_word("23", left=1900, top=136, width=50),
    ]

    document = extract_current_passport_from_words(words)

    assert document["number"] == "114735"
    assert document["series"] == "45 23"


def test_merge_page1_subject_passport_prefers_more_complete_applicant_document() -> None:
    page1 = {
        "applicant_name": "Евдокимова Арина Викторовна",
        "passport": {
            "document_type": "свидетельство о рождении",
            "series": "IV-МЮ",
            "number": "711341",
            "issued_by": "Люблинский отдел ЗАГС Управления ЗАГС Москвы",
            "issue_date": "19.05.2009",
            "raw": "свидетельство о рождении № 711341 IV-МЮ, выдан Люблинский отдел ЗАГС Управления ЗАГС Москвы 19.05.2009",
        },
    }
    person = {
        "full_name": "Евдокимова Арина Викторовна",
        "passport": {
            "document_type": "свидетельство о рождении",
            "series": "IV-МЮ",
            "number": "711341",
            "issued_by": "СКВЫ",
            "issue_date": "19.05.2009",
            "raw": "СКВЫ 19.05.2009",
        },
    }

    merged = merge_page1_subject_passport(page1, person)

    assert merged["passport"]["issued_by"] == "Люблинский отдел ЗАГС Управления ЗАГС Москвы"


def test_merge_identity_document_with_continuation_prefers_stronger_passport_candidate() -> None:
    previous = {
        "document_type": "паспорт",
        "series": "45 10",
        "number": "016428",
        "issued_by": "тинская, ОВД РАЙООТДЕЛЕЖарминНА МАРЬИНИЕМ ПО p-н п/o ский RAЙOUV шо гоrо г",
        "issue_date": "18.09.1998",
        "raw": "паспорт РФ № 016428 45 10, выдан тинская ... 18.09.1998",
    }
    continuation = {
        "raw_text": "№ 016428 45 10, выдан ОТДЕЛЕНИЕМ ПО РАЙОНУ МАРЬИНО УФМС РОССИИ ПО ГОР. МОСКВЕ В ЮВАО 09.02.2009",
        "parsed": {
            "document_type": "паспорт",
            "series": "45 10",
            "number": "016428",
            "issued_by": "ОТДЕЛЕНИЕМ ПО РАЙОНУ МАРЬИНО УФМС РОССИИ ПО ГОР. МОСКВЕ В ЮВАО",
            "issue_date": "09.02.2009",
            "raw": "паспорт РФ № 016428 45 10, выдан ОТДЕЛЕНИЕМ ПО РАЙОНУ МАРЬИНО УФМС РОССИИ ПО ГОР. МОСКВЕ В ЮВАО 09.02.2009",
        },
    }

    merged = merge_identity_document_with_continuation(previous, continuation)

    assert merged["issue_date"] == "09.02.2009"
    assert merged["issued_by"] == "ОТДЕЛЕНИЕМ ПО РАЙОНУ МАРЬИНО УФМС РОССИИ ПО ГОР. МОСКВЕ В ЮВАО"


def test_normalize_registered_passport_canonicalizes_recent_gu_mvd_and_tp_ufms_patterns() -> None:
    galyatkina = normalize_registered_passport(
        {
            "document_type": "паспорт",
            "series": "45 21",
            "number": "284954",
            "issued_by": "по г. Москве Люблинский",
            "issue_date": "12.05.2021",
            "raw": "паспорт РФ № 284954 45 21, выдан по г. Москве Люблинский 12.05.2021",
        }
    )
    miro = normalize_registered_passport(
        {
            "document_type": "паспорт",
            "series": "46 12",
            "number": "845251",
            "issued_by": "TPI N3 ОУФМС России по Московской обл. в Haрo- Фоминском p-ne",
            "issue_date": "20.07.2012",
            "raw": "паспорт РФ № 845251 46 12, выдан TPI N3 ОУФМС России по Московской обл. в Haрo- Фоминском p-ne 20.07.2012",
        }
    )

    assert galyatkina["issued_by"] == "ГУ МВД России по г. Москве"
    assert miro["issued_by"] == "ТП №3 ОУФМС России по Московской обл. в Наро-Фоминском р-не"


def test_select_leftmost_continuation_cluster_discards_previous_document_column() -> None:
    words = [
        make_word("Отделом", left=1246, top=471, width=160),
        make_word("УФМС", left=1246, top=525, width=120),
        make_word("по", left=1246, top=579, width=40),
        make_word("району", left=1330, top=579, width=130),
        make_word("Выхино-Жулебино", left=1246, top=633, width=300),
        make_word("26.08.2011", left=1246, top=687, width=180),
        make_word("Отделением", left=1494, top=471, width=210),
        make_word("по", left=1494, top=525, width=40),
        make_word("р-ну", left=1545, top=525, width=70),
        make_word("Выхино", left=1494, top=579, width=130),
        make_word("19.05.2010", left=1494, top=687, width=180),
    ]

    selected = select_leftmost_continuation_cluster(words)
    selected_text = " ".join(word.text for word in selected)

    assert "26.08.2011" in selected_text
    assert "19.05.2010" not in selected_text
    assert "Отделением" not in selected_text


def test_enrich_passport_continuation_prefers_clean_continuation_over_noisy_merged_candidate() -> None:
    previous = {
        "document_type": "паспорт",
        "series": "45 11",
        "number": "386018",
        "issued_by": None,
        "issue_date": None,
    }
    continuation_parsed = {
        "document_type": "паспорт",
        "series": None,
        "number": None,
        "issued_by": "Отделом УФМС России по гор. Москве по району Выхино-Жулебино",
        "issue_date": "26.08.2011",
    }
    merged_parsed = {
        "document_type": "паспорт",
        "series": "45 11",
        "number": "386018",
        "issued_by": "Отделением по р-ну Выхино ОУФМС России по г. Москве в ЮВАО",
        "issue_date": "26.08.2011",
    }

    enriched = enrich_passport_continuation(previous, continuation_parsed, merged_parsed)

    assert enriched["issued_by"] == "Отделом УФМС России по гор. Москве по району Выхино-Жулебино"
    assert enriched["issue_date"] == "26.08.2011"
