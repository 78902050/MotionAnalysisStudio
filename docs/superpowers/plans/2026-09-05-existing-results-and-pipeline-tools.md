# Existing Results and Pipeline Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户单独或批量登记已完成的 Pose2Sim 试次，在无源视频时仍读取各层结果，并从应用启动 Caliscope、编辑 Config 和分阶段运行 Pose2Sim及查看实时日志。

**Architecture:** 在现有 `ProjectManager` 外增加只负责发现和原地登记的导入层；页面仍读取项目内标准目录，避免引入全局外部路径兼容层。外部 GUI 和 Pose2Sim 阶段统一进入可取消任务边界，Config 文本通过独立事务模型保存，视频保持可选输入。

**Tech Stack:** Python 3.12、PySide6、tomllib、QSettings、现有 TaskSupervisor/PipelineRunner、Caliscope 0.11.6、Pose2Sim 0.10.49、unittest。

**Spec:** `docs/superpowers/specs/2026-09-05-existing-results-and-pipeline-tools-design.md`

## Global Constraints

- 导入已有结果时不得覆盖 pose、TRC、MOT、STO、标定或 MP4。
- 视频不是读取已有分析结果的前置条件，原始 MP4 不转码、不覆盖。
- 缺失或无效 Config 只禁用重跑，不阻止项目打开。
- 一般 Pose2Sim 流程和二维修正选择性重跑使用不同白名单。
- 外部进程、目录扫描、质量扫描、日志跟踪和 Pose2Sim 运行不得阻塞 GUI 主线程。
- 新文件保存使用原子替换；Config 和二维工作 JSON 保留可恢复备份。
- 相机名、同步偏移、人物和关节点不得按样本写死。
- 所有任务回调必须校验 project ID 和 generation。
- 每项任务先运行新增测试确认按预期失败，再写产品代码。

---

### Task 1: 已处理试次发现、索引与原地登记

**Files:**
- Create: `app/project/import_model.py`
- Create: `app/project/discovery.py`
- Create: `app/project/importer.py`
- Modify: `app/project/manifest.py`
- Test: `tests/test_existing_result_import.py`

**Interfaces:**
- Produces: `ArtifactSummary`, `TrialCandidate`, `ExistingResultDiscovery.discover_one(path)`, `ExistingResultDiscovery.scan(root)`, `ExistingResultImporter.register(candidate)`。
- `register` 返回可直接交给 `MainWindow.open_project` 的 `ProjectManager`。

- [ ] **Step 1: Write the failing discovery tests**

```python
candidate = ExistingResultDiscovery().discover_one(trial_root)
self.assertEqual(candidate.cameras, ("cam01", "cam02"))
self.assertTrue(candidate.artifacts.pose_2d)
self.assertFalse(candidate.has_video)
self.assertEqual(ExistingResultDiscovery().scan(parent), (candidate,))
```

- [ ] **Step 2: Run discovery tests to verify RED**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_existing_result_import.py" -v`

Expected: import failure for `app.project.discovery`.

- [ ] **Step 3: Implement immutable candidate models and stable scanning**

```python
@dataclass(frozen=True)
class ArtifactSummary:
    pose_2d: int
    pose_sync: int
    pose_associated: int
    trc: tuple[Path, ...]
    kinematics: tuple[Path, ...]

@dataclass(frozen=True)
class TrialCandidate:
    root: Path
    cameras: tuple[str, ...]
    artifacts: ArtifactSummary
    calibration_path: Path | None
    config_path: Path | None
    videos: tuple[Path, ...]
```

- [ ] **Step 4: Write failing registration tests**

```python
project = ExistingResultImporter().register(candidate)
self.assertTrue((trial_root / "manifest.json").is_file())
self.assertEqual(project.manifest["stages"]["poseEstimation"]["status"], "completed")
self.assertEqual(existing_pose.read_bytes(), original_pose)
```

Include tests for an existing manifest, a read-only registration failure, `can02` preservation, empty Config, nearest-parent calibration and repeated registration.

- [ ] **Step 5: Implement registration and artifact report**

Create the v3 manifest only when absent, call `_ensure_layout` without replacing existing directories, activate a readable calibration copy through `CalibrationImporter`, and write `reports/import/artifacts.json` with counts and source paths. Store discovered video paths only when files exist.

- [ ] **Step 6: Run focused and project regression tests**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_existing_result_import.py" -v`

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_project_manager.py" -v`

- [ ] **Step 7: Commit Task 1**

```powershell
git add app/project/import_model.py app/project/discovery.py app/project/importer.py app/project/manifest.py tests/test_existing_result_import.py
git commit -m "feat: import completed analysis trials"
```

### Task 2: 项目页单个读取与批量扫描

