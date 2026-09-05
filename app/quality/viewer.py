"""Read-only presentation models for quality reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from app.domain.addresses import CorrectionTarget
from app.domain.issues import QualityIssue

from .model import QualityReport


MetricValue = float | int | None


@dataclass(frozen=True)
class QualityIssueView:
    issue_id: str
    severity: str
    disposition: str
    modification_count: int
    message: str
    report_version: str
    target: CorrectionTarget | None
    location_error: str | None


@dataclass(frozen=True)
class QualityViewerModel:
    """A report projection that exposes no mutation operations."""

    report: QualityReport
    issues: tuple[QualityIssueView, ...] = field(init=False)

    def __post_init__(self) -> None:
        rows = tuple(self._issue_view(issue) for issue in self.report.issues())
        object.__setattr__(self, "issues", rows)

    def target(self, issue_id: str) -> CorrectionTarget | None:
        row = self._find(issue_id)
        return row.target if row is not None else None

    def unlocatable_reason(self, issue_id: str) -> str | None:
        row = self._find(issue_id)
        return row.location_error if row is not None else "质量报告中未找到该问题"

    def _find(self, issue_id: str) -> QualityIssueView | None:
        return next((row for row in self.issues if row.issue_id == issue_id), None)

    def _issue_view(self, issue: QualityIssue) -> QualityIssueView:
        target: CorrectionTarget | None = None
        reason: str | None = None
        if issue.target is None:
            reason = "缺少帧定位信息"
        elif issue.person is None:
            reason = "缺少人物定位信息"
        elif issue.keypoint is None:
            reason = "缺少关节点定位信息"
        else:
            target = CorrectionTarget(issue.target, issue.person, issue.keypoint)
        return QualityIssueView(
            issue_id=issue.issue_id,
            severity=issue.severity,
            disposition=issue.disposition,
            modification_count=issue.modification_count,
            message=issue.message,
            report_version=self.report.report_id,
            target=target,
            location_error=reason,
        )


@dataclass(frozen=True)
class QualityComparisonView:
    before_report_id: str | None
    current_report_id: str
    before_metrics: Mapping[str, MetricValue]
    current_metrics: Mapping[str, MetricValue]
    last_rerun_at: str | None

    @classmethod
    def from_sources(
        cls,
        report: QualityReport,
        manifest: Mapping[str, object],
    ) -> "QualityComparisonView":
        quality_value = manifest.get("quality")
        quality = quality_value if isinstance(quality_value, dict) else {}
        comparison_value = quality.get("comparison")
        comparison = comparison_value if isinstance(comparison_value, dict) else {}
        before_value = comparison.get("before_metrics")
        before = dict(before_value) if isinstance(before_value, dict) else {}
        last_rerun = quality.get("last_rerun_at")
        return cls(
            before_report_id=_text_or_none(comparison.get("before_report_id")),
            current_report_id=report.report_id,
            before_metrics=MappingProxyType(before),
            current_metrics=MappingProxyType(report.metrics()),
            last_rerun_at=_text_or_none(last_rerun),
        )


def _text_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None
