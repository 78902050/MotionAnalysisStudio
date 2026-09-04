import importlib
import importlib.util
import unittest


class PipelineDependencyGraphTests(unittest.TestCase):
    def _graph(self):
        module_name = "app.pipeline.dependency_graph"
        self.assertIsNotNone(
            importlib.util.find_spec(module_name),
            "the pipeline dependency graph is not centralized",
        )
        return importlib.import_module(module_name).StageGraph()

    def test_two_dimensional_correction_starts_at_person_association(self) -> None:
        stages = self._graph().rerun_stages_for("2d_correction")

        self.assertEqual(stages[0], "personAssociation")
        self.assertNotIn("poseEstimation", stages)

    def test_synchronization_change_invalidates_synchronization_and_all_downstream(self) -> None:
        affected = self._graph().invalidate_from("synchronization", "mapping changed")

        self.assertEqual(affected[0], "synchronization")
        self.assertIn("poseEstimation", affected)
        self.assertEqual(affected[-1], "comparison")


if __name__ == "__main__":
    unittest.main()
