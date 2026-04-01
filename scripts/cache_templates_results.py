from __future__ import annotations

import json
from pathlib import Path

from egd_parser.pipeline.runner import PipelineRunner


def main() -> int:
    templates_dir = Path("/tmp/templates")
    output_path = Path("/tmp/templates_parse_cache.json")
    files = sorted(templates_dir.glob("*.pdf"), key=lambda path: int(path.stem))

    runner = PipelineRunner()
    results: list[dict] = []

    for path in files:
        try:
            parsed = runner.run(filename=path.name, content=path.read_bytes())
            results.append(
                {
                    "file": path.name,
                    "status": "ok",
                    "data": parsed.extracted_data,
                }
            )
            print(f"OK|{path.name}")
        except Exception as exc:
            results.append(
                {
                    "file": path.name,
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            print(f"FAIL|{path.name}|{type(exc).__name__}:{exc}")

    output_path.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
    print(f"CACHE|{output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
