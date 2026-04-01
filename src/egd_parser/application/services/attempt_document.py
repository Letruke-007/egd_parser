import json
from datetime import datetime
from pathlib import Path

from egd_parser.domain.models.document import ParsedDocument
from egd_parser.pipeline.runner import PipelineRunner
from egd_parser.infrastructure.settings import get_settings
from egd_parser.utils.image import ensure_directory


class AttemptDocumentService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.pipeline = PipelineRunner()

    def run(self, filename: str, content: bytes) -> Path:
        document = self.pipeline.run(filename=filename, content=content)
        return self._save_attempt(document)

    def _save_attempt(self, document: ParsedDocument) -> Path:
        attempts_dir = ensure_directory(self.settings.attempts_dir)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = attempts_dir / f"{timestamp}_{Path(document.filename).stem}.json"
        payload = {
            "filename": document.filename,
            "page_count": document.page_count,
            "warnings": document.warnings,
            "extracted_data": document.extracted_data,
            "metadata": document.metadata,
        }
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return output_path
