from fastapi import APIRouter, File, UploadFile

from egd_parser.api.normalizer import normalize
from egd_parser.api.schemas.response import ParseResponse
from egd_parser.application.services.parse_document import ParseDocumentService

router = APIRouter(tags=["parse"])


@router.post("/parse", response_model=ParseResponse)
async def parse_document(file: UploadFile = File(...)) -> ParseResponse:
    content = await file.read()
    service = ParseDocumentService()
    return service.run(filename=file.filename or "document.pdf", content=content)


@router.post("/parse/normalized")
async def parse_document_normalized(file: UploadFile = File(...)) -> dict:
    content = await file.read()
    service = ParseDocumentService()
    result = service.run(filename=file.filename or "document.pdf", content=content)
    return normalize(result.model_dump())
