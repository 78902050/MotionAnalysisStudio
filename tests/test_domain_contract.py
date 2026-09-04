import unittest

from app.domain.addresses import (
    CorrectionTarget,
    FrameAddress,
    KeypointAddress,
    PersonAddress,
)
from app.domain.stages import StageGraph


class DomainContractTests(unittest.TestCase):
    def test_frame_address_rejects_empty_camera_unknown_timeline_and_negative_frame(self) -> None:
        with self.assertRaises(ValueError):
            FrameAddress("", "raw", 0)
        with self.assertRaises(ValueError):
            FrameAddress("cam01", "unknown", 0)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            FrameAddress("cam01", "raw", -1)

    def test_correction_target_keeps_semantic_person_and_keypoint(self) -> None:
        address = FrameAddress("cam01", "pose3d", 42)
        person = PersonAddress("person-01", track_segment_id="segment-a", raw_person_index=3)
        keypoint = KeypointAddress("coco-17", "left_wrist", source_index=9)
        target = CorrectionTarget(address, person, keypoint)

        self.assertEqual(target.person.project_person_id, "person-01")
        self.assertEqual(target.keypoint.keypoint_name, "left_wrist")
        self.assertEqual(target.address.frame, 42)

    def test_stage_graph_returns_explicit_dependencies_and_selective_rerun(self) -> None:
        graph = StageGraph()

        self.assertEqual(graph.dependencies("triangulation"), ("personAssociation",))
        rerun = graph.rerun_stages_for("2d_correction")
        self.assertEqual(
            rerun,
            (
                "personAssociation",
                "triangulation",
                "filtering",
                "markerAugmentation",
                "kinematics",
                "events",
                "comparison",
            ),
        )
        self.assertNotIn("poseEstimation", rerun)

    def test_stage_graph_invalidation_includes_downstream_stages(self) -> None:
        graph = StageGraph()

        invalidated = graph.invalidate_from("personAssociation", "identity review", "op-1")

        self.assertEqual(
            invalidated,
            [
                "personAssociation",
                "triangulation",
                "filtering",
                "markerAugmentation",
                "kinematics",
                "events",
                "comparison",
            ],
        )

    def test_unknown_stage_or_change_is_rejected(self) -> None:
        graph = StageGraph()

        with self.assertRaises(ValueError):
            graph.dependencies("not-a-stage")
        with self.assertRaises(ValueError):
            graph.rerun_stages_for("future-change")


if __name__ == "__main__":
    unittest.main()
