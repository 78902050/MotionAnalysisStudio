"""Runtime checks and actionable failure messages for Pose2Sim pose estimation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


ONNX_MISSING_MARKER = "MAS_POSE_RUNTIME_ONNX_MISSING"
CPU_MISSING_MARKER = "MAS_POSE_RUNTIME_CPU_MISSING"


@dataclass(frozen=True)
class PoseRuntimeReport:
    ok: bool
    available_frontends: tuple[str, ...]
    user_message: str
    technical_detail: str = ""
    available_devices: tuple[str, ...] = ()


def inspect_openvino_runtime(
    *,
    frontend_names: Iterable[str] | None = None,
    device_names: Iterable[str] | None = None,
) -> PoseRuntimeReport:
    """Report whether the current process can load OpenVINO ONNX models."""

    if frontend_names is None or device_names is None:
        try:
            if frontend_names is None:
                from openvino.frontend import FrontEndManager

                frontend_names = FrontEndManager().get_available_front_ends()
            if device_names is None:
                from openvino import Core

                device_names = Core().available_devices
        except Exception as exc:
            return PoseRuntimeReport(
                False,
                (),
                "无法加载 OpenVINO 运行组件，请检查 Pose2Sim 运行环境或重新安装软件。",
                f"{type(exc).__name__}: {exc}",
            )
    names = tuple(sorted({str(name).strip().casefold() for name in frontend_names if str(name).strip()}))
    devices = tuple(sorted({str(name).strip().upper() for name in device_names if str(name).strip()}))
    if "onnx" not in names:
        return PoseRuntimeReport(
            False,
            names,
            "缺少 OpenVINO ONNX 前端，无法读取 Pose2Sim 二维姿态模型；请更新软件安装包或所选 Pose2Sim 环境。",
            f"{ONNX_MISSING_MARKER}; available_frontends={','.join(names) or '<none>'}",
            devices,
        )
    if not any(device == "CPU" or device.startswith("CPU.") for device in devices):
        return PoseRuntimeReport(
            False,
            names,
            "缺少 OpenVINO CPU 推理插件，Pose2Sim 无法在当前电脑的 CPU 上执行二维姿态估计；请更新软件安装包或所选 Pose2Sim 环境。",
            f"{CPU_MISSING_MARKER}; available_devices={','.join(devices) or '<none>'}",
            devices,
        )
    return PoseRuntimeReport(
        True,
        names,
        "Pose2Sim 二维姿态运行时可用。",
        f"available_frontends={','.join(names)}; available_devices={','.join(devices)}",
        devices,
    )


def require_pose_estimation_runtime() -> None:
    """Raise an actionable error when ONNX models cannot be loaded."""

    report = inspect_openvino_runtime()
    if not report.ok:
        detail = f" [{report.technical_detail}]" if report.technical_detail else ""
        raise RuntimeError(f"{report.user_message}{detail}")


def classify_pose2sim_failure(log_text: str, stage: str | None) -> str | None:
    """Classify supported Pose2Sim failures without guessing beyond log evidence."""

    if stage not in {None, "poseEstimation"}:
        return None
    text = str(log_text)
    folded = text.casefold()
    if ONNX_MISSING_MARKER.casefold() in folded:
        return "缺少 OpenVINO ONNX 前端，当前运行环境无法读取 Pose2Sim 的 ONNX 模型。"
    if CPU_MISSING_MARKER.casefold() in folded or (
        'device with "cpu" name is not registered' in folded
        or "device with 'cpu' name is not registered" in folded
    ):
        return "缺少 OpenVINO CPU 推理插件，当前运行环境无法在 CPU 上执行 Pose2Sim 二维姿态估计。"

    match = re.search(r"available frontends\s*:\s*([^\r\n]+)", text, re.IGNORECASE)
    if match is not None:
        frontends = {
            token.casefold()
            for token in re.findall(r"[A-Za-z0-9_]+", match.group(1))
        }
        if "onnx" not in frontends and ".onnx" in folded:
            return "缺少 OpenVINO ONNX 前端，当前运行环境无法读取 Pose2Sim 的 ONNX 模型。"

    if ".onnx" in folded and any(
        marker in folded
        for marker in (
            "http error",
            "sslerror",
            "connectionerror",
            "connection timed out",
            "download failed",
        )
    ):
        return "Pose2Sim 模型下载失败，请检查网络连接和模型缓存目录的写入权限。"

    if ".onnx" in folded and "read_model" in folded and any(
        marker in folded
        for marker in ("invalid", "corrupt", "parse", "unexpected end")
    ):
        return "OpenVINO 无法解析已缓存的 ONNX 模型，模型缓存文件可能不完整或已损坏。"

    if any(
        marker in folded
        for marker in ("could not open video", "cannot open video", "failed to open video")
    ):
        return "Pose2Sim 无法打开分析视频，请检查视频路径、文件完整性和系统解码支持。"
    return None
