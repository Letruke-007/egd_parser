from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock, Thread
from uuid import uuid4

import httpx

from egd_parser.api.normalizer import normalize
from egd_parser.api.schemas.response import (
    CleanupResponse,
    JobFileResult,
    JobListResponse,
    JobResultsResponse,
    JobStatusResponse,
    ParseResponse,
)
from egd_parser.application.services.job_models import JobRecord, UploadedDocument
from egd_parser.application.services.parse_document import ParseDocumentService

logger = logging.getLogger(__name__)


class InMemoryJobStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._jobs: dict[str, JobRecord] = {}

    def create_job(self, files: list[UploadedDocument], *, callback_url: str | None = None) -> JobRecord:
        now = datetime.now(UTC)
        record = JobRecord(
            job_id=str(uuid4()),
            status="queued",
            created_at=now,
            total_files=len(files),
            files=[
                JobFileResult(
                    filename=file.filename,
                    status="queued",
                )
                for file in files
            ],
            callback_url=callback_url,
        )
        with self._lock:
            self._jobs[record.job_id] = record
        return record

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self, limit: int = 100) -> list[JobRecord]:
        with self._lock:
            records = sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)
            return records[:limit]

    def mark_running(self, job_id: str) -> JobRecord | None:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return None
            record.status = "running"
            record.started_at = datetime.now(UTC)
            return record

    def store_file_result(self, job_id: str, result: JobFileResult) -> JobRecord | None:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None or record.files is None:
                return None
            for index, item in enumerate(record.files):
                if item.filename == result.filename:
                    record.files[index] = result
                    break
            record.completed_files = sum(1 for item in record.files if item.status == "completed")
            record.failed_files = sum(1 for item in record.files if item.status == "failed")
            return record

    def mark_completed(self, job_id: str) -> JobRecord | None:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return None
            record.status = "completed" if record.failed_files == 0 else "completed_with_errors"
            record.finished_at = datetime.now(UTC)
            return record

    def mark_failed(self, job_id: str, error: str) -> JobRecord | None:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return None
            record.status = "failed"
            record.error = error
            record.finished_at = datetime.now(UTC)
            return record

    def delete_jobs_older_than(self, cutoff: datetime) -> list[str]:
        with self._lock:
            job_ids = [job_id for job_id, record in self._jobs.items() if record.created_at < cutoff]
            for job_id in job_ids:
                self._jobs.pop(job_id, None)
            return job_ids

    def count_by_status(self) -> dict[str, int]:
        with self._lock:
            counts: dict[str, int] = {}
            for record in self._jobs.values():
                counts[record.status] = counts.get(record.status, 0) + 1
            counts["total"] = len(self._jobs)
            return counts


