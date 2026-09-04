"""Quality-report version state around selective pipeline reruns."""

from __future__ import annotations

from app.adapters.pose2sim.runner import RunResult
from app.project.manifest import utc_now
from app.project.manager import ProjectManager

from .audit import QualityAuditService
from .model import QualityReport
from .report_store import QualityReportStore


class RerunQualityReporter:
    def __init__(self, project: ProjectManager) -> None:
        self.project = project
        self.store = QualityReportStore(project)

    def current_or_none(self) -> QualityReport | None:
        try:
            return self.store.load_current()
        except FileNotFoundError:
            return None

    def mark_started(self, before: QualityReport | None) -> None:
        state = self.project.manifest.setdefault("quality", {})
        if not isinstance(state, dict):
            raise ValueError("project quality state must be an object")
        state["status"] = "rerunning"
        state["before_report_id"] = before.report_id if before else None
        state["started_at"] = utc_now()
        self.project.save_manifest()

    def complete(self, before: QualityReport | None) -> QualityReport:
        service = QualityAuditService()
        after = service.analyze(self.project)
        service.save(after)
        state = self.project.manifest.setdefault("quality", {})
        if not isinstance(state, dict):
            raise ValueError("project quality state must be an object")
        state.update(
            {
                "status": "current",
                "current_report_id": after.report_id,
                "last_rerun_at": utc_now(),
                "failed_stage": None,
                "log_path": None,
                "comparison": {
                    "before_report_id": before.report_id if before else None,
                    "after_report_id": after.report_id,
                    "before_metrics": before.metrics() if before else None,
                    "after_metrics": after.metrics(),
                },
            }
        )
        self.project.save_manifest()
        return after

    def fail(self, before: QualityReport | None, result: RunResult) -> None:
        state = self.project.manifest.setdefault("quality", {})
        if not isinstance(state, dict):
            raise ValueError("project quality state must be an object")
        state.update(
            {
                "status": "stale",
                "current_report_id": before.report_id if before else None,
                "last_rerun_at": utc_now(),
                "failed_stage": result.failed_stage,
                "log_path": str(result.log_path),
                "error": result.error,
            }
        )
        self.project.save_manifest()
