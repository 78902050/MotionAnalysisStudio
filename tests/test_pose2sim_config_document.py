import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.pose2sim.config_document import ConfigDocument, ConfigSyntaxError


class Pose2SimConfigDocumentTests(unittest.TestCase):
    def test_empty_and_invalid_config_are_not_runnable_or_saved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config" / "Config.toml"
            path.parent.mkdir()
            path.write_text("", encoding="utf-8")
            document = ConfigDocument.open(path)

            self.assertFalse(document.validate("").valid)
            self.assertFalse(document.validate("[project\n").valid)
            with self.assertRaises(ConfigSyntaxError):
                document.save("[project\n", "invalid")

            self.assertEqual(path.read_text(encoding="utf-8"), "")
            self.assertEqual(list(path.parent.glob("backups/*")), [])

    def test_save_preserves_exact_text_and_creates_distinct_backups(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config" / "Config.toml"
            path.parent.mkdir()
            original = "# 原注释\n[project]\nname = \"原项目\"\n"
            first = "# 保留注释\n[project]\nname = \"动作一\"\n"
            second = "# 保留注释\r\n[project]\r\nname = \"动作二\"\r\n"
            path.write_text(original, encoding="utf-8", newline="")
            document = ConfigDocument.open(path)

            first_result = document.save(first, "第一次编辑")
            second_result = document.save(second, "第二次编辑")

            self.assertEqual(path.read_bytes(), second.encode("utf-8"))
            self.assertNotEqual(first_result.backup_path, second_result.backup_path)
            self.assertEqual(first_result.backup_path.read_bytes(), original.encode("utf-8"))
            self.assertEqual(second_result.backup_path.read_bytes(), first.encode("utf-8"))
            self.assertFalse(document.has_unsaved_changes(second))

    def test_reload_discards_editor_text_and_returns_disk_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Config.toml"
            path.write_text("[project]\nname = \"A\"\n", encoding="utf-8")
            document = ConfigDocument.open(path)
            path.write_text("[project]\nname = \"B\"\n", encoding="utf-8")

            reloaded = document.reload()

            self.assertIn('name = "B"', reloaded)
            self.assertFalse(document.has_unsaved_changes(reloaded))

    def test_replace_failure_leaves_previous_config_readable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Config.toml"
            original = "[project]\nname = \"safe\"\n"
            path.write_text(original, encoding="utf-8")
            document = ConfigDocument.open(path)

            with patch("app.pose2sim.config_document.os.replace", side_effect=OSError("locked")):
                with self.assertRaisesRegex(OSError, "locked"):
                    document.save("[project]\nname = \"new\"\n", "replace failure")

            self.assertEqual(path.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
