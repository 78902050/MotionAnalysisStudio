# 可读主题与可移植 Pose2Sim 运行时实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 提供清晰可调的浅色/深色界面，并确保冻结 EXE 能在没有开发环境的电脑上通过 OpenVINO 读取 ONNX 模型并运行 Pose2Sim 二维姿态估计。

**Architecture:** GUI 使用集中式语义调色板、应用级字体和控件 `uiRole` 属性，设置保存后原位刷新；自绘二维/三维画布从同一调色板取色。Pose2Sim 使用独立运行时探针，在实际执行环境中检查 ONNX 前端和 CPU 设备；PyInstaller 精确收集 ONNX 前端与 CPU 插件，构建审计、冻结运行时检查和官方示例短帧推理共同构成发布门禁。

**Tech Stack:** Python 3.12、PySide6、PyInstaller、OpenVINO、Pose2Sim、RTMLib、PowerShell、unittest

**Spec:** `docs/superpowers/specs/2026-09-09-accessible-theme-and-portable-pose2sim-design.md`

## Global Constraints

- 不修改已安装的 Pose2Sim、RTMLib、OpenVINO 或 Caliscope 源代码。
- 不修改 Pose2Sim 官方示例源目录；验证只操作临时副本。
- 不自动删除模型缓存，不无差别打包无关 OpenVINO 插件。
- 所有新增或变更的生产行为必须先写失败测试并确认因预期原因失败。
- 保留现有项目格式、视频、分析结果和用户的四份未跟踪审查文档。
- GUI 仍需支持 1120×720 和 620×480，字号上限 16pt 时所有操作可访问。
- 使用现有 `.venv` 和 `unittest`，不为本任务更换测试框架。

---

### Task 1: OpenVINO 运行时探针与真实日志分类

**Files:**
- Create: `app/pose2sim/runtime_diagnostics.py`
- Modify: `app/main.py`
- Create: `tests/test_pose2sim_runtime_diagnostics.py`

**Interfaces:**
- Produces: `PoseRuntimeReport`, `inspect_openvino_runtime()`, `require_pose_estimation_runtime()`, `classify_pose2sim_failure(log_text, stage)`。
- Produces: CLI `--pose2sim-runtime-check`，成功返回 0，失败返回 1。

- [x] **Step 1: Write the failing runtime-probe tests**

```python
def test_runtime_report_rejects_frontends_without_onnx():
    report = inspect_openvino_runtime(frontend_names=("jax", "pytorch"))
    self.assertFalse(report.ok)
    self.assertIn("ONNX", report.user_message)

def test_runtime_report_accepts_onnx_frontend():
    report = inspect_openvino_runtime(frontend_names=("pytorch", "onnx"))
    self.assertTrue(report.ok)
    self.assertEqual(report.available_frontends, ("onnx", "pytorch"))

def test_real_log_is_classified_as_missing_onnx_frontend():
    message = classify_pose2sim_failure(
        "Available frontends: jax pytorch\nread_model failed for model.onnx",
        "poseEstimation",
    )
    self.assertIn("缺少 OpenVINO ONNX", message)
```

- [x] **Step 2: Run the focused tests and confirm RED**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_pose2sim_runtime_diagnostics.py" -v`
Expected: import fails because `app.pose2sim.runtime_diagnostics` does not exist.

- [x] **Step 3: Implement the minimal diagnostic module**

Implement the dataclass and pure `frontend_names` path first; when names are omitted, lazily import
`openvino.frontend.FrontEndManager` and `openvino.Core`. Sort and normalize names. Return the fixed markers
`MAS_POSE_RUNTIME_ONNX_MISSING` or `MAS_POSE_RUNTIME_CPU_MISSING` when the corresponding capability is absent. Classify only evidence present
in the log and return `None` for unknown failures.

- [x] **Step 4: Add and verify the CLI entry test**

```python
with patch("app.main.inspect_openvino_runtime", return_value=PoseRuntimeReport(True, ("onnx",), "运行时可用")):
    self.assertEqual(main(["--pose2sim-runtime-check"]), 0)
```

