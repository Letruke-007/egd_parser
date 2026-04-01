from egd_parser.domain.models.document import ParsedDocument


class InspectDocumentService:
    """Diagnostic use case for future OCR/layout inspection."""

    def run(self, filename: str, content: bytes) -> ParsedDocument:
        return ParsedDocument(filename=filename, page_count=0, warnings=["inspection is not implemented"])
