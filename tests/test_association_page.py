import os
import json
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QTableWidget

from app.gui.main_window import MainWindow
from app.gui.pages.association_page import AssociationPage
from app.association.model import (
    AssociationCandidate,
    AssociationIssue,
    AssociationReport,
    SkeletonFingerprint,
)
from app.association.overrides import AssociationOverrideStore
from app.application.controller import ApplicationController
from app.project.manager import ProjectManager


class AssociationPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_main_window_registers_association_page_with_confirmation_actions(self) -> None:
        window = MainWindow()

        page = window._pages["association"]

        self.assertIsInstance(page, AssociationPage)
        self.assertIsNotNone(page.findChild(QTableWidget, "association_candidate_table"))
        self.assertIsNotNone(page.findChild(QPushButton, "association_confirm_button"))
        self.assertIsNotNone(page.findChild(QPushButton, "association_materialize_button"))
        self.assertIsNotNone(page.findChild(QPushButton, "association_restore_button"))

    def test_blocking_report_disables_confirmation_and_materialization(self) -> None:
        page = AssociationPage()
        candidate = AssociationCandidate(
            "candidate-1",
            "person-1",
            "camA",
            0,
            0,
            SkeletonFingerprint("pose2d", ("nose",), "hash"),
            0.5,
            "temporal",
            "时间连续性候选",
            False,
        )
        report = AssociationReport(
            (candidate,),
            (),
            (AssociationIssue("blocking", "质量输入阻断", code="quality_blocking"),),
        )

        page._project_id = "project-1"
        page._generation = 1
        page._analysis_finished("project-1", 1, report)
        page.candidate_table.selectRow(0)

        self.assertFalse(page.confirm_button.isEnabled())
        self.assertFalse(page.materialize_button.isEnabled())
        page.close()

    def test_materialization_runs_through_the_application_task_supervisor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory), "后台人物物化")
            output = project.root / "pose-associated" / "results.json"
            output.write_text(
                json.dumps(
                    {
                        "frames": [
                            {
                                "camera": "camA",
                                "frame": 0,
                                "people": [
                                    {
                                        "raw_person_index": 0,
                                        "keypoints": {"nose": {"x": 1, "y": 2, "confidence": 1}},
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            controller = ApplicationController()
            self.assertTrue(controller.open_project(project))
            page = AssociationPage(controller=controller)
            page.set_project(project)
            candidate = AssociationCandidate(
                "candidate-task",
                "person-1",
                "camA",
                0,
                0,
                SkeletonFingerprint("pose2d", ("nose",), "hash"),
                1.0,
                "exact",
                "已有人工关联",
                True,
                ("同帧语义一致",),
            )
            page.report = AssociationReport((candidate,), (), ())
            AssociationOverrideStore(project.root).save_confirmed(candidate)

            page.materialize()
            for _ in range(100):
                self.application.processEvents()
                if page._materialize_handle is None:
                    break
                QTest.qWait(10)

            self.assertTrue(any(item.name == "association-materialize" for item in controller.supervisor.snapshots()))
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["frames"][0]["people"][0]["project_person_id"], "person-1")
            self.assertTrue(controller.shutdown(dirty_decision="discard"))
            page.close()


if __name__ == "__main__":
    unittest.main()
