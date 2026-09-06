# 二维视频骨骼修正恢复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让二维修正页可靠显示原视频或 Pose2Sim 二维标记视频，并在视频上绘制可编辑的语义骨骼。

**Architecture:** 新增视频来源解析/绑定服务和共享骨架拓扑适配器。项目打开时先配置后台帧提供器，再打开 Pose 帧；画布把视频与当前工作 JSON 分为两个图层，视频只读，JSON 图层可编辑并保留现有事务历史。

**Tech Stack:** Python 3.12、PySide6、OpenCV、Pose2Sim skeletons、unittest。

**Spec:** `docs/superpowers/specs/2026-09-06-2d-video-overlay-restoration-design.md`

**Implementation status:** 已于 2026-09-06 完成；最终证据见 `docs/superpowers/test-records/2026-09-06-2d-video-overlay-restoration.md`。下列复选步骤保留为可重复执行的重建流程。

## Global Constraints

- 不修改、删除或转码原视频和 Pose2Sim 二维标记视频。
- 不修改已安装 Pose2Sim；只读取其骨架定义和示例视频。
- 不写死项目路径、相机名、同步偏移、人物编号或视频帧偏移。
- 原视频与 Pose2Sim 标记视频必须明确标注来源类型。
- 视频帧解码继续在后台线程执行。
- 未知骨架模型只画点，不猜测连线。
- 每项生产改动前先写并运行失败测试。

---

### Task 1: 视频来源模型、发现与旧清单刷新

**Files:**
- Create: `app/media/video_sources.py`
- Modify: `app/project/importer.py`
- Modify: `app/gui/main_window.py`
- Test: `tests/test_video_sources.py`

**Interfaces:**
- Produces: `CameraVideoSource(camera: str, path: Path, kind: Literal["original", "pose2sim_overlay"])`
- Produces: `VideoSourceResolver.resolve(project: ProjectManager) -> dict[str, CameraVideoSource]`
- Consumes later: `MultiViewFrameProvider.set_project(project_id, sources)`

- [ ] **Step 1: Write the failing source-priority tests**

Create the temporary project tree and `make_project_with_camera` / `discover_trial_with` fixtures inside the test module so every path and candidate used below is a real file in an isolated temporary directory.

```python
def test_resolver_prefers_original_but_falls_back_to_pose_video(self):
    project = make_project_with_camera(
        video_path=original,
        pose_video_path=overlay,
    )
    self.assertEqual(VideoSourceResolver.resolve(project)["cam01"].kind, "original")
    original.unlink()
    self.assertEqual(
        VideoSourceResolver.resolve(project)["cam01"],
        CameraVideoSource("cam01", overlay.resolve(), "pose2sim_overlay"),
    )

def test_importer_maps_pose2sim_video_by_camera_name(self):
    candidate = discover_trial_with("pose/cam02_pose.mp4")
    project = ExistingResultImporter().register(candidate)
    by_camera = {item["camera_id"]: item for item in project.manifest["cameras"]}
    self.assertEqual(by_camera["cam02"]["pose_video_path"], str(overlay.resolve()))
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p test_video_sources.py -v`

Expected: import failure for `app.media.video_sources` or missing `pose_video_path`.

- [ ] **Step 3: Implement the source model and importer mapping**

Implement `CameraVideoSource.__post_init__()` validation, preferred-kind selection, readable-file fallback and per-camera normalized stem matching. Keep `video_path` semantics unchanged and add `pose_video_path` only for a unique matching derived video.

- [ ] **Step 4: Run focused and importer regression tests**

Run each file with `unittest discover`: `$patterns=@('test_video_sources.py','test_existing_result_import.py','test_existing_result_refresh.py','test_gui_workflows.py'); foreach($pattern in $patterns){ .venv\Scripts\python.exe -m unittest discover -s tests -p $pattern -v; if($LASTEXITCODE -ne 0){ exit $LASTEXITCODE } }`

Expected: all pass.

- [ ] **Step 5: Commit and push**

```text
git add app/media/video_sources.py app/project/importer.py app/gui/main_window.py tests/test_video_sources.py
git commit -m "feat: resolve camera video sources"
git push origin codex/phase-9
```

### Task 2: 媒体页逐相机视频绑定

**Files:**
- Create: `app/media/bindings.py`
- Modify: `app/gui/pages/media_page.py`
- Modify: `app/gui/main_window.py`
- Test: `tests/test_media_bindings.py`

**Interfaces:**
- Produces: `VideoBindingService.bind(project, camera, path, kind, preferred=True) -> CameraVideoSource`
- Produces: `VideoBindingService.clear(project, camera, kind) -> None`
- Produces: `MediaPage.sources_changed = Signal()`

- [ ] **Step 1: Write failing binding behavior tests**