**Files:**
- Modify: `app/gui/pages/project_page.py`
- Modify: `app/gui/main_window.py`
- Test: `tests/test_existing_result_project_page.py`

**Interfaces:**
- Consumes: `ExistingResultDiscovery` and `ExistingResultImporter` from Task 1.
- Produces signals `import_one_requested(Path)` and `scan_parent_requested(Path)`; `MainWindow.import_existing_path(path)` and `MainWindow.scan_existing_parent(path)`。

- [ ] **Step 1: Write failing GUI tests**

```python
self.assertIsNotNone(page.findChild(QPushButton, "project_import_existing_button"))
window.import_existing_path(trial_root)
self.assertEqual(window.project.root, trial_root.resolve())
window.scan_existing_parent(parent)
self.assertEqual(page.candidate_table.rowCount(), 2)
```

- [ ] **Step 2: Run GUI tests to verify RED**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_existing_result_project_page.py" -v`

- [ ] **Step 3: Implement single and bulk controls**

Add separate directory pickers, a read-only candidate table, “登记所选” and “登记全部” buttons. Run recursive scan through `ApplicationController.start_task`; marshal results to the page only when project generation still matches.

- [ ] **Step 4: Implement import/open integration**

`import_existing_path` discovers exactly the selected folder, registers it and calls `open_project`. Bulk registration registers each selected candidate and opens the first successfully registered project; failures remain visible per row.

- [ ] **Step 5: Verify layout and behavior**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_existing_result_project_page.py" -v`

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_gui_layout.py" -v`

- [ ] **Step 6: Commit Task 2**

```powershell
git add app/gui/pages/project_page.py app/gui/main_window.py tests/test_existing_result_project_page.py
git commit -m "feat: open single and scanned result folders"
```

### Task 3: 无视频结果读取与初始质量扫描

**Files:**
- Modify: `app/gui/pages/correction_page.py`
- Modify: `app/application/quality_correction_service.py`
- Modify: `app/quality/audit.py`
- Modify: `app/gui/main_window.py`
- Test: `tests/test_data_only_results.py`

**Interfaces:**
- Produces: `CorrectionCanvas.set_data_extent(width, height)`, Pose2Sim per-frame quality scanning, and `MainWindow.start_initial_quality_scan(project)`。

- [ ] **Step 1: Write failing no-video canvas test**

```python
canvas.set_data_extent(3840, 2160)
canvas.set_pose_points({"nose": (100.0, 200.0, 0.9)})
self.assertTrue(canvas.has_coordinate_space)
self.assertFalse(canvas.has_frame)
```

Assert dragging is enabled in coordinate space and the hint says “仅姿态数据，无视频背景”.

- [ ] **Step 2: Write failing real per-frame quality scan test**

Copy `tests/fixtures/real_data/pose/*_json` into a project and assert `QualityAuditService.analyze` counts detections and records camera inputs instead of reporting pose as absent.

- [ ] **Step 3: Run tests to verify RED**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_data_only_results.py" -v`

- [ ] **Step 4: Implement coordinate-only rendering**

Use a logical QSize when no QImage exists. `_image_rect`, `_image_to_widget`, `_widget_to_image` and drag bounds use either image dimensions or logical dimensions. Prefer calibration image size; otherwise derive finite point maxima plus margin.

- [ ] **Step 5: Extend quality audit to nested Pose2Sim frames**

Read `pose/*_json/*.json` incrementally, infer camera/frame from directory and filename, validate flat triples and count detections without loading every frame into one aggregate dictionary. Preserve existing aggregate JSON support.

- [ ] **Step 6: Generate missing initial report in background**

When an imported project lacks `reports/quality/current.json`, submit one quality scan task. Save the report only if project ID/generation still match, then refresh both quality pages.

- [ ] **Step 7: Verify focused, heartbeat and regression tests**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_data_only_results.py" -v`

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_quality*.py" -v`

- [ ] **Step 8: Commit Task 3**

```powershell
git add app/gui/pages/correction_page.py app/application/quality_correction_service.py app/quality/audit.py app/gui/main_window.py tests/test_data_only_results.py
git commit -m "feat: browse processed results without video"
```

### Task 4: Caliscope GUI 启动和设置编码诊断

**Files:**
- Create: `app/external_tools/model.py`
- Create: `app/external_tools/launcher.py`
- Create: `app/external_tools/caliscope_settings.py`
- Modify: `app/gui/pages/calibration_page.py`
- Modify: `app/gui/main_window.py`
- Test: `tests/test_caliscope_launcher.py`
- Test: `tests/test_caliscope_page_launch.py`

**Interfaces:**
- Produces: `ExternalToolLauncher.start(command, cwd, log_path) -> ExternalProcessHandle`.
- Produces: `build_caliscope_command(workspace, configured_executable=None) -> tuple[str, ...]`.
- Produces: `CaliscopeSettingsDiagnostic.inspect(path)` and `convert_to_utf8(path) -> Path` returning the backup path.

