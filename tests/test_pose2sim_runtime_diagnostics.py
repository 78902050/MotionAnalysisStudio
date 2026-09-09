import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from app.pose2sim.runtime_diagnostics import (
    PoseRuntimeReport,
    classify_pose2sim_failure,
    inspect_openvino_runtime,
)


class Pose2SimRuntimeDiagnosticsTests(unittest.TestCase):
    def test_runtime_report_rejects_frontends_without_onnx(self) -> None:
        report = inspect_openvino_runtime(
            frontend_names=("jax", "pytorch"), device_names=("CPU",)
        )

        self.assertFalse(report.ok)
        self.assertEqual(report.available_frontends, ("jax", "pytorch"))
        self.assertIn("缺少 OpenVINO ONNX 前端", report.user_message)
        self.assertIn("MAS_POSE_RUNTIME_ONNX_MISSING", report.technical_detail)

    def test_runtime_report_accepts_onnx_frontend_and_sorts_names(self) -> None:
        report = inspect_openvino_runtime(
            frontend_names=("pytorch", "ONNX", "jax"), device_names=("CPU",)
        )

        self.assertTrue(report.ok)
        self.assertEqual(report.available_frontends, ("jax", "onnx", "pytorch"))
        self.assertIn("可用", report.user_message)

    def test_runtime_report_rejects_onnx_frontend_without_cpu_device(self) -> None:
        report = inspect_openvino_runtime(
            frontend_names=("onnx", "pytorch"), device_names=()
        )

        self.assertFalse(report.ok)
        self.assertIn("CPU 推理插件", report.user_message)
        self.assertIn("MAS_POSE_RUNTIME_CPU_MISSING", report.technical_detail)

    def test_real_log_signature_is_classified_as_missing_onnx_frontend(self) -> None:
        message = classify_pose2sim_failure(
            "Available frontends: jax pytorch\n"
            "Exception while reading model yolox_m.onnx",
            "poseEstimation",
        )

        self.assertIsNotNone(message)
        self.assertIn("缺少 OpenVINO ONNX 前端", message)

    def test_unknown_failure_is_not_misclassified(self) -> None:
        self.assertIsNone(
            classify_pose2sim_failure("unexpected worker failure", "poseEstimation")
        )

    def test_unregistered_cpu_log_is_classified_as_missing_cpu_plugin(self) -> None:
        message = classify_pose2sim_failure(
            'Device with "CPU" name is not registered in the OpenVINO Runtime',
            "poseEstimation",
        )

        self.assertIsNotNone(message)
        self.assertIn("CPU 推理插件", message)

    def test_runtime_check_cli_returns_success_and_lists_frontends(self) -> None:
        from app.main import main

        report = PoseRuntimeReport(
            True,
            ("onnx", "pytorch"),
            "Pose2Sim 二维姿态运行时可用",
            available_devices=("CPU",),
        )
        stdout = io.StringIO()
        with patch("app.main.inspect_openvino_runtime", return_value=report), redirect_stdout(stdout):
            result = main(["--pose2sim-runtime-check"])

        self.assertEqual(result, 0)
        self.assertIn("onnx", stdout.getvalue())
        self.assertIn("CPU", stdout.getvalue())

    def test_runtime_check_cli_returns_failure_with_actionable_message(self) -> None:
        from app.main import main

        report = PoseRuntimeReport(
            False,
            ("jax", "pytorch"),
            "缺少 OpenVINO ONNX 前端",
            "MAS_POSE_RUNTIME_ONNX_MISSING",
            ("CPU",),
        )
        stderr = io.StringIO()
        with patch("app.main.inspect_openvino_runtime", return_value=report), redirect_stderr(stderr):
            result = main(["--pose2sim-runtime-check"])

        self.assertEqual(result, 1)
        self.assertIn("缺少 OpenVINO ONNX 前端", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
