from egd_parser.pipeline.extractors.page2_residents import (
    annotate_without_registration,
    build_without_registration_trace,
    filter_out_without_registration,
)


def test_annotate_without_registration_detects_marker() -> None:
    block = {
        "count": 1,
        "persons": [
            {
                "full_name": "Шведова Анна Вадимовна",
                "birthday_date": "14.11.1975",
                "__departure_raw_text": "без реги- страции",
            }
        ],
    }

    annotated = annotate_without_registration(block)

    assert annotated["persons"][0]["__registration_status"] == "without_registration"
    assert annotated["persons"][0]["__registration_status_raw"] == "без реги- страции"


def test_without_registration_helpers_filter_public_persons_and_build_trace() -> None:
    persons = [
        {
            "full_name": "Шведова Анна Вадимовна",
            "birthday_date": "14.11.1975",
            "__page_number": 2,
            "__registration_status": "without_registration",
            "__registration_status_raw": "без регистрации",
        },
        {
            "full_name": "Иванов Иван Иванович",
            "birthday_date": "01.01.1980",
            "__page_number": 2,
            "__registration_status": "registered",
        },
    ]

    assert filter_out_without_registration(persons) == [
        {
            "full_name": "Иванов Иван Иванович",
            "birthday_date": "01.01.1980",
            "__page_number": 2,
            "__registration_status": "registered",
        }
    ]

    assert build_without_registration_trace(persons) == [
        {
            "full_name": "Шведова Анна Вадимовна",
            "birthday_date": "14.11.1975",
            "registration_status": "without_registration",
            "raw": "без регистрации",
            "source_pages": [2],
        }
    ]
