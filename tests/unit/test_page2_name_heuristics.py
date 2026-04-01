from egd_parser.domain.models.ocr import OCRWord
from egd_parser.domain.value_objects.bbox import BoundingBox
from egd_parser.pipeline.extractors.page2_names import (
    extract_name_and_birthday_from_words,
    merge_split_name_parts,
    normalize_name_text,
    normalize_name_token_fragment,
)
from egd_parser.pipeline.extractors.page2_core import parse_resident_row_words
from egd_parser.pipeline.extractors.page2_table import extract_name_from_name_column


def make_word(text: str, left: int, top: int, width: int = 120, height: int = 24) -> OCRWord:
    return OCRWord(
        text=text,
        confidence=0.99,
        bbox=BoundingBox(left=left, top=top, width=width, height=height),
    )


def test_normalize_name_token_fragment_handles_mixed_script_patronymic() -> None:
    assert normalize_name_token_fragment("Дмiтrиevич") == "Дмитриевич"


def test_normalize_name_token_fragment_handles_short_latin_tail() -> None:
    assert normalize_name_token_fragment("Ha") == "На"


def test_normalize_name_token_fragment_keeps_long_pure_latin_words() -> None:
    assert normalize_name_token_fragment("Moscow") == "Moscow"


def test_normalize_name_text_repairs_mixed_name_text() -> None:
    assert normalize_name_text("Кукса Максим Дмiтrиevич") == "Кукса Максим Дмитриевич"


def test_merge_split_name_parts_repairs_hyphenated_patronymic_tail() -> None:
    assert merge_split_name_parts(["Николаев-", "Ha"]) == ["Николаевна"]


def test_extract_name_from_name_column_restores_mixed_script_patronymic() -> None:
    words = [
        make_word("Кукса", left=120, top=100),
        make_word("Максим", left=260, top=100),
        make_word("Дмiтrиevич", left=120, top=136, width=180),
    ]

    assert extract_name_from_name_column(words) == "Кукса Максим Дмитриевич"


def test_extract_name_from_name_column_restores_split_name_and_patronymic() -> None:
    words = [
        make_word("Максимова", left=120, top=100, width=170),
        make_word("Све-", left=320, top=100, width=90),
        make_word("тлана", left=120, top=136, width=110),
        make_word("Николаев-", left=250, top=136, width=170),
        make_word("Ha", left=120, top=172, width=60),
    ]

    assert extract_name_from_name_column(words) == "Максимова Светлана Николаевна"


def test_parse_resident_row_words_ignores_birth_place_word_from_next_column() -> None:
    row_words = [
        make_word("Авдонян", left=120, top=100, width=160),
        make_word("Анна", left=310, top=100, width=110),
        make_word("Альбертовна", left=120, top=136, width=220),
        make_word("04.11.1970", left=520, top=100, width=150),
        make_word("Баку", left=710, top=94, width=100),
    ]

    person = parse_resident_row_words(row_words, page_number=2)

    assert person["full_name"] == "Авдонян Анна Альбертовна"
    assert person["birthday_date"] == "04.11.1970"


def test_extract_name_and_birthday_from_words_ignores_birth_place_after_date() -> None:
    words = [
        make_word("04.11.1970", left=520, top=100, width=150),
        make_word("Баку", left=720, top=100, width=100),
        make_word("Авдонян", left=120, top=108, width=160),
        make_word("Анна", left=310, top=108, width=110),
        make_word("Альбертовна", left=120, top=144, width=220),
    ]

    full_name, birthday_date = extract_name_and_birthday_from_words(words)

    assert full_name == "Авдонян Анна Альбертовна"
    assert birthday_date == "04.11.1970"
