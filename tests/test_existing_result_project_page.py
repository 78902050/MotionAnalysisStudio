import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from app.gui.main_window import MainWindow
from app.gui.pages.project_page import ProjectPage


def _trial(root: Path, name: str) -> Path:
    trial = root / name
    pose = trial / "pose" / "cam01_json"
    pose.mkdir(parents=True)
    (pose / "cam01_000000.json").write_text(
        json.dumps({"version": 1.3, "people": []}),
        encoding="utf-8",
    )
    return trial


class ExistingResultProjectPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_project_page_has_separate_single_and_parent_import_actions(self) -> None:
        page = ProjectPage()

        self.assertIsNotNone(page.findChild(QPushButton, "project_import_existing_button"))
        self.assertIsNotNone(page.findChild(QPushButton, "project_scan_parent_button"))
        self.assertEqual(page.candidate_table.columnCount(), 8)

    def test_main_window_imports_one_processed_folder_and_opens_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trial = _trial(Path(directory), "单独试次")
            window = MainWindow()

            self.assertTrue(window.import_existing_path(trial))

            self.assertIsNotNone(window.project)
            self.assertEqual(window.project.root, trial.resolve())
            self.assertTrue((trial / "manifest.json").is_file())
            self.assertIn("单独试次", window.project_label.text())
            window.close()

    def test_parent_scan_runs_off_thread_and_populates_candidate_table(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / "data"
            first = _trial(parent / "8.14", "走路")
            second = _trial(parent / "8.15", "起跑")
            window = MainWindow()
            page = window._pages["project"]

            self.assertTrue(window.scan_existing_parent(parent))
            for _ in range(200):
                self.application.processEvents()
                if page.candidate_table.rowCount() == 2 and window._discovery_thread is None:
                    break
                QTest.qWait(10)

            self.assertEqual(page.candidate_table.rowCount(), 2)
            roots = {
                page.candidate_table.item(row, 1).data(256).root
                for row in range(page.candidate_table.rowCount())
            }
            self.assertEqual(roots, {first.resolve(), second.resolve()})
            self.assertIn("2", page.status.text())
            window.close()


if __name__ == "__main__":
    unittest.main()
