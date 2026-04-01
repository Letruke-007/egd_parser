from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from egd_parser.api.schemas.response import JobFileResult


@dataclass(slots=True, frozen=True)
class UploadedDocument:
    filename: str
    content: bytes
    content_type: str | None = None


@dataclass(slots=True)
class JobRecord:
    job_id: str
    status: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    total_files: int = 0
    completed_files: int = 0
    failed_files: int = 0
    files: list[JobFileResult] | None = None
    error: str | None = None
    callback_url: str | None = None
