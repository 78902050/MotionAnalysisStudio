import unittest

from app.correction.model import CorrectionOperation, IssueDisposition
from app.domain.addresses import (
    CorrectionTarget,
    FrameAddress,
    KeypointAddress,
    PersonAddress,
)


class CorrectionModelTests(unittest.TestCase):
    def test_operation_round_trips_semantic_target_and_values(self) -> None:
        target = CorrectionTarget(
            FrameAddress("cam01", "pose2d", 12),
            PersonAddress("person-01", "segment-01", 1),
            KeypointAddress("coco17", "left_wrist", 9),
        )
        operation = CorrectionOperation(
            operation_id="op-1",
            session_id="session-1",
            target=target,
            before=(10.0, 20.0, 0.2),
            after=(11.0, 21.0, 1.0),
            note="人工确认",
            created_at="2026-09-04T00:00:00+00:00",
            source="manual",
        )

        restored = CorrectionOperation.from_dict(operation.to_dict())

        self.assertEqual(restored, operation)

    def test_issue_disposition_rejects_unknown_status(self) -> None:
        with self.assertRaises(ValueError):
            IssueDisposition("issue-1", "unknown")


if __name__ == "__main__":
    unittest.main()
