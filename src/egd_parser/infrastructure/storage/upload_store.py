from __future__ import annotations

import re
from pathlib import Path

from egd_parser.application.services.job_models import UploadedDocument


class UploadStore:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def save_job_files(self, job_id: str, files: list[UploadedDocument]) -> list[Path]:
        job_dir = self.root_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        saved_paths: list[Path] = []
        for index, file in enumerate(files):
            target = job_dir / f"{index:03d}_{self._sanitize_filename(file.filename)}"
            target.write_bytes(file.content)
            saved_paths.append(target)
        return saved_paths

    def list_job_files(self, job_id: str) -> list[dict]:
        job_dir = self.root_dir / job_id
        if not job_dir.exists():
            return []
        items: list[dict] = []
        for path in sorted(job_dir.iterdir()):
            if not path.is_file():
                continue
            file_index, original_filename = self._parse_saved_filename(path.name)
            items.append(
                {
                    "file_index": file_index,
                    "filename": original_filename,
                    "stored_filename": path.name,
                    "size_bytes": path.stat().st_size,
                }
            )
        return items

    def get_job_file_path(self, job_id: str, file_index: int) -> Path | None:
        job_dir = self.root_dir / job_id
        if not job_dir.exists():
            return None
        pattern = f"{file_index:03d}_*"
        matches = sorted(job_dir.glob(pattern))
        return matches[0] if matches else None

    def delete_job_files(self, job_id: str) -> None:
        job_dir = self.root_dir / job_id
        if not job_dir.exists():
            return
        for path in sorted(job_dir.glob("**/*"), reverse=True):
            if path.is_file():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                path.rmdir()
        job_dir.rmdir()

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        cleaned = re.sub(r"[^0-9A-Za-zА-Яа-я._ -]+", "_", filename)
        cleaned = cleaned.strip() or "document.pdf"
        return cleaned

    @staticmethod
    def _parse_saved_filename(value: str) -> tuple[int, str]:
        match = re.match(r"(?P<index>\d{3})_(?P<filename>.+)", value)
        if not match:
            return 0, value
        return int(match.group("index")), match.group("filename")
