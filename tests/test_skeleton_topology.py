import unittest

from app.visualization.skeleton import SkeletonTopologyRepository


HALPE_26_NAMES = (
    "Nose", "LEye", "REye", "LEar", "REar", "LShoulder", "RShoulder",
    "LElbow", "RElbow", "LWrist", "RWrist", "LHip", "RHip", "LKnee",
    "RKnee", "LAnkle", "RAnkle", "Head", "Neck", "Hip", "LBigToe",
    "RBigToe", "LSmallToe", "RSmallToe", "LHeel", "RHeel",
)


class SkeletonTopologyTests(unittest.TestCase):
    def test_halpe26_edges_are_semantic_names(self) -> None:
        edges = SkeletonTopologyRepository().edges_for("HALPE_26", HALPE_26_NAMES)

        self.assertIn(("LShoulder", "LElbow"), edges)
        self.assertIn(("LElbow", "LWrist"), edges)
        self.assertIn(("Hip", "LHip"), edges)
        self.assertTrue(all(left in HALPE_26_NAMES and right in HALPE_26_NAMES for left, right in edges))

    def test_unknown_model_and_insufficient_label_match_have_no_edges(self) -> None:
        repository = SkeletonTopologyRepository()
        self.assertEqual(repository.edges_for("CUSTOM", ("A", "B")), ())
        self.assertEqual(repository.edges_for_labels(("Hip", "Neck")), ())

    def test_label_only_matching_selects_halpe_for_complete_names(self) -> None:
        edges = SkeletonTopologyRepository().edges_for_labels(HALPE_26_NAMES)
        self.assertIn(("RKnee", "RAnkle"), edges)

    def test_augmented_marker_set_keeps_base_body_edges(self) -> None:
        augmented = (*HALPE_26_NAMES, *(f"extra-{index}" for index in range(39)))
        edges = SkeletonTopologyRepository().edges_for_labels(augmented)
        self.assertIn(("Hip", "LHip"), edges)
        self.assertIn(("RShoulder", "RElbow"), edges)

    def test_marker_augmented_halpe_without_face_points_keeps_body_edges(self) -> None:
        body = tuple(name for name in HALPE_26_NAMES if name not in {"LEye", "REye", "LEar", "REar"})
        edges = SkeletonTopologyRepository().edges_for_labels((*body, "r.ASIS_study"))
        self.assertEqual(len(edges), 21)


if __name__ == "__main__":
    unittest.main()
