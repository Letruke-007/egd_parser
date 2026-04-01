from __future__ import annotations

import json
import sys
from pathlib import Path

from egd_parser.pipeline.validate.confidence import (
    score_address_confidence,
    score_date_confidence,
    score_enum_confidence,
    score_identity_document_confidence,
    score_person_name_confidence,
)


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/build_regression_report.py <batch_selected.json>")
        return 1

    batch_path = Path(sys.argv[1])
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    items = batch.get("items", [])

    report = {
        "batch_path": str(batch_path),
        "file_count": len(items),
        "low_confidence_page1": [],
        "low_confidence_residents": [],
        "method_stats": {
            "layout": 0,
            "fallback": 0,
            "unknown": 0,
        },
    }

    for item in items:
        attempt_path = Path(item["attempt_path"])
        payload = json.loads(attempt_path.read_text(encoding="utf-8"))
        metadata = payload.get("metadata", {})
        trace = metadata.get("extraction_trace", {})
        extracted = payload.get("extracted_data", {})

        page1 = extracted.get("page_1", {})
        page2_trace = trace.get("page_2", {}).get("registered_persons_constantly", {})

        page1_fields = {
            "document_date": {
                "value": page1.get("document_date"),
                "confidence": score_date_confidence(page1.get("document_date")),
            },
            "property_address": {
                "value": (page1.get("property_address") or {}).get("full"),
                "confidence": score_address_confidence((page1.get("property_address") or {}).get("full")),
            },
            "settlement_type": {
                "value": page1.get("settlement_type"),
                "confidence": score_enum_confidence(page1.get("settlement_type")),
            },
        }

        for field_name, field_trace in page1_fields.items():
            confidence = field_trace["confidence"]
            if confidence < 0.75:
                report["low_confidence_page1"].append(
                    {
                        "filename": item["filename"],
                        "field": field_name,
                        "value": field_trace["value"],
                        "confidence": confidence,
                    }
                )

        method = page2_trace.get("selected_method", "unknown")
        report["method_stats"][method] = report["method_stats"].get(method, 0) + 1

        public_persons = (
            extracted.get("page_2", {})
            .get("registered_persons_constantly", {})
            .get("persons", [])
        )
        trace_persons = page2_trace.get("persons", [])

        for index, person in enumerate(public_persons):
            trace_person = trace_persons[index] if index < len(trace_persons) else {}
            full_name_confidence = score_person_name_confidence(person.get("full_name"))
            passport_confidence = score_identity_document_confidence(person.get("passport"))
            if full_name_confidence < 0.75 or (passport_confidence not in (0.0, 1.0) and passport_confidence < 0.7):
                report["low_confidence_residents"].append(
                    {
                        "filename": item["filename"],
                        "full_name": person.get("full_name"),
                        "full_name_confidence": full_name_confidence,
                        "passport_confidence": passport_confidence,
                        "source_method": trace_person.get("source_method")
                        or trace_person.get("name_source_method")
                        or page2_trace.get("selected_method"),
                    }
                )

    output_path = batch_path.with_name(batch_path.stem + "_regression_report.json")
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
