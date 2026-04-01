from typing import Optional

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse

from egd_parser.api.schemas.response import (
    CleanupResponse,
    JobAcceptedResponse,
    UploadedJobFileListResponse,
    UploadedJobFileResponse,
    JobListResponse,
    JobResultsResponse,
    JobStatusResponse,
)
from egd_parser.application.services.job_models import UploadedDocument
from egd_parser.application.services.job_service import JobService

router = APIRouter(tags=["jobs"])


def get_job_service(request: Request) -> JobService:
    return request.app.state.job_service


@router.post("/jobs", response_model=JobAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_job(
    request: Request,
    files: list[UploadFile] = File(...),
    callback: Optional[str] = Query(default=None, description="Callback URL for POST result"),
) -> JobAcceptedResponse:
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")

    uploaded_documents: list[UploadedDocument] = []
    for file in files:
        content = await file.read()
        uploaded_documents.append(
            UploadedDocument(
                filename=file.filename or "document.pdf",
                content=content,
                content_type=file.content_type,
            )
        )

    job = get_job_service(request).enqueue_job(uploaded_documents, callback_url=callback)
    return JobAcceptedResponse(**job.model_dump())


@router.get("/jobs", response_model=JobListResponse)
def list_jobs(request: Request, limit: int = Query(default=100, ge=1, le=500)) -> JobListResponse:
    return get_job_service(request).list_jobs(limit=limit)


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str, request: Request) -> JobStatusResponse:
    result = get_job_service(request).get_status(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return result


@router.get("/jobs/{job_id}/results", response_model=JobResultsResponse)
def get_job_results(job_id: str, request: Request) -> JobResultsResponse:
    result = get_job_service(request).get_results(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return result


@router.get("/jobs/{job_id}/files", response_model=UploadedJobFileListResponse)
def list_uploaded_job_files(job_id: str, request: Request) -> UploadedJobFileListResponse:
    files = get_job_service(request).list_uploaded_files(job_id)
    if files is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return UploadedJobFileListResponse(
        job_id=job_id,
        files=[UploadedJobFileResponse(**item) for item in files],
    )


@router.get("/jobs/{job_id}/files/{file_index}")
def download_uploaded_job_file(job_id: str, file_index: int, request: Request) -> FileResponse:
    path = get_job_service(request).get_uploaded_file_path(job_id, file_index)
    if path is None:
        raise HTTPException(status_code=404, detail="Uploaded file not found.")
    return FileResponse(path=path, filename=path.name.split("_", maxsplit=1)[-1], media_type="application/pdf")


@router.delete("/jobs/cleanup", response_model=CleanupResponse)
def cleanup_jobs(request: Request) -> CleanupResponse:
    retention_days = request.app.state.settings.jobs_retention_days
    return get_job_service(request).cleanup_old_jobs(retention_days=retention_days)