Run before implementation and confirm failure because the argument is unknown; then add the parser branch,
print the report message plus frontends, and rerun until green.

- [x] **Step 5: Run focused and packaging smoke regression**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_pose2sim_runtime_diagnostics.py" -v`
Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_packaging_diagnostics.py" -v`

### Task 2: 在实际 Pose2Sim 执行环境中强制预检并改善失败说明

**Files:**
- Modify: `app/main.py`
- Modify: `app/application/pipeline_launcher.py`
- Modify: `tests/test_pose2sim_pipeline.py`
- Create: `tests/test_pose2sim_failure_reporting.py`

**Interfaces:**
- Consumes: `require_pose_estimation_runtime()`、`classify_pose2sim_failure()`。
- Produces: `build_pipeline_commands()` 生成的内置和外部 Python 命令都在 `poseEstimation` 前检查 ONNX 与 CPU。

- [x] **Step 1: Write failing tests for bundled and external commands**

```python
def test_bundled_pose_estimation_checks_runtime_before_pose2sim_import():
    with patch("app.main.require_pose_estimation_runtime") as check, patch.dict(
        sys.modules, {"Pose2Sim.Pose2Sim": fake_pose2sim_module}
    ):
        run_pose2sim_stage("poseEstimation", config, project)
    check.assert_called_once_with()

def test_external_python_pose_estimation_command_contains_onnx_preflight():
    command = build_pipeline_commands(config, ("poseEstimation",), project_root=project, pose2sim_python=python)["poseEstimation"]
    self.assertIn("FrontEndManager", command[2])
    self.assertIn("MAS_POSE_RUNTIME_ONNX_MISSING", command[2])
```

- [x] **Step 2: Verify RED**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_pose2sim_pipeline.py" -v`
Expected: bundled check is never called and generated external script lacks the marker.

- [x] **Step 3: Implement environment-correct preflight**

Call `require_pose_estimation_runtime()` in `run_pose2sim_stage` only for `poseEstimation`, before importing
Pose2Sim. Add the equivalent compact OpenVINO check to the external interpreter script; do not inspect the
GUI process when a different Python executable is configured.

- [x] **Step 4: Write failing tests for user-facing failure classification**

Create a real temporary log with the supplied error signature, return a failed `RunResult`, and assert that
the task error contains “缺少 OpenVINO ONNX 前端” and the absolute log path. Add an unknown-error case that
retains stage and exit-code information.

- [x] **Step 5: Implement bounded log-tail classification**

After the runner returns a failed result, read at most the final 256 KiB of its UTF-8 log, call
`classify_pose2sim_failure`, and use the classified message when available. Keep the original log and
manifest failure fields unchanged.

- [x] **Step 6: Run focused regressions**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_pose2sim_pipeline.py" -v`
Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_pose2sim_failure_reporting.py" -v`
Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_pipeline_page.py" -v`

### Task 3: 精确打包并审计 OpenVINO ONNX 前端和 CPU 插件

**Files:**
- Modify: `MotionAnalysisStudio.spec`
- Modify: `scripts/audit_dist_dlls.ps1`
- Modify: `tests/test_packaging_diagnostics.py`

**Interfaces:**
- Produces: PyInstaller binary entries `openvino/libs/openvino_onnx_frontend.dll` and `openvino/libs/openvino_intel_cpu_plugin.dll`。
- Produces: DLL 审计在 ONNX 前端或 CPU 插件缺失时非零退出。

- [x] **Step 1: Write the failing DLL-audit test**

```python
def test_dll_audit_rejects_bundle_without_openvino_onnx_frontend(self):
    completed = self._run_dll_audit(
        "('openvino\\libs\\openvino_pytorch_frontend.dll', 'C:\\\\venv\\\\openvino_pytorch_frontend.dll', 'BINARY')"
    )
    self.assertNotEqual(completed.returncode, 0)
    self.assertIn("openvino_onnx_frontend.dll", completed.stderr + completed.stdout)
```

