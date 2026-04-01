PAGE_LAYOUTS = {
    "page2": {
        "residents_table": {
            "page_2": {
                "top": 850,
                "left": 0,
                "right": 2800,
            },
            "continuation_page": {
                "top": 430,
                "left": 0,
                "right": 2800,
            },
            "columns": {
                "full_name": {
                    "left": 0,
                    "right": 560,
                },
                "birth_date": {
                    "left": 500,
                    "right": 930,
                },
                "current_passport": {
                    "left": 1180,
                    "right": 2050,
                },
                "departure": {
                    "left": 2050,
                    "right": 2800,
                },
            },
        }
    }
}


def build_regions() -> dict:
    return PAGE_LAYOUTS


def get_page_regions(page_name: str) -> dict:
    return PAGE_LAYOUTS.get(page_name, {})