```python
def test_binding_updates_only_selected_camera_and_preserves_file(self):
    before = video.read_bytes()
    source = VideoBindingService.bind(project, "cam02", video, "original")
    self.assertEqual(source.camera, "cam02")
    self.assertEqual(project.manifest["cameras"][1]["video_path"], str(video.resolve()))
    self.assertEqual(video.read_bytes(), before)

def test_media_page_marks_pose_video_source(self):
    page = MediaPage(project)
    self.assertEqual(page.model.records[0].source_kind, "pose2sim_overlay")
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p test_media_bindings.py -v`

Expected: missing binding service and `source_kind`.

- [ ] **Step 3: Implement binding service and UI actions**

Use `QFileDialog.getOpenFileName()` only in click handlers. Put path validation and manifest mutation in `VideoBindingService`, preserve unrelated camera fields, call `project.save_manifest()`, then emit `sources_changed`. Add source type to `MediaRecord` and buttons for bind original, bind Pose2Sim video, set preferred and clear selected binding.

- [ ] **Step 4: Run media and project regressions**

Run each file with `unittest discover`: `$patterns=@('test_media_bindings.py','test_gui_workflows.py','test_project_manager.py','test_atomic_storage.py'); foreach($pattern in $patterns){ .venv\Scripts\python.exe -m unittest discover -s tests -p $pattern -v; if($LASTEXITCODE -ne 0){ exit $LASTEXITCODE } }`

Expected: all pass.

- [ ] **Step 5: Commit and push**

```text
git add app/media/bindings.py app/gui/pages/media_page.py app/gui/main_window.py tests/test_media_bindings.py
git commit -m "feat: bind camera video sources"
git push origin codex/phase-9
```

### Task 3: 帧提供器来源隔离与首帧顺序

**Files:**
- Modify: `app/media/frame_provider.py`
- Modify: `app/gui/main_window.py`
- Modify: `app/gui/pages/correction_page.py`
- Test: `tests/test_frame_provider_sources.py`

**Interfaces:**
- Consumes: `dict[str, CameraVideoSource]`
- Produces: `MultiViewFrameProvider.source_for(camera: str) -> CameraVideoSource | None`
- Produces: `MainWindow(..., frame_provider: MultiViewFrameProvider | None = None)` for deterministic integration tests while retaining the normal default provider.
- Preserves: `frame_ready(str, int, object)` and `frame_failed(str, int, str)`

- [ ] **Step 1: Write failing cache/source and ordering tests**

```python
def test_switching_source_cannot_return_old_cached_frame(self):
    provider.set_project("p1", {"cam01": CameraVideoSource("cam01", first, "original")})
    request_and_wait(provider, FrameAddress("cam01", "raw", 0))
    provider.set_project("p1", {"cam01": CameraVideoSource("cam01", second, "pose2sim_overlay")})
    image = request_and_wait(provider, FrameAddress("cam01", "raw", 0))
    self.assertEqual(tuple(image[0, 0]), SECOND_VIDEO_PIXEL)

def test_main_window_configures_provider_before_first_pose_request(self):
    window = MainWindow(frame_provider=recording_provider)
    window.open_project(project)
    self.assertLess(events.index("set_project"), events.index("request"))
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p test_frame_provider_sources.py -v`

Expected: wrong argument type or request occurs before `set_project`.

- [ ] **Step 3: Implement source-aware provider and open ordering**

Pass the selected source path to `_CameraDecodeThread`, include kind and resolved path in cache identity, expose `source_for()`, configure the provider before `set_pose_inventory()`, and request the current frame after any binding refresh. Keep generation checks and worker shutdown behavior.

- [ ] **Step 4: Run frame, workspace and heartbeat tests**

Run each file with `unittest discover`: `$patterns=@('test_frame_provider_sources.py','test_frame_provider.py','test_correction_workspace.py','test_gui_layout.py'); foreach($pattern in $patterns){ .venv\Scripts\python.exe -m unittest discover -s tests -p $pattern -v; if($LASTEXITCODE -ne 0){ exit $LASTEXITCODE } }`

Expected: all pass; heartbeat remains below 250 ms.

- [ ] **Step 5: Commit and push**

```text
git add app/media/frame_provider.py app/gui/main_window.py app/gui/pages/correction_page.py tests/test_frame_provider_sources.py
git commit -m "fix: load correction video frames reliably"
git push origin codex/phase-9
```

### Task 4: 共享骨架拓扑与二维连线图层

**Files:**
- Create: `app/visualization/__init__.py`
- Create: `app/visualization/skeleton.py`
- Modify: `app/gui/pages/correction_page.py`
- Test: `tests/test_skeleton_topology.py`
- Test: `tests/test_correction_overlay.py`

**Interfaces:**
- Produces: `SkeletonTopologyRepository.edges_for(model_name, keypoint_names) -> tuple[tuple[str, str], ...]`
- Produces: `SkeletonTopologyRepository.edges_for_labels(keypoint_names) -> tuple[tuple[str, str], ...]`
- Produces: `CorrectionCanvas.set_pose_points(points, edges=()) -> None`
- Produces: `CorrectionCanvas.edge_count: int`

