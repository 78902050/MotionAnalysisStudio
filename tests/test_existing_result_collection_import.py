import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.gui.main_window import MainWindow


def _trial(root: Path, name: str) -> Path:
    trial = root / name
    pose = trial / "pose" / "cam01_json"
    pose.mkdir(parents=True)
    (pose / "cam01_000000.json").write_text(
        json.dumps({"version": 1.3, "people": []}),
        encoding="utf-8",
    )
    return trial


class ExistingResultCollectionImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_single_folder_action_expands_a_collection_without_creating_root_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "多试次数据"
            first = _trial(root / "8.14", "走路")
            second = _trial(root / "8.15", "起跑")
            window = MainWindow()

            self.assertTrue(window.import_existing_path(root))
            page = window._pages["project"]
            for _ in range(300):
                self.application.processEvents()
                if window._discovery_thread is None:
                    break
                QTest.qWait(10)

            self.assertEqual(page.candidate_table.rowCount(), 2)
            candidates = {
                page.candidate_table.item(row, 1).data(256).root
                for row in range(page.candidate_table.rowCount())
            }
            self.assertEqual(candidates, {first.resolve(), second.resolve()})
            self.assertFalse((root / "manifest.json").exists())
            self.assertIn("多个", page.status.text())
            window.close()


if __name__ == "__main__":
    unittest.main()