Update the existing success fixture to include the ONNX frontend.

- [x] **Step 2: Verify RED**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_packaging_diagnostics.py" -v`
Expected: current audit exits 0.

- [x] **Step 3: Implement the audit requirement**

Scan all discovered `Analysis-00.toc` contents case-insensitively. If none contains
`openvino_onnx_frontend.dll` or `openvino_intel_cpu_plugin.dll`, emit a precise error and exit 1. Preserve the Poppler ICU check.

- [x] **Step 4: Add the exact spec collection**

Resolve the OpenVINO package directory at spec execution time, require
`libs/openvino_onnx_frontend.dll` and `libs/openvino_intel_cpu_plugin.dll`, and append exactly those files
to `binaries` under `openvino/libs` before `Analysis`. Do not collect all frontends or device plugins.

- [x] **Step 5: Run packaging tests**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_packaging_diagnostics.py" -v`

### Task 4: 集中式调色板、字号偏好和对比度

**Files:**
- Create: `app/gui/theme.py`
- Modify: `app/gui/style.py`
- Create: `tests/test_gui_theme.py`

**Interfaces:**
- Produces: `ThemePalette`, `UiPreferences`, `load_ui_preferences`, `save_ui_preferences`,
  `resolve_palette`, `build_stylesheet`, `apply_theme`, `palette_for_application`。
- Preserves: `apply_style(application, settings=None)` compatibility wrapper.

- [x] **Step 1: Write failing tests for defaults, persistence and bounds**

```python
def test_new_settings_default_to_light_twelve_point_text():
    prefs = load_ui_preferences(self.settings)
    self.assertEqual(prefs, UiPreferences("light", 12))

def test_font_size_is_clamped_to_supported_range():
    self.settings.setValue("ui/font_point_size", 99)
    self.assertEqual(load_ui_preferences(self.settings).font_point_size, 16)
```

- [x] **Step 2: Verify RED, then implement immutable preferences and palettes**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_gui_theme.py" -v`
Expected: module import failure. Implement only preference parsing, save/load and the two approved palettes.

- [x] **Step 3: Add failing contrast tests**

Convert literal hex colors to relative luminance in the test and assert text/window and text/panel ratios are
at least 4.5 for both palettes. The expected threshold is independent of production code.

- [x] **Step 4: Build semantic QSS and application font**

Generate selectors for page title, section title, body, muted, accent, warning and error `uiRole` values,
plus lists, tables, editors, buttons, scroll areas, splitters, focus and disabled states. `apply_theme` sets a
`QFont` point size, the stylesheet and application properties `masTheme` and `masFontPointSize`.

- [x] **Step 5: Run theme tests**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_gui_theme.py" -v`

### Task 5: 设置页集成和即时主题刷新

**Files:**
- Modify: `app/gui/pages/settings_page.py`
- Modify: `app/gui/main_window.py`
- Modify: `tests/test_gui_theme.py`
- Modify: `tests/test_gui_shell.py`

**Interfaces:**
- Consumes: `UiPreferences`, `load_ui_preferences`, `save_ui_preferences`, `apply_theme`。
- Produces: controls `settings_theme` and `settings_font_size`；`settings_saved` 触发当前应用刷新。

- [x] **Step 1: Write failing settings-page tests**

Construct the page with an INI-backed `QSettings`; assert default selector is light and font is 12, then save
dark/14 and reconstruct the page to prove persistence.

- [x] **Step 2: Verify RED**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_gui_theme.py" -v`
Expected: controls are absent.

- [x] **Step 3: Add theme and font controls**

Add a `QComboBox` with data values `light`, `dark`, `system` and a 10–16 `QSpinBox`. Save validated values
through the theme module. Update status text to state that visual settings apply immediately while cache
capacity still applies next launch.

- [x] **Step 4: Connect immediate application in MainWindow**

