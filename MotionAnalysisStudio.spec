# -*- mode: python ; coding: utf-8 -*-

from importlib.util import find_spec
from pathlib import Path


project_root = Path(SPECPATH).resolve()
openvino_module = find_spec("openvino")
if openvino_module is None or openvino_module.origin is None:
    raise RuntimeError("OpenVINO is required to build MotionAnalysisStudio")
openvino_root = Path(openvino_module.origin).resolve().parent
openvino_onnx_frontend = openvino_root / "libs" / "openvino_onnx_frontend.dll"
openvino_cpu_plugin = openvino_root / "libs" / "openvino_intel_cpu_plugin.dll"
required_openvino_binaries = (openvino_onnx_frontend, openvino_cpu_plugin)
missing_openvino_binaries = [path for path in required_openvino_binaries if not path.is_file()]
if missing_openvino_binaries:
    raise FileNotFoundError(
        "Required OpenVINO runtime files were not found: "
        + ", ".join(str(path) for path in missing_openvino_binaries)
    )
required_binaries = [(str(path), "openvino/libs") for path in required_openvino_binaries]

a = Analysis(
    [str(project_root / "app" / "main.py")],
    pathex=[str(project_root)],
    binaries=required_binaries,
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)


def is_incompatible_poppler_icu(entry):
    name, source, _kind = entry
    normalized_name = Path(name).name.lower()
    normalized_source = str(source).replace("\\", "/").lower()
    is_icu = normalized_name in {"icuuc.dll", "icuin.dll"} or (
        normalized_name.startswith("icudt") and normalized_name.endswith(".dll")
    )
    return is_icu and "/poppler/" in normalized_source


a.binaries = [entry for entry in a.binaries if not is_incompatible_poppler_icu(entry)]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="MotionAnalysisStudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
