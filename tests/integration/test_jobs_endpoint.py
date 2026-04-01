from datetime import UTC, datetime

from fastapi.testclient import TestClient

from egd_parser.api.app import app
from egd_parser.api.schemas.response import JobStatusResponse, ParseResponse
from egd_parser.application.services.job_service import JobService


def test_jobs_endpoints_lifecycle(monkeypatch) -> None:
    fixed_job = JobStatusResponse(
        job_id="job-123",
        status="queued",
        created_at=datetime.now(UTC),
        total_files=2,
        completed_files=0,
        failed_files=0,
    )

    def fake_enqueue_job(self, files):
        return fixed_job

    def fake_get_status(self, job_id):
        return JobStatusResponse(
            job_id=job_id,
            status="completed",
            created_at=fixed_job.created_at,
            started_at=fixed_job.created_at,
            finished_at=fixed_job.created_at,
            total_files=2,
            completed_files=2,
            failed_files=0,
        )

    def fake_get_results(self, job_id):
        status = fake_get_status(None, job_id)
        return {
            **status.model_dump(),
            "files": [
                ParseResponse(
                    filename="sample-1.pdf",
                    pages=1,
                    extracted_data={"document_type": "egd"},
                ).model_dump() | {"status": "completed", "error": None},
                ParseResponse(
                    filename="sample-2.pdf",
                    pages=2,
                    extracted_data={"document_type": "egd"},
                ).model_dump() | {"status": "completed", "error": None},
            ],
        }

    monkeypatch.setattr(JobService, "enqueue_job", fake_enqueue_job)
    monkeypatch.setattr(JobService, "get_status", fake_get_status)
    monkeypatch.setattr(JobService, "get_results", fake_get_results)

    client = TestClient(app)

    create_response = client.post(
        "/api/v1/jobs",
        files=[
            ("files", ("sample-1.pdf", b"%PDF-1.3", "application/pdf")),
            ("files", ("sample-2.pdf", b"%PDF-1.3", "application/pdf")),
        ],
    )

    assert create_response.status_code == 202
    create_payload = create_response.json()
    assert create_payload["job_id"] == "job-123"
    assert create_payload["total_files"] == 2

    status_response = client.get("/api/v1/jobs/job-123")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "completed"

    result_response = client.get("/api/v1/jobs/job-123/results")
    assert result_response.status_code == 200
    result_payload = result_response.json()
    assert result_payload["completed_files"] == 2
    assert len(result_payload["files"]) == 2
    assert result_payload["files"][0]["filename"] == "sample-1.pdf"
