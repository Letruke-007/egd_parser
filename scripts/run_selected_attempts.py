from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from egd_parser.application.services.attempt_document import AttemptDocumentService
from egd_parser.infrastructure.settings import get_settings
from egd_parser.utils.image import ensure_directory


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python scripts/run_selected_attempts.py <pdf_or_dir> [more_pdfs_or_ranges...]")
        print("Examples:")
        print("  python scripts/run_selected_attempts.py templates/35.pdf templates/37.pdf")
        print("  python scripts/run_selected_attempts.py templates 35-39 41 43")
        return 1

    resolved_paths = resolve_pdf_paths(sys.argv[1:])
    if not resolved_paths:
        print("No PDF files resolved from input.")
        return 1

    service = AttemptDocumentService()
    settings = get_settings()
    attempts_dir = ensure_directory(settings.attempts_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    items: list[dict] = []
    total = len(resolved_paths)
    for index, pdf_path in enumerate(resolved_paths, start=1):
        print(f"[{index}/{total}] {pdf_path}", flush=True)
        attempt_path = service.run(filename=pdf_path.name, content=pdf_path.read_bytes())
        payload = json.loads(attempt_path.read_text(encoding="utf-8"))
        page_1 = payload.get("extracted_data", {}).get("page_1", {})
        page_2 = payload.get("extracted_data", {}).get("page_2", {})
        items.append(
            {
                "filename": pdf_path.name,
                "attempt_path": str(attempt_path),
                "document_date": page_1.get("document_date"),
                "property_address": page_1.get("property_address", {}).get("full"),
                "owners": [owner.get("full_name") for owner in page_1.get("owners", [])],
                "registered_persons_count": page_2.get("registered_persons_constantly", {}).get("count"),
                "benefits": page_2.get("benefits"),
                "warnings": payload.get("warnings", []),
            }
        )

    batch_path = attempts_dir / f"batch_selected_{timestamp}.json"
    batch_path.write_text(
        json.dumps(
            {
                "inputs": sys.argv[1:],
                "file_count": len(resolved_paths),
                "items": items,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(batch_path)
    return 0


def resolve_pdf_paths(args: list[str]) -> list[Path]:
    directory = next((Path(arg) for arg in args if Path(arg).is_dir()), None)
    resolved: list[Path] = []
    seen: set[Path] = set()

    for arg in args:
        path = Path(arg)
        if path.is_file():
            candidate = path.resolve()
            if candidate.suffix.lower() == ".pdf" and candidate not in seen:
                resolved.append(candidate)
                seen.add(candidate)
            continue

        if directory and is_number_or_range(arg):
            for number in expand_number_range(arg):
                candidate = (directory / f"{number}.pdf").resolve()
                if candidate.exists() and candidate not in seen:
                    resolved.append(candidate)
                    seen.add(candidate)
            continue

    return resolved


def is_number_or_range(value: str) -> bool:
    if value.isdigit():
        return True
    if "-" not in value:
        return False
    start, end = value.split("-", maxsplit=1)
    return start.isdigit() and end.isdigit()


def expand_number_range(value: str) -> list[int]:
    if value.isdigit():
        return [int(value)]
    start_text, end_text = value.split("-", maxsplit=1)
    start = int(start_text)
    end = int(end_text)
    if start > end:
        start, end = end, start
    return list(range(start, end + 1))


if __name__ == "__main__":
    raise SystemExit(main())