- [ ] **Step 1: Write failing command and process tests**

```python
command = build_caliscope_command(workspace, configured_executable=tool)
self.assertEqual(command, (str(tool), "--workspace", str(workspace)))
handle = launcher.start(command, workspace, log_path)
self.assertLess(time.monotonic() - started, 0.25)
```

Verify nonzero exit, missing executable and UTF-8 log output are reported.

- [ ] **Step 2: Write failing encoding conversion tests**

```python
diagnostic = store.inspect(gb18030_toml)
self.assertEqual(diagnostic.encoding, "gb18030")
backup = store.convert_to_utf8(gb18030_toml)
self.assertEqual(tomllib.loads(gb18030_toml.read_text(encoding="utf-8")), expected)
self.assertTrue(backup.is_file())
```

Also assert invalid TOML is never rewritten.

- [ ] **Step 3: Run tests to verify RED**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_caliscope*.py" -v`

- [ ] **Step 4: Implement launcher and explicit conversion**

Use `subprocess.Popen` in a non-daemon worker, log command/exit/error, and expose `poll`, `cancel` and `wait`. Conversion writes a timestamped sibling backup and uses `AtomicJsonStore`-equivalent byte replacement without parsing/reformatting TOML content.

- [ ] **Step 5: Connect calibration page**

Add workspace chooser, “启动 Caliscope”, diagnostic text and “备份并转换为 UTF-8”. Resolve QSettings override first, then environment/PATH. Register process with the task center and show its log path.

- [ ] **Step 6: Verify focused and GUI responsiveness tests**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_caliscope*.py" -v`

- [ ] **Step 7: Commit Task 4**

```powershell
git add app/external_tools app/gui/pages/calibration_page.py app/gui/main_window.py tests/test_caliscope_launcher.py tests/test_caliscope_page_launch.py
git commit -m "feat: launch Caliscope workspaces"
```

### Task 5: Config.toml 事务编辑模型

**Files:**
- Create: `app/pose2sim/config_document.py`
- Test: `tests/test_pose2sim_config_document.py`

**Interfaces:**
- Produces: `ConfigDocument.open(path)`, `validate(text) -> ConfigValidation`, `save(text, reason) -> ConfigSaveResult`, `reload()` and `has_unsaved_changes(text)`。

- [ ] **Step 1: Write failing Config tests**

```python
document = ConfigDocument.open(config_path)
self.assertFalse(document.validate("[project\n").valid)
with self.assertRaises(ConfigSyntaxError):
    document.save("[project\n", "invalid")
self.assertEqual(config_path.read_bytes(), original)
```

Assert valid text keeps comments, first and subsequent saves create distinct backups, empty Config is not runnable, and injected replace failure keeps the old file readable.

- [ ] **Step 2: Run tests to verify RED**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_pose2sim_config_document.py" -v`

- [ ] **Step 3: Implement text-preserving validation and atomic saves**

Use `tomllib.loads` only for validation, preserve the exact editor text, write backups under `config/backups/<timestamp>-Config.toml`, flush the temporary file and replace the working file atomically.

- [ ] **Step 4: Run focused tests**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_pose2sim_config_document.py" -v`

- [ ] **Step 5: Commit Task 5**

```powershell
git add app/pose2sim/config_document.py tests/test_pose2sim_config_document.py
git commit -m "feat: edit Pose2Sim config safely"
```

### Task 6: 完整 Pose2Sim 阶段运行、实时日志和流程页面

**Files:**
- Create: `app/application/pipeline_launcher.py`
- Create: `app/gui/pages/pipeline_page.py`
- Modify: `app/adapters/pose2sim/runner.py`
- Modify: `app/main.py`
- Modify: `app/pipeline/dependency_graph.py`
- Modify: `app/gui/main_window.py`
- Modify: `app/gui/pages/tasks_page.py`
- Test: `tests/test_pose2sim_pipeline.py`
- Test: `tests/test_pipeline_page.py`

**Interfaces:**
- Produces: `GENERAL_POSE2SIM_STAGES` with all eight stages.
- Produces: `build_pipeline_commands(config_path, stages, executable=None)`.
- Produces: `PipelineLauncher.start(project, stages) -> TaskHandle`.
- Extends `RunResult` with per-stage timing/status while preserving existing correction rerun callers.

- [ ] **Step 1: Write failing stage allowlist and command tests**

```python
self.assertEqual(GENERAL_POSE2SIM_STAGES[0], "calibration")
self.assertIn("poseEstimation", GENERAL_POSE2SIM_STAGES)
self.assertNotIn("poseEstimation", CORRECTION_RERUN_STAGES)
```

