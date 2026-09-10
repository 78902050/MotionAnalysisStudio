"""Atomic storage for current and versioned quality reports."""

from collections import OrderedDict
import json
from pathlib import Path
from threading import RLock

from app.io.transactions import ProjectTransaction, TransactionRecovery
from app.project.manager import ProjectManager

from .model import QualityReport


class QualityReportStore:
    # A quality report can contain one entry for every low-confidence
    # keypoint.  Opening the two quality pages used to parse that same JSON
    # document repeatedly.  Keep only a few recent, stat-validated reports so
    # page navigation is a metadata check instead of a second full decode.
    _CACHE_CAPACITY = 4
    _cache: "OrderedDict[Path, tuple[tuple[int, int], QualityReport]]" = OrderedDict()
    _cache_lock = RLock()

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
        self._remember(current, report)

    def load_current(self) -> QualityReport:
        path = self.project.path_for("quality_report")
        signature = self._signature(path)
        with self._cache_lock:
            cached = self._cache.get(path)
            if cached is not None and cached[0] == signature:
                self._cache.move_to_end(path)
                return cached[1]
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("quality report must contain a JSON object")
        report = QualityReport.from_dict(value)
        self._remember(path, report)
        return report

    @staticmethod
    def _signature(path: Path) -> tuple[int, int]:
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size

    @classmethod
    def _remember(cls, path: Path, report: QualityReport) -> None:
        try:
            signature = cls._signature(path)
        except OSError:
            return
        with cls._cache_lock:
            cls._cache[path] = (signature, report)
            cls._cache.move_to_end(path)
            while len(cls._cache) > cls._CACHE_CAPACITY:
                cls._cache.popitem(last=False)
