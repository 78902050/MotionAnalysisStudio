# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


project_root = Path(SPECPATH).resolve()

a = Analysis(
    [str(project_root / "app" / "main.py")],
    pathex=[str(project_root)],
    binaries=[],
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