class JobService:
    def __init__(self, store: object | None = None, upload_store: object | None = None, max_workers: int = 4) -> None:
        self.store = store or InMemoryJobStore()
        self.upload_store = upload_store
        self.max_workers = max_workers

    def enqueue_job(self, files: list[UploadedDocument], *, callback_url: str | None = None) -> JobStatusResponse:
        record = self.store.create_job(files, callback_url=callback_url)
        if self.upload_store is not None:
            self.upload_store.save_job_files(record.job_id, files)
        worker = Thread(target=self._run_job, args=(record.job_id, files), daemon=True)
        worker.start()
        return self._to_status_response(record)

    def list_jobs(self, limit: int = 100) -> JobListResponse:
        if not hasattr(self.store, "list_jobs"):
            return JobListResponse(jobs=[])
        records = self.store.list_jobs(limit=limit)
        return JobListResponse(jobs=[self._to_status_response(record) for record in records])

    def get_status(self, job_id: str) -> JobStatusResponse | None:
        record = self.store.get(job_id)
        if record is None:
            return None
        return self._to_status_response(record)

    def get_results(self, job_id: str) -> JobResultsResponse | None:
        record = self.store.get(job_id)
        if record is None:
            return None
        return JobResultsResponse(
            job_id=record.job_id,
            status=record.status,
            created_at=record.created_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            total_files=record.total_files,
            completed_files=record.completed_files,
            failed_files=record.failed_files,
            files=record.files or [],
            error=record.error,
        )

    def cleanup_old_jobs(self, retention_days: int) -> CleanupResponse:
        if not hasattr(self.store, "delete_jobs_older_than"):
            return CleanupResponse(deleted_jobs=0)
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        deleted_job_ids = self.store.delete_jobs_older_than(cutoff)
        if self.upload_store is not None:
            for job_id in deleted_job_ids:
                self.upload_store.delete_job_files(job_id)
        return CleanupResponse(deleted_jobs=len(deleted_job_ids))

    def list_uploaded_files(self, job_id: str) -> list[dict] | None:
        if self.store.get(job_id) is None:
            return None
        if self.upload_store is None:
            return []
        return self.upload_store.list_job_files(job_id)

    def get_uploaded_file_path(self, job_id: str, file_index: int) -> Path | None:
        if self.store.get(job_id) is None or self.upload_store is None:
            return None
        return self.upload_store.get_job_file_path(job_id, file_index)

    def get_metrics(self) -> dict:
        counts = (
            self.store.count_by_status()
            if hasattr(self.store, "count_by_status")
            else {"total": 0}
        )
        return {
            "jobs": counts,
            "worker_threads": self.max_workers,
        }

    def _run_job(self, job_id: str, files: list[UploadedDocument]) -> None:
        try:
            self.store.mark_running(job_id)
            with ThreadPoolExecutor(max_workers=min(self.max_workers, max(1, len(files)))) as executor:
                futures = {
                    executor.submit(self._parse_document, file): file
                    for file in files
                }
                for future in as_completed(futures):
                    source = futures[future]
                    try:
                        response = future.result()
                        result = JobFileResult(
                            filename=response.filename,
                            status="completed",
                            pages=response.pages,
                            warnings=response.warnings,
                            extracted_data=response.extracted_data,
                            metadata=response.metadata,
                        )
                    except Exception as exc:  # noqa: BLE001
                        result = JobFileResult(
                            filename=source.filename,
                            status="failed",
                            error=str(exc),
                        )
                    self.store.store_file_result(job_id, result)
            self.store.mark_completed(job_id)
        except Exception as exc:  # noqa: BLE001
            self.store.mark_failed(job_id, str(exc))
        self._send_callback(job_id)

    def _send_callback(self, job_id: str) -> None:
        record = self.store.get(job_id)
        if record is None or not record.callback_url:
            return

        try:
            first = None
            if record.status in ("completed", "completed_with_errors") and record.files:
                first = next((f for f in record.files if f.status == "completed" and f.extracted_data), None)

            if first is not None:
                to_dict = lambda v: v.model_dump() if hasattr(v, "model_dump") else v
                raw = {
                    "filename": first.filename,
                    "extracted_data": to_dict(first.extracted_data),
                    "metadata": to_dict(first.metadata),
                    "pages": first.pages,
                    "warnings": first.warnings,
                }
                normalized = normalize(raw)
                payload = {"id": job_id, "status": "completed", "result": normalized}
            else:
                error = record.error
                if not error and record.files:
                    failed = next((f for f in record.files if f.error), None)
                    error = failed.error if failed else None
                payload = {
                    "id": job_id,
                    "status": "failed",
                    "result": None,
                    "error": error or "No data extracted",
                }

            with httpx.Client(timeout=20.0) as client:
                resp = client.post(record.callback_url, json=payload)
                logger.info("Callback POST %s -> %s", record.callback_url, resp.status_code)
        except Exception:  # noqa: BLE001
            logger.exception("Callback to %s failed for job %s", record.callback_url, job_id)

    @staticmethod
    def _parse_document(file: UploadedDocument) -> ParseResponse:
        service = ParseDocumentService()
        return service.run(filename=file.filename, content=file.content)

    @staticmethod
    def _to_status_response(record: JobRecord) -> JobStatusResponse:
        return JobStatusResponse(
            job_id=record.job_id,
            status=record.status,
            created_at=record.created_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            total_files=record.total_files,
            completed_files=record.completed_files,
            failed_files=record.failed_files,
            error=record.error,
        )
