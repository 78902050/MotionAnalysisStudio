# 已处理结果自动装载实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让已处理 Pose2Sim 试次在登记后直接向二维、关联、三维、运动学、事件和对比页面提供可用数据。

**Architecture:** 以 `ProjectArtifactCatalog` 作为目录事实来源，登记器只刷新清单，页面通过明确的适配接口读取标准 Pose2Sim/Caliscope 产物。耗时解析继续放在后台任务中，页面之间只传递经过验证的领域对象。

**Tech Stack:** Python 3.12、PySide6、Pose2Sim/OpenPose JSON、TRC、MOT/STO、unittest。

**Spec:** `docs/superpowers/specs/2026-09-06-existing-results-auto-load-design.md`

## Global Constraints

- 不修改原始 MP4，不把衍生视频冒充为原始视频。
- 不修改已安装 Pose2Sim 或 Caliscope。
- 不写死样本路径、相机名称、同步偏移或人物编号。
- 缺失 Config 只限制重跑，不限制结果查看。
- 所有保存继续使用原子替换，保留已有项目 ID、修正历史和用户状态。
- 耗时扫描、解析和计算不得阻塞 GUI 主线程。

---

### Task 1: 统一产物目录与幂等清单刷新

**Files:**
- Create: `app/project/artifacts.py`
- Modify: `app/project/importer.py`
- Modify: `app/project/discovery.py`
- Test: `tests/test_existing_result_refresh.py`

**Interfaces:**
- Produces: `ProjectArtifactCatalog.scan(root: Path) -> ProjectArtifacts`
- Produces: `ExistingResultImporter.register(candidate: TrialCandidate) -> ProjectManager`

- [ ] 写失败测试，构造已有清单后再加入标准结果目录并重新登记：

```python
def test_register_refreshes_stale_manifest_without_replacing_identity(self):
    project = ProjectManager.create(root, "旧项目")
    project.manifest["custom"] = {"keep": True}
    project.save_manifest()
    write_pose_frame(root / "pose" / "cam01_json" / "cam01_000000.json")
    write_minimal_trc(root / "pose-3d" / "trial_P0.trc")
    candidate = ExistingResultDiscovery().discover_one(root)

    refreshed = ExistingResultImporter().register(candidate)

    self.assertEqual(refreshed.manifest["project_id"], project.manifest["project_id"])
    self.assertEqual(refreshed.manifest["custom"], {"keep": True})
    self.assertEqual(refreshed.manifest["cameras"], [{"camera_id": "cam01"}])
    self.assertEqual(refreshed.manifest["imported_artifacts"]["pose_2d_files"], 1)
    self.assertEqual(len(refreshed.manifest["imported_artifacts"]["trc_files"]), 1)
```

- [ ] 运行 `\.venv\Scripts\python.exe -m unittest tests.test_existing_result_refresh -v`，预期相机仍为空或缺少 `imported_artifacts`。
- [ ] 实现 `ProjectArtifactCatalog.scan()`；把目录枚举集中在该类型中，并让 `ExistingResultImporter.register()` 对已有清单执行刷新而不是提前返回。
- [ ] 运行 `\.venv\Scripts\python.exe -m unittest tests.test_existing_result_refresh tests.test_project_manager tests.test_existing_results_import -v`，预期全部通过。
- [ ] 仅暂存本任务文件并提交 `fix: refresh imported result manifests`。

### Task 2: 多试次根目录自动转后台扫描

**Files:**
- Modify: `app/gui/main_window.py`
- Modify: `app/gui/pages/project_page.py`
- Test: `tests/test_existing_result_collection_import.py`

**Interfaces:**
- Consumes: `ExistingResultDiscovery.scan(root)`
- Produces: `MainWindow.import_existing_path(path) -> bool`

- [ ] 写失败测试，调用与按钮相同的入口并等待后台线程：

```python
def test_import_collection_populates_candidates_without_root_manifest(self):
    write_pose_frame(root / "trial-a" / "pose" / "cam01_json" / "cam01_000000.json")
    write_pose_frame(root / "trial-b" / "pose" / "cam01_json" / "cam01_000000.json")
    window = MainWindow()

    self.assertTrue(window.import_existing_path(root))
    wait_until(lambda: window._discovery_thread is None)

    page = window._pages["project"]
    self.assertEqual(page.candidate_table.rowCount(), 2)
    self.assertFalse((root / "manifest.json").exists())
```

