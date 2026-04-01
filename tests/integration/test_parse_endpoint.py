from fastapi.testclient import TestClient

from egd_parser.api.app import app
from egd_parser.api.schemas.response import ParseResponse
from egd_parser.application.services.parse_document import ParseDocumentService


def test_parse_endpoint_returns_stub_response(monkeypatch) -> None:
    monkeypatch.setattr(
        ParseDocumentService,
        "run",
        lambda self, filename, content: ParseResponse(
            filename=filename,
            pages=1,
            extracted_data={"document_type": "egd", "page_1": {}},
        ),
    )

    client = TestClient(app)

    response = client.post(
        "/api/v1/parse",
        files={"file": ("sample.pdf", b"%PDF-1.3", "application/pdf")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["filename"] == "sample.pdf"
    assert payload["status"] == "accepted"
    assert payload["pages"] == 1
    assert payload["extracted_data"]["document_type"] == "egd"
    assert "page_1" in payload["extracted_data"]
