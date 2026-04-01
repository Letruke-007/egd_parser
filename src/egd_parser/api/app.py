from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

from egd_parser.api.routes.health import router as health_router
from egd_parser.api.routes.jobs import router as jobs_router
from egd_parser.api.routes.metrics import router as metrics_router
from egd_parser.api.routes.parse import router as parse_router
from egd_parser.application.services.job_service import JobService
from egd_parser.infrastructure.housekeeping import cleanup_rendered_pages
from egd_parser.infrastructure.logging.setup import configure_logging
from egd_parser.infrastructure.storage import SQLiteJobStore
from egd_parser.infrastructure.storage.upload_store import UploadStore
from egd_parser.infrastructure.settings import get_settings

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        started_at = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        logger.info(
            "request_completed",
            extra={
                "path": request.url.path,
                "method": request.method,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    settings.jobs_db_path.parent.mkdir(parents=True, exist_ok=True)
    settings.rendered_pages_dir.mkdir(parents=True, exist_ok=True)
    deleted = cleanup_rendered_pages(
        settings.rendered_pages_dir,
        settings.rendered_pages_retention_hours,
    )
    logger.info("startup_completed", extra={"deleted_rendered_pages": deleted})
    yield
    deleted = cleanup_rendered_pages(
        settings.rendered_pages_dir,
        settings.rendered_pages_retention_hours,
    )
    logger.info("shutdown_completed", extra={"deleted_rendered_pages": deleted})


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="EGD Parser Service",
        version="0.1.0",
        description="OCR service for parsing unified housing documents (EGD) PDF files.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.job_service = JobService(
        store=SQLiteJobStore(settings.jobs_db_path),
        upload_store=UploadStore(settings.uploads_dir),
        max_workers=settings.job_worker_threads,
    )

    app.add_middleware(RequestLoggingMiddleware)
    app.include_router(health_router)
    app.include_router(metrics_router)
    app.include_router(parse_router, prefix=settings.api_prefix)
    app.include_router(jobs_router, prefix=settings.api_prefix)

    return app


app = create_app()