- [ ] 运行 `\.venv\Scripts\python.exe -m unittest tests.test_existing_result_collection_import -v`，预期入口返回失败且候选数为 0。
- [ ] 在 `import_existing_path()` 捕获“目录不是单试次”后调用既有 `scan_existing_parent()`；扫描完成时区分 0、1、多候选并显示可执行提示。
- [ ] 运行 `\.venv\Scripts\python.exe -m unittest tests.test_existing_result_collection_import tests.test_existing_results_gui -v`，预期全部通过且 Qt 线程退出。
- [ ] 仅暂存本任务文件并提交 `fix: expand processed result collections`。

### Task 3: 二维 pose 直接浏览与编辑

**Files:**
- Modify: `app/project/artifacts.py`
- Modify: `app/application/quality_correction_service.py`
- Modify: `app/gui/pages/correction_page.py`
- Modify: `app/gui/main_window.py`
- Test: `tests/test_existing_pose_browser.py`

**Interfaces:**
- Produces: `QualityCorrectionService.resolve_pose_frame(camera, frame, person_index, keypoint_index) -> CorrectionResolution`
- Produces: `CorrectionPage.browse_requested(str, int, int, int)`

- [ ] 写失败测试，直接解析标准 Pose2Sim 帧并创建可编辑会话：

```python
def test_resolve_pose_frame_opens_halpe26_without_quality_issue(self):
    project = make_project_with_pose_people(keypoint_count=26, people=2)
    service = QualityCorrectionService(project)

    resolution = service.resolve_pose_frame("cam01", 0, 1, 9)
    session = service.create_session(resolution)

    self.assertTrue(resolution.can_edit)
    self.assertEqual(resolution.edit_target.keypoint.model_name, "HALPE_26")
    self.assertEqual(resolution.edit_target.keypoint.keypoint_name, "LWrist")
    self.assertEqual(len(session.document.frame_pose().people[1].keypoints), 26)
```

- [ ] 写 GUI 失败测试：`CorrectionPage` 的人物和关节点选择器可用，改变相机/帧发出 `browse_requested(camera, frame, person, keypoint)`。
- [ ] 运行 `\.venv\Scripts\python.exe -m unittest tests.test_existing_pose_browser -v`，预期因 `resolve_pose_frame` 和 `browse_requested` 不存在而失败。
- [ ] 增加 pose 帧索引与 `HALPE_26` 名称表；实现直接解析、选择器更新和 `CorrectionSession` 复用。无法识别模型时生成 `index-000` 形式名称并在状态栏说明。
- [ ] 运行 `\.venv\Scripts\python.exe -m unittest tests.test_existing_pose_browser tests.test_correction_workspace tests.test_correction_session tests.test_correction_history -v`，预期全部通过。
- [ ] 仅暂存本任务文件并提交 `feat: browse imported pose frames directly`。

### Task 4: 已有质量与关联结果后台装载

**Files:**
- Modify: `app/quality/audit.py`
- Modify: `app/gui/main_window.py`
- Modify: `app/gui/pages/association_page.py`
- Test: `tests/test_existing_quality_and_association.py`

**Interfaces:**
- Consumes: `ProjectArtifactCatalog.scan(root)`
- Produces: TRC 三维质量指标和项目打开后的后台关联报告。

- [ ] 写失败测试，使用最小 TRC 和标准嵌套 pose：

```python
def test_quality_audit_uses_trc_when_internal_pose3d_json_is_absent(self):
    project = make_imported_project_with_trc(valid_points=5, missing_points=1)

    report = QualityAuditService().analyze(project)

    self.assertEqual(report.metrics()["3d_total_points"], 6)
    self.assertEqual(report.metrics()["3d_valid_points"], 5)
    self.assertEqual(report.metrics()["3d_missing_points"], 1)
    self.assertNotIn("pose-3d file is missing", issue_messages(report))
```

