import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit

from app.gui.widgets.config_parameter_editor import ConfigParameterEditor


CONFIG = """[project]
frame_rate = 'auto'
multi_person = false

[pose]
pose_model = 'Body_with_feet'
det_frequency = 4
device = 'auto'
"""


class ConfigParameterEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_tree_shows_chinese_help_without_source_english_comment(self) -> None:
        editor = ConfigParameterEditor()
        editor.set_text(CONFIG)

        item = editor.item_for(("pose", "pose_model"))

        self.assertIsNotNone(item)
        self.assertEqual(item.text(0), "ⓘ pose_model")
        self.assertIn("二维姿态模型", item.toolTip(0))
        self.assertNotIn("With RTMLib", item.toolTip(0))
        editor.close()

    def test_typed_editors_update_toml_source(self) -> None:
        editor = ConfigParameterEditor()
        editor.set_text(CONFIG)
        frequency = editor.editor_for(("pose", "det_frequency"))
        multi_person = editor.editor_for(("project", "multi_person"))

        self.assertIsInstance(frequency, QLineEdit)
        frequency.setText("2")
        frequency.editingFinished.emit()
        self.assertIsInstance(multi_person, QComboBox)
        multi_person.setCurrentText("true")

        self.assertIn("det_frequency = 2", editor.text())
        self.assertIn("multi_person = true", editor.text())
        editor.close()

    def test_custom_parameter_and_chinese_help_persist_for_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "中文项目"
            editor = ConfigParameterEditor()
            editor.set_project_root(root)
            editor.set_text(CONFIG)

            editor.add_custom_parameter(("pose",), "my_threshold", "0.75", "我的置信度阈值")

            reopened = ConfigParameterEditor()
            reopened.set_project_root(root)
            reopened.set_text(editor.text())
            item = reopened.item_for(("pose", "my_threshold"))
            self.assertIsNotNone(item)
            self.assertIn("我的置信度阈值", item.toolTip(0))
            self.assertIn("my_threshold = 0.75", reopened.text())
            editor.close()
            reopened.close()


if __name__ == "__main__":
    unittest.main()
