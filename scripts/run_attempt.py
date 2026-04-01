from pathlib import Path
import sys

from egd_parser.application.services.attempt_document import AttemptDocumentService


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/run_attempt.py /path/to/file.pdf")
        return 1

    pdf_path = Path(sys.argv[1])
    if not pdf_path.exists():
        print(f"File not found: {pdf_path}")
        return 1

    service = AttemptDocumentService()
    output_path = service.run(filename=pdf_path.name, content=pdf_path.read_bytes())
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
