import unittest
from unittest.mock import patch

from app.diagnostics.bundle import validate_installation


class SmokeCapabilityTests(unittest.TestCase):
    def test_runtime_validation_can_check_only_embedded_desktop_capabilities(self) -> None:
        self.assertEqual(validate_installation(include_external=False), [])

    def test_embedded_check_does_not_require_external_analysis_or_build_tools(self) -> None:
        def fake_find_spec(module_name: str):
            return object() if module_name == "PySide6" else None

        with patch("app.diagnostics.bundle.find_spec", side_effect=fake_find_spec):
            self.assertEqual(validate_installation(include_external=False), [])
            issues = validate_installation(include_external=True)

        self.assertIn("missing runtime capability: NumPy (numpy)", issues)
        self.assertIn("missing runtime capability: Pose2Sim (Pose2Sim)", issues)


if __name__ == "__main__":
    unittest.main()
