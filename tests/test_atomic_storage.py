import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.io.atomic import AtomicJsonStore
from app.io.jsonl import JsonlStore
from app.io.transactions import TransactionRecovery


class AtomicStorageTests(unittest.TestCase):
    def test_replace_failure_keeps_previous_json_readable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            path.write_text('{"value": 1}\n', encoding="utf-8")

            with patch("app.io.atomic.os.replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    AtomicJsonStore.replace(path, {"value": 2})

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"value": 1})

    def test_first_backup_is_exclusive_and_does_not_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "pose.json"
            backup = Path(directory) / "backups" / "pose.json"
            source.write_text('{"value": 1}\n', encoding="utf-8")

            self.assertTrue(AtomicJsonStore.backup_once(source, backup))
            source.write_text('{"value": 2}\n', encoding="utf-8")
            self.assertFalse(AtomicJsonStore.backup_once(source, backup))
            self.assertEqual(json.loads(backup.read_text(encoding="utf-8")), {"value": 1})

    def test_jsonl_reports_truncated_line_without_losing_valid_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.jsonl"
            store = JsonlStore(path)
            store.append({"id": "one"})
            path.open("a", encoding="utf-8").write('{"id": "broken"')

            records, errors = store.read()

            self.assertEqual(records, [{"id": "one"}])
            self.assertEqual(len(errors), 1)
            self.assertIn("line 2", errors[0])

    def test_transaction_recovery_reports_unfinished_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transactions.jsonl"
            path.write_text(
                '{"transaction_id":"tx-1","status":"started"}\n'
                '{"transaction_id":"tx-2","status":"started"}\n'
                '{"transaction_id":"tx-2","status":"completed"}\n',
                encoding="utf-8",
            )

            incomplete = TransactionRecovery(Path(directory)).recover_incomplete()

            self.assertEqual(incomplete, ["tx-1"])


if __name__ == "__main__":
    unittest.main()
