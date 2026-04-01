from egd_parser.domain.models.ocr import OCRPageResult
from egd_parser.pipeline.extractors.page2_benefits import extract_page2_benefits
from egd_parser.pipeline.extractors.page2_core import has_resident_table_continuation
from egd_parser.pipeline.extractors.page2_residents import (
    extract_page2_residents,
    extract_page2_residents_with_trace,
    extract_registered_persons_temporary,
)


def extract_page2(ocr_results: list[OCRPageResult]) -> dict:
    resident_pages = []
    ordered_pages = sorted(ocr_results, key=lambda page: page.page_number)
    second_page_index = next((index for index, page in enumerate(ordered_pages) if page.page_number == 2), None)
    if second_page_index is not None:
        resident_pages.append(ordered_pages[second_page_index])
        for page in ordered_pages[second_page_index + 1:]:
            if has_resident_table_continuation(page):
                resident_pages.append(page)
            else:
                break

    if not resident_pages:
        return {
            "registered_persons_constantly": {"count": 0, "persons": []},
            "registered_persons_temporary": {"count": 0, "persons": []},
            "benefits": extract_page2_benefits([], ocr_results),
            "__trace__": {
                "registered_persons_constantly": {
                    "selected_method": "none",
                    "page_numbers": [],
                    "layout_count": 0,
                    "fallback_count": 0,
                    "layout_score": 0,
                    "fallback_score": 0,
                    "persons": [],
                }
            },
        }

    joined_text = "\n".join(page.text for page in resident_pages)
    residents_block, residents_trace = extract_page2_residents_with_trace(resident_pages)

    return {
        "registered_persons_constantly": residents_block,
        "registered_persons_temporary": extract_registered_persons_temporary(joined_text),
        "benefits": extract_page2_benefits(resident_pages, ocr_results),
        "__trace__": {
            "registered_persons_constantly": residents_trace,
        },
    }
