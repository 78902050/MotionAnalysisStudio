import unittest

from app import project_version, runtime_capabilities


class BootstrapContractTests(unittest.TestCase):
    def test_package_reports_version_and_no_development_path(self) -> None:
        version = project_version()
        capabilities = runtime_capabilities()

        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        self.assertIsInstance(capabilities, dict)
        self.assertTrue(capabilities)
        for key, value in capabilities.items():
            self.assertIsInstance(key, str)
            self.assertIsInstance(value, bool)
        self.assertNotIn("D:\\CODEX\\2026-09-01\\ni", repr(capabilities))


if __name__ == "__main__":
    unittest.main()