- [ ] 写 GUI 失败测试：打开无报告的已有结果项目会启动质量任务；打开含 `pose-associated` 的项目会自动启动关联后台扫描并最终填充轨迹段状态。
- [ ] 运行 `\.venv\Scripts\python.exe -m unittest tests.test_existing_quality_and_association -v`，预期 TRC 指标缺失且关联页保持等待按钮状态。
- [ ] 用 `Trajectory.from_trc()` 生成三维质量汇总；项目打开时启动可取消的质量和关联任务，并按项目 ID/generation 接受结果。
- [ ] 运行 `\.venv\Scripts\python.exe -m unittest tests.test_existing_quality_and_association tests.test_quality_audit tests.test_quality_pages tests.test_association -v`，预期全部通过。
- [ ] 仅暂存本任务文件并提交 `feat: load imported quality and associations`。

### Task 5: 三维、运动学、事件与对比联动

**Files:**
- Modify: `app/gui/pages/analysis_page.py`
- Modify: `app/gui/pages/events_page.py`
- Modify: `app/gui/pages/comparison_page.py`
- Modify: `app/gui/main_window.py`
- Test: `tests/test_existing_analysis_flow.py`

**Interfaces:**
- Produces: `AnalysisPage.metrics_ready = Signal(object)`
- Consumes: `EventsPage.set_metric_table(table)`、`ComparisonPage.set_members(members)`

- [ ] 写失败测试，验证页面目录与跨页信号：

```python
def test_existing_trc_metrics_feed_events_and_comparison(self):
    window = open_window(make_project_with_trc_and_mot())
    analysis = window._pages["analysis"]

    self.assertGreater(analysis.trajectory_selector.count(), 0)
    self.assertGreater(analysis.kinematics_files.count(), 0)
    analysis.calculate()
    wait_until(lambda: analysis._thread is None)

    self.assertIsNotNone(window._pages["events"].metric_table)
    self.assertEqual(len(window._pages["comparison"]._members), 1)
```

- [ ] 运行 `\.venv\Scripts\python.exe -m unittest tests.test_existing_analysis_flow -v`，预期产物控件或 `metrics_ready` 信号不存在。
- [ ] 增加 TRC 选择器和 MOT/STO 只读目录；`AnalysisPage` 完成计算后发出 `MetricTable`，主窗口调用 `EventsPage.set_metric_table()` 并创建当前试次 `ComparisonMember`。
- [ ] 运行 `\.venv\Scripts\python.exe -m unittest tests.test_existing_analysis_flow tests.test_analysis_page tests.test_events_page tests.test_comparison_page -v`，预期全部通过。
- [ ] 仅暂存本任务文件并提交 `feat: connect imported analysis results`。

### Task 6: 真实数据、打包与完整验收

**Files:**
- Modify: `scripts/real_data_acceptance.py`
- Modify: `tests/test_existing_results_acceptance.py`
- Modify: `docs/user-guide.md`
- Create: `docs/superpowers/test-records/2026-09-06-existing-results-auto-load.md`

- [ ] 扩展 `tests/test_existing_results_acceptance.py`，断言旧清单刷新、集合候选、二维直接浏览、TRC 质量与指标联动均成功。
- [ ] 运行 `\.venv\Scripts\python.exe -m unittest tests.test_existing_results_acceptance -v`，修复任何真实格式适配失败。
- [ ] 运行 `powershell -ExecutionPolicy Bypass -File scripts\run_real_data_acceptance.ps1 -Root D:\test\data`，比较验收前后的源 pose、TRC、MOT/STO，预期内容不变。
- [ ] 运行 `\.venv\Scripts\python.exe -m unittest discover -s tests -q` 和 `\.venv\Scripts\python.exe -m compileall -q app tests scripts`，预期退出码 0。
- [ ] 运行 `powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1`，再运行 `powershell -ExecutionPolicy Bypass -File scripts\smoke_exe.ps1 -Executable outputs\build\dist\MotionAnalysisStudio.exe -Mode All`，预期三类 smoke 全部通过。
- [ ] 更新用户指南和测试记录，只暂存本任务文件并提交 `test: verify imported result auto loading`。
