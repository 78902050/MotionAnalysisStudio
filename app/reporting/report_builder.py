"""Construction boundary for versioned comparison reports."""

from __future__ import annotations

from collections.abc import Sequence


class ReportBuilder:
    def build(self, report_id, request, member_ids, rows, metadata, summary):
        from app.analysis.comparison import ComparisonReport

        return ComparisonReport(
            report_id=report_id,
            report_version="comparison-v1",
            request=request,
            member_ids=tuple(member_ids),
            rows=tuple(rows),
            metadata=dict(metadata),
            summary=dict(summary),
        )
