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

    def test_import_file_replaces_project_copy_without_changing_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "project" / "config" / "Config.toml"
            path.parent.mkdir(parents=True)
            original = "[project]\nname = \"old\"\n"
            imported = "# imported\n[project]\nname = \"new\"\n"
            path.write_text(original, encoding="utf-8")
            source = root / "外部配置" / "Config.toml"
            source.parent.mkdir()
            source.write_text(imported, encoding="utf-8")
            source_before = source.read_bytes()
            document = ConfigDocument.open(path)

            result = document.import_file(source)

            self.assertEqual(path.read_text(encoding="utf-8"), imported)
            self.assertEqual(source.read_bytes(), source_before)
            self.assertIsNotNone(result.backup_path)
            self.assertEqual(result.backup_path.read_text(encoding="utf-8"), original)

    def test_invalid_import_does_not_change_project_copy_or_create_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "config" / "Config.toml"
            path.parent.mkdir()
            original = "[project]\nname = \"safe\"\n"
            path.write_text(original, encoding="utf-8")
            source = root / "invalid.toml"
            source.write_text("[project\n", encoding="utf-8")
            document = ConfigDocument.open(path)

            with self.assertRaises(ConfigSyntaxError):
                document.import_file(source)

            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertEqual(list(path.parent.glob("backups/*")), [])


if __name__ == "__main__":
    unittest.main()
