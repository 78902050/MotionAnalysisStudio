import json
import tempfile
import unittest
from pathlib import Path

from app.association.materializer import AssociationMaterializer
from app.association.model import AssociationOverride, SkeletonFingerprint
from app.project.manager import ProjectManager


class AssociationInvalidationTests(unittest.TestCase):
    def test_materializing_confirmed_association_invalidates_only_downstream_stages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory), "失效测试")
            project.manifest["stages"]["personAssociation"]["status"] = "completed"
            project.manifest["stages"]["triangulation"]["status"] = "completed"
            project.manifest["stages"]["kinematics"]["status"] = "completed"
            project.save_manifest()
            output = project.root / "pose-associated" / "results.json"
            output.write_text(
                json.dumps(
                    {"frames": [{"camera": "camA", "frame": 0, "people": [{"raw_person_index": 0, "keypoints": {"nose": {"x": 1, "y": 2, "confidence": 1}}}]}]},
                ),
                encoding="utf-8",
            )
            fingerprint = SkeletonFingerprint("pose2d", ("nose",), "hash")
            constraint = AssociationOverride("override-1", "person-1", "camA", 0, 0, fingerprint)

            result = AssociationMaterializer().materialize(project, (constraint,))

            self.assertTrue(result.succeeded)
            self.assertEqual(project.manifest["stages"]["personAssociation"]["status"], "completed")
            self.assertIn(project.manifest["stages"]["triangulation"]["status"], {"stale", "pending"})
            self.assertIn(project.manifest["stages"]["kinematics"]["status"], {"stale", "pending"})


if __name__ == "__main__":
    unittest.main()
