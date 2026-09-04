import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.io import transactions
from app.io.transactions import TransactionRecovery


class ProjectTransactionTests(unittest.TestCase):
    def _transaction_type(self):
        self.assertTrue(
            hasattr(transactions, "ProjectTransaction"),
            "ProjectTransaction must stage and recover multi-file updates",
        )
        return transactions.ProjectTransaction

    def test_successful_transaction_replaces_all_files(self) -> None:
        transaction_type = self._transaction_type()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "data" / "first.json"
            second = root / "data" / "second.json"
            first.parent.mkdir()
            first.write_text('{"value": 1}\n', encoding="utf-8")
            second.write_text('{"value": 2}\n', encoding="utf-8")
            transaction = transaction_type(root, transaction_id="tx-success")
            transaction.prepare_json("data/first.json", {"value": 10})
            transaction.prepare_json("data/second.json", {"value": 20})

            transaction.commit()

            self.assertEqual(json.loads(first.read_text(encoding="utf-8")), {"value": 10})
            self.assertEqual(json.loads(second.read_text(encoding="utf-8")), {"value": 20})
            self.assertEqual(TransactionRecovery(root).recover_all(), [])

    def test_failure_after_first_replace_is_rolled_back_on_reopen(self) -> None:
        transaction_type = self._transaction_type()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "data" / "first.json"
            second = root / "data" / "second.json"
            first.parent.mkdir()
            first.write_text('{"value": 1}\n', encoding="utf-8")
            second.write_text('{"value": 2}\n', encoding="utf-8")
            transaction = transaction_type(root, transaction_id="tx-failure")
            transaction.prepare_json("data/first.json", {"value": 10})
            transaction.prepare_json("data/second.json", {"value": 20})
            real_replace = os.replace
            replace_count = 0

            def fail_second_replace(source, destination):
                nonlocal replace_count
                replace_count += 1
                if replace_count == 2:
                    raise OSError("injected disk failure")
                return real_replace(source, destination)

            with patch("app.io.transactions.os.replace", side_effect=fail_second_replace):
                with self.assertRaises(OSError):
                    transaction.commit()

            self.assertEqual(json.loads(first.read_text(encoding="utf-8")), {"value": 10})
            recovered = TransactionRecovery(root).recover_all()

            self.assertEqual(recovered, ["tx-failure"])
            self.assertEqual(json.loads(first.read_text(encoding="utf-8")), {"value": 1})
            self.assertEqual(json.loads(second.read_text(encoding="utf-8")), {"value": 2})
            self.assertEqual(TransactionRecovery(root).recover_all(), [])

    def test_transaction_rejects_target_outside_project(self) -> None:
        transaction_type = self._transaction_type()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            root.mkdir()
            transaction = transaction_type(root, transaction_id="tx-escape")

            with self.assertRaises(ValueError):
                transaction.prepare_json("../outside.json", {"value": 1})


if __name__ == "__main__":
    unittest.main()
