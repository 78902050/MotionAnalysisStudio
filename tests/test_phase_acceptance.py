import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.project.manager import ProjectManager


class PhaseAcceptanceTests(unittest.TestCase):
    def test_runtime_validation_and_smoke_entrypoint_are_available(self) -> None:
        from app.diagnostics.bundle import validate_installation
        from app.main import main

        self.assertEqual(validate_installation(), [])
        self.assertEqual(main(["--smoke-test"]), 0)

    def test_diagnostic_bundle_redacts_paths_and_excludes_project_inputs(self) -> None:
        from app.diagnostics.bundle import DiagnosticBundle

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "中文项目"
            project = ProjectManager.create(root, "诊断测试")
            project.manifest["workspace_root"] = str(root)
            project.manifest["source_path"] = str(root / "secret.mp4")
            project.save_manifest()
            (root / "logs" / "app.log").write_text(
                f"failed at {root}\\pose\\camA_000001.json\n", encoding="utf-8"
            )
            (root / "pose-3d" / "large-results.trc").write_text("do not bundle", encoding="utf-8")
            archive = DiagnosticBundle().create(project, root / "diagnostics.zip")

            with zipfile.ZipFile(archive) as handle:
                names = handle.namelist()
                payload = "\n".join(handle.read(name).decode("utf-8") for name in names)
            self.assertIn("manifest.json", names)
            self.assertIn("diagnostics/runtime.json", names)
            self.assertNotIn("pose-3d/large-results.trc", names)
            self.assertNotIn(str(root), payload)
            self.assertNotIn("secret.mp4", payload)

    def test_packaging_and_smoke_scripts_use_project_relative_paths(self) -> None:
        build_script = Path("scripts/build_windows.ps1").read_text(encoding="utf-8")
        smoke_script = Path("scripts/smoke_exe.ps1").read_text(encoding="utf-8")

        self.assertIn("PyInstaller", build_script)
        self.assertIn("app\\main.py", build_script)
        self.assertIn("--smoke-test", smoke_script)
        self.assertIn("MotionAnalysisStudio.exe", smoke_script)
        self.assertNotIn("D:\\CODEX\\2026-09-01\\ni", build_script + smoke_script)


if __name__ == "__main__":
    unittest.main()
