from fastapi import APIRouter, Request

from egd_parser.application.services.job_service import JobService
from egd_parser.infrastructure.settings import Settings

router = APIRouter(tags=["metrics"])


def get_job_service(request: Request) -> JobService:
    return request.app.state.job_service


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


@router.get("/metrics")
def get_metrics(request: Request) -> dict:
    settings = get_settings(request)
    metrics = get_job_service(request).get_metrics()
    metrics["runtime"] = {
        "ocr_engine": settings.ocr_engine,
        "pdf_render_dpi": settings.pdf_render_dpi,
        "jobs_db_path": str(settings.jobs_db_path),
        "uploads_dir": str(settings.uploads_dir),
        "rendered_pages_dir": str(settings.rendered_pages_dir),
    }
    return metrics
