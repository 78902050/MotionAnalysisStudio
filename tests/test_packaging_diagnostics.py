import os
import subprocess
import tempfile
import unittest
from importlib import import_module
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class PackagingDiagnosticsTests(unittest.TestCase):
    def test_gui_smoke_loads_qt_and_constructs_main_window(self) -> None:
        bundle = import_module("app.diagnostics.bundle")
        self.assertTrue(hasattr(bundle, "run_gui_smoke"), "run_gui_smoke must exercise the real Qt GUI stack")

        result = bundle.run_gui_smoke()

        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.checks, ("QtWidgets import", "QApplication", "MainWindow"))

    def test_gui_smoke_entrypoint_returns_success(self) -> None:
        from app.main import main

        try:
            result = main(["--gui-smoke-test"])
        except SystemExit as exc:
            self.fail(f"--gui-smoke-test is not implemented: {exc}")
        self.assertEqual(result, 0)

    def test_workflow_smoke_includes_existing_results_and_pipeline_interfaces(self) -> None:
        from app.diagnostics.bundle import run_workflow_smoke

        result = run_workflow_smoke()

        self.assertTrue(result.ok, result.message)
        self.assertIn("existing results", result.checks)
        self.assertIn("pipeline interface", result.checks)

    def test_dll_audit_rejects_poppler_icu_selected_for_bundle(self) -> None:
        completed = self._run_dll_audit(
            "('icuuc.dll', 'C:\\\\tools\\\\poppler\\\\Library\\\\bin\\\\icuuc.dll', 'BINARY')"
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("incompatible Poppler ICU", completed.stderr + completed.stdout)

    def test_dll_audit_accepts_bundle_without_poppler_icu(self) -> None:
        completed = self._run_dll_audit(
            "('PySide6\\\\Qt6Core.dll', 'C:\\\\venv\\\\PySide6\\\\Qt6Core.dll', 'BINARY')"
        )

        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        self.assertIn("DLL audit passed", completed.stdout)

    def _run_dll_audit(self, toc_text: str) -> subprocess.CompletedProcess[str]:
        script = Path("scripts/audit_dist_dlls.ps1").resolve()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work = root / "work" / "MotionAnalysisStudio"
            dist = root / "dist"
            work.mkdir(parents=True)
            dist.mkdir()
            (work / "Analysis-00.toc").write_text(toc_text, encoding="utf-8")
            return subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-WorkRoot",
                    str(root / "work"),
                    "-Dist",
                    str(dist),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )


if __name__ == "__main__":
    unittest.main()
