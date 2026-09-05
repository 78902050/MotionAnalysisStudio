"""Stable JSON, CSV and HTML comparison report exports."""

from __future__ import annotations

import csv
import html
import io
import json
import os
import tempfile
from pathlib import Path


class ReportExporter:
    def export(self, report, path: Path, format: str) -> None:
        path = Path(path)
        if format not in {"json", "csv", "html"}:
            raise ValueError(f"unsupported report format: {format}")
        if format == "json":
            text = json.dumps(report.to_dict(), ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n"
        elif format == "csv":
            text = _csv_text(report)
        else:
            text = _html_text(report)
        _atomic_text_replace(path, text)


def export_report(report, path: Path, format: str) -> None:
    ReportExporter().export(report, path, format)


def _csv_text(report) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    fields = ("alignment_key", "member_id", "project_id", "person_id", "trial_id", "metric", "unit", "frame", "time", "value", "missing_reason", "event_id")
    writer.writerow(fields)
    for row in report.rows:
        data = row.to_dict()
        writer.writerow(["" if data[field] is None else data[field] for field in fields])
    return output.getvalue()


def _html_text(report) -> str:
    headers = ("alignment_key", "member_id", "metric", "unit", "frame", "time", "value", "missing_reason", "event_id")
    rows = []
    for row in report.rows:
        data = row.to_dict()
        cells = "".join(f"<td>{html.escape('' if data[field] is None else str(data[field]))}</td>" for field in headers)
        rows.append(f"<tr>{cells}</tr>")
    header_html = "".join(f"<th>{html.escape(field)}</th>" for field in headers)
    return (
        "<!doctype html>\n<html><head><meta charset=\"utf-8\"><title>"
        + html.escape(report.report_id)
        + "</title></head><body>\n<h1>"
        + html.escape(report.report_id)
        + "</h1>\n<table><thead><tr>"
        + header_html
        + "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>\n</body></html>\n"
    )


def _atomic_text_replace(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