Connect `SettingsPage.settings_saved` to a `_apply_ui_preferences` slot. Apply preferences once before or
immediately after UI construction, then on every save call `apply_theme`, repolish the window and update all
self-painted canvases. Do not reopen the project or reset splitter sizes.

- [x] **Step 5: Verify persistence and immediate refresh**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_gui_theme.py" -v`
Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_gui_shell.py" -v`

### Task 6: Replace page-local hardcoded styles with semantic roles

**Files:**
- Modify: `app/gui/main_window.py`
- Modify: `app/gui/pages/analysis_page.py`
- Modify: `app/gui/pages/association_page.py`
- Modify: `app/gui/pages/calibration_page.py`
- Modify: `app/gui/pages/comparison_page.py`
- Modify: `app/gui/pages/correction_page.py`
- Modify: `app/gui/pages/events_page.py`
- Modify: `app/gui/pages/media_page.py`
- Modify: `app/gui/pages/pipeline_page.py`
- Modify: `app/gui/pages/playback_3d_page.py`
- Modify: `app/gui/pages/project_page.py`
- Modify: `app/gui/pages/quality_2d_page.py`
- Modify: `app/gui/pages/settings_page.py`
- Modify: `app/gui/pages/synchronization_page.py`
- Modify: `app/gui/pages/tasks_page.py`
- Modify: `tests/test_gui_theme.py`
- Modify: `tests/test_gui_layout.py`

**Interfaces:**
- Consumes: global QSS `uiRole` selectors.
- Produces: pages with no inline hardcoded foreground/background colors that conflict with theme changes.

- [x] **Step 1: Write failing behavior tests for representative roles**

Instantiate project, quality, pipeline and correction pages and assert their title/description widgets expose
`uiRole=pageTitle` and `uiRole=muted`, while the quality comparison frame exposes
`uiRole=recessedPanel`. Name widgets where needed for stable lookup.

- [x] **Step 2: Verify RED**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_gui_theme.py" -v`
Expected: representative widgets have no roles.

- [x] **Step 3: Replace inline styles page by page**

Replace only color/font inline QSS with `setProperty("uiRole", role)`. Preserve functional inline layout,
padding or geometry only when it does not encode theme color. Use the same roles consistently across all
listed pages.

- [x] **Step 4: Add large-font small-window regression**

Apply light/16pt, resize the main window to 620×480, visit media, settings, calibration, pipeline,
quality_2d and correction_2d, and assert each complex control area is inside a scroll area or adjustable
splitter and remains reachable.

- [x] **Step 5: Run GUI regressions**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_gui_theme.py" -v`
Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_gui_layout.py" -v`
Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_gui_shell.py" -v`

### Task 7: Theme-aware 2D/3D canvases and parameter help

**Files:**
- Modify: `app/gui/pages/correction_page.py`
- Modify: `app/gui/widgets/trajectory_canvas.py`
- Modify: `app/gui/widgets/config_parameter_editor.py`
- Modify: `tests/test_correction_overlay.py`
- Modify: `tests/test_trajectory_canvas.py`
- Modify: `tests/test_config_parameter_editor.py`

**Interfaces:**
- Consumes: `palette_for_application()`.
- Produces: self-painted widgets whose background, grid, normal/selected point and help colors update with theme.

- [x] **Step 1: Write failing palette-consumption tests**

Set application theme to light, render each canvas offscreen, switch to dark and render again. Assert the
corner/background pixel changes to the exact palette canvas color. For the config editor, rebuild parameters
and assert the help marker foreground equals the palette accent.

- [x] **Step 2: Verify RED**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_correction_overlay.py" -v`
Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_trajectory_canvas.py" -v`
Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_config_parameter_editor.py" -v`
Expected: rendered background remains the existing hardcoded dark color.

- [x] **Step 3: Replace hardcoded canvas colors**

Read the active palette during paint. Keep semantic left/right/center skeleton hues but use palette-provided
canvas, grid, muted, accent and warning colors. On theme refresh call `update()`; do not alter zoom, pan,
selection, ghost trajectories or coordinate transforms.

- [x] **Step 4: Refresh parameter help accent**

