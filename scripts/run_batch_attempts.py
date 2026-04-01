from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from egd_parser.application.services.attempt_document import AttemptDocumentService
from egd_parser.infrastructure.settings import get_settings
from egd_parser.utils.image import ensure_directory


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/run_batch_attempts.py /path/to/pdf_dir")
        return 1

    pdf_dir = Path(sys.argv[1])
    if not pdf_dir.exists() or not pdf_dir.is_dir():
        print(f"Directory not found: {pdf_dir}")
        return 1

    pdf_paths = sorted(pdf_dir.glob("*.pdf"), key=sort_key)
    if not pdf_paths:
        print(f"No PDF files found in: {pdf_dir}")
        return 1

    service = AttemptDocumentService()
    settings = get_settings()
    attempts_dir = ensure_directory(settings.attempts_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    items: list[dict] = []
    for index, pdf_path in enumerate(pdf_paths, start=1):
        print(f"[{index}/{len(pdf_paths)}] {pdf_path.name}", flush=True)
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

    batch_path = attempts_dir / f"batch_{timestamp}.json"
    batch_path.write_text(
        json.dumps(
            {
                "source_dir": str(pdf_dir),
                "file_count": len(pdf_paths),
                "items": items,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(batch_path)
    return 0


def sort_key(path: Path) -> tuple[int, str]:
    stem = path.stem
    return (int(stem) if stem.isdigit() else 10**9, stem)


if __name__ == "__main__":
    raise SystemExit(main())
