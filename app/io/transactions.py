"""Detection of incomplete file transactions."""

from pathlib import Path

from .jsonl import JsonlStore


class TransactionRecovery:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.store = JsonlStore(self.root / "transactions.jsonl")

    def recover_incomplete(self) -> list[str]:
        records, errors = self.store.read()
        if errors:
            raise ValueError("invalid transaction journal: " + "; ".join(errors))

        latest: dict[str, str] = {}
        order: list[str] = []
        for record in records:
            transaction_id = record.get("transaction_id")
            status = record.get("status")
            if not isinstance(transaction_id, str) or not transaction_id.strip():
                raise ValueError("transaction journal record has no transaction_id")
            if not isinstance(status, str) or not status.strip():
                raise ValueError(f"transaction {transaction_id} has no status")
            if transaction_id not in latest:
                order.append(transaction_id)
            latest[transaction_id] = status
        return [transaction_id for transaction_id in order if latest[transaction_id] != "completed"]