Provide `ConfigParameterEditor.refresh_theme()` that reapplies the accent brush to generated help markers.
Call it from MainWindow theme refresh through the pipeline page.

- [x] **Step 5: Run focused regressions**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_correction_overlay.py" -v`
Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_correction_page.py" -v`
Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_trajectory_canvas.py" -v`
Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_playback_3d_page.py" -v`
Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_config_parameter_editor.py" -v`

### Task 8: Pose2Sim 官方示例短帧验收工具

**Files:**
- Create: `scripts/pose2sim_sample_acceptance.py`
- Create: `tests/test_pose2sim_sample_acceptance.py`
- Modify: `docs/user-guide.md`

**Interfaces:**
- Produces CLI: `pose2sim_sample_acceptance.py --sample <dir> --runner <python-or-exe> --frames 3`。
- Produces a temporary copied project and exits nonzero with categorized reason on failure.

- [x] **Step 1: Write failing tests for safe sample preparation**

Create a tiny fake sample with Config.toml and videos, run `prepare_sample`, and assert the returned path is
different, the source bytes are unchanged, `frame_range` is limited to the requested frames, and unnecessary
rendered-video output is disabled in the copy.

- [x] **Step 2: Verify RED**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_pose2sim_sample_acceptance.py" -v`
Expected: script module is absent.

- [x] **Step 3: Implement temporary-copy preparation and runner selection**

Use `tempfile.TemporaryDirectory` and `shutil.copytree`; invoke a Python runner as
`python -m app.main ...` and an EXE runner directly. First call `--pose2sim-runtime-check`, then invoke only
`poseEstimation`. Preserve full subprocess output in a timestamped acceptance log outside the sample source.

- [x] **Step 4: Document exact operator commands**

Add source-environment and EXE examples to `docs/user-guide.md`, including the distinction between a missing
ONNX frontend and a first-run model download failure.

- [x] **Step 5: Run safe-preparation tests**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_pose2sim_sample_acceptance.py" -v`

### Task 9: Full regression, build and release acceptance

**Files:**
- Modify: `docs/superpowers/test-records/2026-09-09-accessible-theme-and-portable-pose2sim.md`

**Interfaces:**
- Consumes: all previous tasks.
- Produces: reproducible test/build/sample evidence and a single known-limit section.

- [x] **Step 1: Run the complete unit suite**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -q`
Expected: exit 0 with no failures or errors.

- [x] **Step 2: Compile all application, test and acceptance Python files**

Run: `.venv\Scripts\python.exe -m compileall -q app tests scripts\pose2sim_sample_acceptance.py`
Expected: exit 0.

- [x] **Step 3: Build the Windows executable**

Run: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\build_windows.ps1`
Expected: PyInstaller exits 0 and DLL audit reports no Poppler conflict, ONNX frontend present and CPU plugin present.

- [x] **Step 4: Run frozen smoke and runtime checks**

Run: `outputs\build\dist\MotionAnalysisStudio.exe --gui-smoke-test`
Run: `outputs\build\dist\MotionAnalysisStudio.exe --pose2sim-runtime-check`
Expected: both exit 0; runtime output lists `onnx` and `CPU`.

- [x] **Step 5: Run official sample acceptance on a temporary copy**

Run source and EXE acceptance against `Pose2Sim\Demo_SinglePerson` with three frames. If the model is not
cached and network is unavailable, record that external condition separately, then rerun with the existing
cached model before release. The final release gate requires a completed EXE poseEstimation, not only a probe.

- [x] **Step 6: Record evidence and review repository state**

Record commands, exit codes, sample source, temporary destination, generated pose file count and known
limitations. Run `git diff --check` and `git status --short`; verify the four pre-existing untracked documents
remain untouched.

- [ ] **Step 7: Commit and push the completed stage**

After fresh verification, stage only files from this plan, commit with a concise non-generated message, and
push the current `codex/phase-9` branch to the configured MotionAnalysisStudio remote, following the user's
standing request to upload each completed stage.
