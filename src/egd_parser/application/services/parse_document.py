from egd_parser.api.schemas.response import ParseResponse
from egd_parser.domain.models.document import ParsedDocument
from egd_parser.pipeline.runner import PipelineRunner


class ParseDocumentService:
    def __init__(self) -> None:
        self.pipeline = PipelineRunner()

    def run(self, filename: str, content: bytes) -> ParseResponse:
        document = self.pipeline.run(filename=filename, content=content)
        return self._to_response(document)

    @staticmethod
    def _to_response(document: ParsedDocument) -> ParseResponse:
        return ParseResponse(
            filename=document.filename,
            pages=document.page_count,
            warnings=document.warnings,
            extracted_data=document.extracted_data,
            metadata=document.metadata,
        )
