def collect_required_field_warnings(data: dict) -> list[str]:
    warnings: list[str] = []
    if "document_type" not in data:
        warnings.append("document_type is missing")
    if "page_1" not in data:
        warnings.append("page_1 is missing")
    return warnings