- [ ] **Step 1: Write failing semantic topology tests**

```python
def test_halpe26_edges_are_names_and_include_main_limb_chain(self):
    edges = SkeletonTopologyRepository().edges_for("HALPE_26", HALPE_26_NAMES)
    self.assertIn(("LShoulder", "LElbow"), edges)
    self.assertIn(("LElbow", "LWrist"), edges)
    self.assertNotIn(("LEye", "REye"), edges)

def test_unknown_model_draws_points_without_edges(self):
    canvas.set_pose_points({"index-000": (10.0, 20.0, 0.9)}, edges=())
    self.assertEqual(canvas.point_count, 1)
    self.assertEqual(canvas.edge_count, 0)
```

- [ ] **Step 2: Run tests and verify RED**

Run each file with `unittest discover`: `$patterns=@('test_skeleton_topology.py','test_correction_overlay.py'); foreach($pattern in $patterns){ .venv\Scripts\python.exe -m unittest discover -s tests -p $pattern -v; if($LASTEXITCODE -ne 0){ exit $LASTEXITCODE } }`

Expected: missing repository and unsupported `edges` argument.

- [ ] **Step 3: Implement Pose2Sim tree traversal and canvas lines**

Resolve the named Pose2Sim skeleton object, traverse parent/child nodes, retain only edges whose names exist in the current frame, and return no edges on unknown or ambiguous input. Draw edges before points; skip missing/non-positive-confidence endpoints. Refresh edges after drag, undo, redo and reset. Add source-kind text to each view label.

- [ ] **Step 4: Run correction regressions**

Run each file with `unittest discover`: `$patterns=@('test_skeleton_topology.py','test_correction_overlay.py','test_correction_page.py','test_correction_workspace.py','test_existing_pose_browser.py'); foreach($pattern in $patterns){ .venv\Scripts\python.exe -m unittest discover -s tests -p $pattern -v; if($LASTEXITCODE -ne 0){ exit $LASTEXITCODE } }`

Expected: all pass.

- [ ] **Step 5: Commit and push**

```text
git add app/visualization app/gui/pages/correction_page.py tests/test_skeleton_topology.py tests/test_correction_overlay.py
git commit -m "feat: draw editable skeleton over video"
git push origin codex/phase-9
```

### Task 5: 真实视频、回归与冻结 EXE 验收

**Files:**
- Modify: `scripts/real_data_acceptance.py`
- Modify: `tests/test_existing_results_acceptance.py`
- Modify: `docs/user-guide.md`
- Create: `docs/superpowers/test-records/2026-09-06-2d-video-overlay-restoration.md`

**Interfaces:**
- Consumes: Pose2Sim demo original MP4 and `D:\test\data` Pose2Sim marker MP4/JSON.
- Produces: acceptance report fields for selected video kind, decoded frame and semantic edge count.

- [ ] **Step 1: Extend acceptance test before changing the script**

```python
def test_pose2sim_marker_video_is_used_when_original_is_absent(self):
    existing = run_acceptance(source, output)["existing_results"]
    self.assertEqual(existing["correction_video_kind"], "pose2sim_overlay")
    self.assertTrue(existing["correction_frame_decoded"])
    self.assertGreater(existing["correction_skeleton_edges"], 0)
```

- [ ] **Step 2: Verify RED, then add acceptance reporting**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p test_existing_results_acceptance.py -v`

Expected RED: acceptance fields are missing. Update the script to resolve and decode one frame directly from the authorized Pose2Sim marker-video source. Keep correction-save assertions confined to the isolated project copy; do not copy, transcode or modify the large source video.

- [ ] **Step 3: Run focused, full and compile checks**

```text
.venv\Scripts\python.exe -m unittest discover -s tests -p test_existing_results_acceptance.py -v
.venv\Scripts\python.exe -m unittest discover -s tests -q
.venv\Scripts\python.exe -m compileall -q app tests scripts
```

Expected: all exit 0.

- [ ] **Step 4: Run real-data and Windows frozen checks**

```text
powershell -ExecutionPolicy Bypass -File scripts\run_real_data_acceptance.ps1 -Root D:\test\data
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
powershell -ExecutionPolicy Bypass -File scripts\smoke_exe.ps1 -Executable outputs\build\dist\MotionAnalysisStudio.exe -Mode All
```

Expected: marker video frame and skeleton overlay acceptance pass; three EXE smoke modes pass.

- [ ] **Step 5: Document, commit and push**

```text
git add scripts/real_data_acceptance.py tests/test_existing_results_acceptance.py docs/user-guide.md docs/superpowers/test-records/2026-09-06-2d-video-overlay-restoration.md docs/superpowers/plans/2026-09-06-2d-video-overlay-restoration.md
git commit -m "test: verify correction video overlay"
git push origin codex/phase-9
```
