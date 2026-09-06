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


if __name__ == "__main__":
    unittest.main()
