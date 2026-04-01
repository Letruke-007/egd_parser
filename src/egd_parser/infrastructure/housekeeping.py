from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path


def cleanup_rendered_pages(root_dir: Path, retention_hours: int) -> int:
    if not root_dir.exists():
        return 0

    cutoff = datetime.now(UTC) - timedelta(hours=retention_hours)
    deleted = 0
    for path in root_dir.glob("**/*"):
        if not path.is_file():
            continue
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        if modified_at < cutoff:
            path.unlink(missing_ok=True)
            deleted += 1
    return deleted