Assert `app.main --pose2sim-stage` accepts every general stage and still rejects unknown stages.

- [ ] **Step 2: Write failing live-log and cancellation tests**

Run a small subprocess that emits three delayed lines. Assert incremental reads return only appended bytes, task status changes running→completed, and cancellation removes a spawned child process.

- [ ] **Step 3: Run model tests to verify RED**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_pose2sim_pipeline.py" -v`

- [ ] **Step 4: Implement the general launcher**

Map each stage to the matching Pose2Sim API function in `app.main`. Persist stage start/end/exit records, update manifest atomically and rescan artifacts after success. Reject empty/invalid Config before creating a process.

- [ ] **Step 5: Write failing pipeline-page tests**

```python
self.assertEqual(page.stage_list.count(), 8)
self.assertFalse(page.run_selected_button.isEnabled())  # invalid Config
page.set_project(valid_project)
self.assertTrue(page.run_from_button.isEnabled())
```

Assert Config validation text, save/reload, 250 ms log timer, 5000-line display cap and 620×480 scroll access.

- [ ] **Step 6: Implement the resizable workflow page**

Create left stage controls, center `QPlainTextEdit` Config editor and right read-only `QPlainTextEdit` log viewer in `QSplitter`. Add single/selected/from-stage run actions, cancel, open log, save Config and reload. Register the page as a dirty editor and persist splitter sizes through QSettings.

- [ ] **Step 7: Connect navigation, refresh and task page details**

Add `("pipeline", "Pose2Sim 流程")` before tasks. After project open or stage completion refresh pipeline, artifact-driven pages and task details. TasksPage shows failed stage and log path in addition to generic error.

- [ ] **Step 8: Verify focused and correction-rerun regression tests**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_pose2sim_pipeline.py" -v`

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_pipeline_page.py" -v`

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_correction_rerun*.py" -v`

- [ ] **Step 9: Commit Task 6**

```powershell
git add app/application/pipeline_launcher.py app/gui/pages/pipeline_page.py app/adapters/pose2sim/runner.py app/main.py app/pipeline/dependency_graph.py app/gui/main_window.py app/gui/pages/tasks_page.py tests/test_pose2sim_pipeline.py tests/test_pipeline_page.py
git commit -m "feat: run Pose2Sim stages with live logs"
```

### Task 7: 真实数据、GUI、打包和文档验收

**Files:**
- Modify: `scripts/real_data_acceptance.py`
- Modify: `scripts/smoke_exe.ps1`
- Modify: `docs/user-guide.md`
- Create: `tests/test_existing_results_acceptance.py`
- Create: `docs/superpowers/test-records/2026-09-05-existing-results-and-tools.md`

**Interfaces:**
- Consumes all Tasks 1–6 public interfaces.
- Produces a final machine-readable acceptance report containing discovered trials, data-only capability, Config state, stage command list and external-tool diagnostics.

- [ ] **Step 1: Write failing end-to-end acceptance test**

Copy the fixture trial without videos, register it, generate quality, open MainWindow, verify calibration/pose/TRC pages, edit a copied Config, run a harmless fake stage command and tail its log.

- [ ] **Step 2: Run acceptance test to verify RED**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_existing_results_acceptance.py" -v`

- [ ] **Step 3: Extend real-data acceptance**

Scan `D:\test\data`, record candidate trial count, select one trial with pose/TRC, register only a copied representative in `outputs/real-data-acceptance`, verify source pose remains byte-identical and assert no video-dependent gate blocks TRC or pose loading.

- [ ] **Step 4: Run full verification**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -q`

Run: `.venv\Scripts\python.exe -m compileall -q app tests scripts`

Run: `scripts\run_real_data_acceptance.ps1 -Root D:\test\data`

Run: `git diff --check`

- [ ] **Step 5: Rebuild and smoke the EXE**

Run: `scripts\build_windows.ps1`

Run: `scripts\smoke_exe.ps1 -Executable outputs\build\dist\MotionAnalysisStudio.exe -Mode All`

The frozen workflow smoke must include importing a processed folder without video and validating the Pose2Sim stage/config interfaces without launching a real long-running analysis.

- [ ] **Step 6: Update documentation and test record**

Document single/bulk import, data-only mode, Caliscope launch, Config backups, stage controls, logs, cancellation and actual verification results. Keep independent clean-Windows validation as a known limitation until performed.

- [ ] **Step 7: Commit and push Task 7**

```powershell
git add scripts/real_data_acceptance.py scripts/smoke_exe.ps1 docs/user-guide.md tests/test_existing_results_acceptance.py docs/superpowers/test-records/2026-09-05-existing-results-and-tools.md
git commit -m "test: verify existing results and pipeline tools"
git push origin codex/phase-9
```
