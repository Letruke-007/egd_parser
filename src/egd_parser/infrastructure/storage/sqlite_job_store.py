from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from egd_parser.api.schemas.response import JobFileResult
from egd_parser.application.services.job_models import JobRecord, UploadedDocument


class SQLiteJobStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._init_db()

    def create_job(self, files: list[UploadedDocument], *, callback_url: str | None = None) -> JobRecord:
        record = JobRecord(
            job_id=self._generate_job_id(),
            status="queued",
            created_at=datetime.now(UTC),
            total_files=len(files),
            files=[JobFileResult(filename=file.filename, status="queued") for file in files],
            callback_url=callback_url,
        )
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    job_id, status, created_at, started_at, finished_at,
                    total_files, completed_files, failed_files, error, callback_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.job_id,
                    record.status,
                    self._to_iso(record.created_at),
                    None,
                    None,
                    record.total_files,
                    record.completed_files,
                    record.failed_files,
                    record.error,
                    record.callback_url,
                ),
            )
            connection.executemany(
                """
                INSERT INTO job_files (
                    job_id, file_index, filename, status, pages,
                    warnings_json, extracted_data_json, metadata_json, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        record.job_id,
                        index,
                        file.filename,
                        "queued",
                        0,
                        "[]",
                        "{}",
                        "{}",
                        None,
                    )
                    for index, file in enumerate(files)
                ],
            )
            connection.commit()
        return record

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock, self._connect() as connection:
            job_row = connection.execute(
                """
                SELECT job_id, status, created_at, started_at, finished_at,
                       total_files, completed_files, failed_files, error, callback_url
                FROM jobs
                WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
            if job_row is None:
                return None
            file_rows = connection.execute(
                """
                SELECT filename, status, pages, warnings_json,
                       extracted_data_json, metadata_json, error
                FROM job_files
                WHERE job_id = ?
                ORDER BY file_index
                """,
                (job_id,),
            ).fetchall()
        return self._row_to_record(job_row, file_rows)

    def list_jobs(self, limit: int = 100) -> list[JobRecord]:
        with self._lock, self._connect() as connection:
            job_rows = connection.execute(
                """
                SELECT job_id, status, created_at, started_at, finished_at,
                       total_files, completed_files, failed_files, error, callback_url
                FROM jobs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            records: list[JobRecord] = []
            for job_row in job_rows:
                file_rows = connection.execute(
                    """
                    SELECT filename, status, pages, warnings_json,
                           extracted_data_json, metadata_json, error
                    FROM job_files
                    WHERE job_id = ?
                    ORDER BY file_index
                    """,
                    (job_row["job_id"],),
                ).fetchall()
                records.append(self._row_to_record(job_row, file_rows))
        return records

    def mark_running(self, job_id: str) -> JobRecord | None:
        started_at = datetime.now(UTC)
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE jobs SET status = ?, started_at = ? WHERE job_id = ?",
                ("running", self._to_iso(started_at), job_id),
            )
            connection.commit()
        return self.get(job_id)

    def store_file_result(self, job_id: str, result: JobFileResult) -> JobRecord | None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE job_files
                SET status = ?, pages = ?, warnings_json = ?, extracted_data_json = ?, metadata_json = ?, error = ?
                WHERE job_id = ? AND filename = ?
                """,
                (
                    result.status,
                    result.pages,
                    json.dumps(result.warnings, ensure_ascii=False),
                    json.dumps(result.extracted_data.model_dump() if hasattr(result.extracted_data, "model_dump") else result.extracted_data, ensure_ascii=False),
                    json.dumps(result.metadata.model_dump() if hasattr(result.metadata, "model_dump") else result.metadata, ensure_ascii=False),
                    result.error,
                    job_id,
                    result.filename,
                ),
            )
            counts = connection.execute(
                """
                SELECT
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END)
                FROM job_files
                WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
            completed_files = counts[0] or 0
            failed_files = counts[1] or 0
            connection.execute(
                "UPDATE jobs SET completed_files = ?, failed_files = ? WHERE job_id = ?",
                (completed_files, failed_files, job_id),
            )
            connection.commit()
        return self.get(job_id)

    def mark_completed(self, job_id: str) -> JobRecord | None:
        record = self.get(job_id)
        if record is None:
            return None
        status = "completed" if record.failed_files == 0 else "completed_with_errors"
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE jobs SET status = ?, finished_at = ? WHERE job_id = ?",
                (status, self._to_iso(datetime.now(UTC)), job_id),
            )
            connection.commit()
        return self.get(job_id)

    def mark_failed(self, job_id: str, error: str) -> JobRecord | None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE jobs SET status = ?, error = ?, finished_at = ? WHERE job_id = ?",
                ("failed", error, self._to_iso(datetime.now(UTC)), job_id),
            )
            connection.commit()
        return self.get(job_id)

    def delete_jobs_older_than(self, cutoff: datetime) -> list[str]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT job_id FROM jobs WHERE created_at < ?",
                (self._to_iso(cutoff),),
            ).fetchall()
            job_ids = [row["job_id"] for row in rows]
            if not job_ids:
                return []
            connection.executemany(
                "DELETE FROM job_files WHERE job_id = ?",
                [(job_id,) for job_id in job_ids],
            )
            connection.executemany(
                "DELETE FROM jobs WHERE job_id = ?",
                [(job_id,) for job_id in job_ids],
            )
            connection.commit()
        return job_ids

    def count_by_status(self) -> dict[str, int]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT status, COUNT(*) AS total
                FROM jobs
                GROUP BY status
                """
            ).fetchall()
            total = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        counts = {row["status"]: row["total"] for row in rows}
        counts["total"] = total
        return counts

    def _init_db(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    total_files INTEGER NOT NULL,
                    completed_files INTEGER NOT NULL,
                    failed_files INTEGER NOT NULL,
                    error TEXT,
                    callback_url TEXT
                )
                """
            )
            # Migrate existing databases that lack the callback_url column
            columns = [row[1] for row in connection.execute("PRAGMA table_info(jobs)").fetchall()]
            if "callback_url" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN callback_url TEXT")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS job_files (
                    job_id TEXT NOT NULL,
                    file_index INTEGER NOT NULL,
                    filename TEXT NOT NULL,
                    status TEXT NOT NULL,
                    pages INTEGER NOT NULL,
                    warnings_json TEXT NOT NULL,
                    extracted_data_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    error TEXT,
                    PRIMARY KEY (job_id, file_index),
                    FOREIGN KEY(job_id) REFERENCES jobs(job_id)
                )
                """
            )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _generate_job_id() -> str:
        from uuid import uuid4

        return str(uuid4())

    @staticmethod
    def _to_iso(value: datetime | None) -> str | None:
        return value.isoformat() if value else None

    @staticmethod
    def _from_iso(value: str | None) -> datetime | None:
        return datetime.fromisoformat(value) if value else None

    def _row_to_record(self, job_row: sqlite3.Row, file_rows: list[sqlite3.Row]) -> JobRecord:
        return JobRecord(
            job_id=job_row["job_id"],
            status=job_row["status"],
            created_at=self._from_iso(job_row["created_at"]) or datetime.now(UTC),
            started_at=self._from_iso(job_row["started_at"]),
            finished_at=self._from_iso(job_row["finished_at"]),
            total_files=job_row["total_files"],
            completed_files=job_row["completed_files"],
            failed_files=job_row["failed_files"],
            files=[
                JobFileResult(
                    filename=row["filename"],
                    status=row["status"],
                    pages=row["pages"],
                    warnings=json.loads(row["warnings_json"]),
                    extracted_data=json.loads(row["extracted_data_json"]),
                    metadata=json.loads(row["metadata_json"]),
                    error=row["error"],
                )
                for row in file_rows
            ],
            error=job_row["error"],
            callback_url=job_row["callback_url"],
        )
