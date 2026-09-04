"""Atomic storage for current and versioned quality reports."""

import json

from app.io.transactions import ProjectTransaction, TransactionRecovery
from app.project.manager import ProjectManager

from .model import QualityReport


class QualityReportStore:
    def __init__(self, project: ProjectManager) -> None:
        self.project = project

    def save(self, report: QualityReport) -> None:
        payload = report.to_dict()
        current = self.project.path_for("quality_report")
        history = current.parent / "history" / f"{report.report_id}.json"
        root = self.project.root.resolve()
        transaction = ProjectTransaction(root)
        transaction.prepare_json(current.resolve().relative_to(root), payload)
        transaction.prepare_json(history.resolve().relative_to(root), payload)
        try:
            transaction.commit()
        except BaseException:
            TransactionRecovery(root).recover_all()
            raise

    def load_current(self) -> QualityReport:
        path = self.project.path_for("quality_report")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("quality report must contain a JSON object")
        return QualityReport.from_dict(value)
