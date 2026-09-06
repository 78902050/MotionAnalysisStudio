# 三维骨骼轨迹回放实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增可从现有 TRC/C3D 播放三维骨骼运动轨迹的独立 PySide6 页面。

**Architecture:** 新增 `app.playback` 只读领域包，负责来源发现、容错播放读取、投影和时钟；GUI 页面只处理选择、渲染与导航。三维和二维共用语义骨架拓扑，严格分析解析规则不因播放器容错而放宽。

**Tech Stack:** Python 3.12、PySide6、NumPy、c3d 0.6.0、Pose2Sim skeletons、unittest。

**Spec:** `docs/superpowers/specs/2026-09-06-3d-skeleton-playback-design.md`

**Implementation status:** 已于 2026-09-06 完成；最终证据见 `docs/superpowers/test-records/2026-09-06-3d-skeleton-playback.md`。下列复选步骤保留为可重复执行的重建流程。

## Global Constraints

- TRC/C3D 只读，不重写、不转换、不删除。
- 不增加 PyQt5、Kinetics Toolkit、VTK 或其他三维 GUI 依赖。
- 缺失点保持 NaN，不显示为原点。
- 骨架语义不唯一时只画点，不猜测连接关系。
- 解析和目录扫描不得阻塞 GUI 主线程。
- 播放时间由真实时间轴决定，不按定时器触发次数累加。
- 每项生产改动前先写并运行失败测试。

---

### Task 1: 三维来源目录和人物/版本分组

**Files:**
- Create: `app/playback/__init__.py`
- Create: `app/playback/model.py`
- Create: `app/playback/catalog.py`
- Test: `tests/test_playback_catalog.py`

**Interfaces:**
- Produces: `TrajectorySource(path, format, trial_id, person_id, variant)`
- Produces: `TrajectoryCatalog.scan(project_root: Path) -> tuple[TrajectorySource, ...]`

- [ ] **Step 1: Write failing literal filename-grouping tests**

Create `touch()` in the test module so each example below materializes a real empty catalog candidate below an isolated temporary `pose-3d` directory.

```python
def test_catalog_groups_pose2sim_variants_without_ranking_quality(self):
    touch("pose-3d/test1_P0_1-739.trc")
    touch("pose-3d/test1_P0_1-739_filt_butterworth.trc")
    touch("pose-3d/test1_P0_1-739_filt_butterworth_LSTM.c3d")
    sources = TrajectoryCatalog.scan(root)
    self.assertEqual(
        [(item.person_id, item.variant, item.format) for item in sources],
        [("P0", "raw", "trc"), ("P0", "butterworth", "trc"), ("P0", "butterworth_lstm", "c3d")],
    )
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p test_playback_catalog.py -v`

Expected: `app.playback` does not exist.

- [ ] **Step 3: Implement immutable models and deterministic catalog**

Scan only `pose-3d/*.trc` and `pose-3d/*.c3d`, parse `P<number>` semantically, preserve unknown suffix text as a display variant, and sort by trial/person/variant with TRC before C3D. Do not label one variant “best”.

- [ ] **Step 4: Run focused tests**

Run each file with `unittest discover`: `$patterns=@('test_playback_catalog.py','test_existing_analysis_flow.py'); foreach($pattern in $patterns){ .venv\Scripts\python.exe -m unittest discover -s tests -p $pattern -v; if($LASTEXITCODE -ne 0){ exit $LASTEXITCODE } }`

Expected: all pass.

- [ ] **Step 5: Commit and push**

```text
git add app/playback tests/test_playback_catalog.py
git commit -m "feat: discover 3d playback trajectories"
git push origin codex/phase-9
```

### Task 2: 容错 TRC 与 C3D 播放读取器

**Files:**
- Create: `app/playback/readers.py`
- Test: `tests/test_playback_readers.py`

**Interfaces:**
- Produces: `PlaybackTrajectory(frames, times, points, coordinate_unit, source, diagnostics)`
- Produces: `load_playback_trajectory(source: TrajectorySource) -> PlaybackTrajectory`

- [ ] **Step 1: Write failing reader tests**

Implement `write_trc()` and `write_c3d()` as test-only fixture writers using the real TRC text structure and installed `c3d.Writer`; the product reader must not depend on these helpers.

```python
def test_trc_player_loads_actual_rows_and_reports_header_mismatch(self):
    source = write_trc(declared_frames=3, rows=[FRAME_1, FRAME_2])
    trajectory = load_playback_trajectory(source)
    self.assertEqual(trajectory.frames, (1, 2))
    self.assertEqual(trajectory.diagnostics[0].code, "frame_count_mismatch")

def test_c3d_reader_trims_labels_and_converts_invalid_residual_to_nan(self):
    source = write_c3d(labels=("Hip   ",), frames=(VALID_POINT, INVALID_POINT))
    trajectory = load_playback_trajectory(source)
    self.assertEqual(tuple(trajectory.points), ("Hip",))
    self.assertTrue(math.isnan(trajectory.points["Hip"][1][0]))
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p test_playback_readers.py -v`

Expected: reader module or load function missing.

- [ ] **Step 3: Implement format-specific readers**

Parse TRC rows independently of `Trajectory.from_trc()` while sharing unit aliases and point types. Allow only header-count mismatch as a warning; reject non-increasing frames/times and malformed rows. Use `c3d.Reader`, close handles deterministically, normalize residual-invalid points to three NaNs, and emit explicit diagnostics for point-only C3D support.

- [ ] **Step 4: Run reader and strict-analysis regressions**

Run each file with `unittest discover`: `$patterns=@('test_playback_readers.py','test_analysis_contracts.py','test_metrics.py'); foreach($pattern in $patterns){ .venv\Scripts\python.exe -m unittest discover -s tests -p $pattern -v; if($LASTEXITCODE -ne 0){ exit $LASTEXITCODE } }`

Expected: playback reader accepts the mismatch fixture; strict `Trajectory.from_trc()` still rejects it.

- [ ] **Step 5: Commit and push**

```text
git add app/playback/readers.py tests/test_playback_readers.py
git commit -m "feat: read trc and c3d for playback"
git push origin codex/phase-9
```

### Task 3: 三维投影、适应视图和语义骨架帧

**Files:**
- Create: `app/playback/projection.py`
- Modify: `app/visualization/skeleton.py`
- Test: `tests/test_playback_projection.py`

**Interfaces:**
- Produces: `ViewTransform(yaw, pitch, zoom, pan_x, pan_y, perspective)`
- Produces: `project_points(points, transform, viewport) -> dict[str, QPointF | None]`
- Consumes: `SkeletonTopologyRepository.edges_for_labels(labels) -> tuple[tuple[str, str], ...]`

- [ ] **Step 1: Write failing hand-calculated projection tests**

```python
def test_front_and_side_views_project_known_axes(self):
    points = {"origin": (0.0, 0.0, 0.0), "x": (1.0, 0.0, 0.0)}
    front = project_points(points, FRONT_VIEW, (200, 100))
    side = project_points(points, SIDE_VIEW, (200, 100))
    self.assertEqual(front["origin"], QPointF(100.0, 50.0))
    self.assertGreater(front["x"].x(), 100.0)
    self.assertAlmostEqual(side["x"].x(), 100.0)

def test_missing_point_is_not_projected_to_origin(self):
    projected = project_points({"Hip": (math.nan, math.nan, math.nan)}, FRONT_VIEW, (200, 100))
    self.assertIsNone(projected["Hip"])
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p test_playback_projection.py -v`

Expected: projection APIs missing.

- [ ] **Step 3: Implement projection and label-only topology matching**

Use explicit rotation matrices, finite-point bounds and clamped perspective depth. Add unique-best semantic topology selection based on label coverage and required torso chain. Return no edges on tied/insufficient matches.

- [ ] **Step 4: Run projection and 2D topology regressions**

Run each file with `unittest discover`: `$patterns=@('test_playback_projection.py','test_skeleton_topology.py','test_correction_overlay.py'); foreach($pattern in $patterns){ .venv\Scripts\python.exe -m unittest discover -s tests -p $pattern -v; if($LASTEXITCODE -ne 0){ exit $LASTEXITCODE } }`

Expected: all pass.

- [ ] **Step 5: Commit and push**

```text
git add app/playback/projection.py app/visualization/skeleton.py tests/test_playback_projection.py
git commit -m "feat: project semantic 3d skeletons"
git push origin codex/phase-9
```

### Task 4: 播放时钟和原生三维画布

**Files:**
- Create: `app/playback/clock.py`
- Create: `app/gui/widgets/__init__.py`
- Create: `app/gui/widgets/trajectory_canvas.py`
- Test: `tests/test_playback_clock.py`
- Test: `tests/test_trajectory_canvas.py`

**Interfaces:**
- Produces: `PlaybackClock.start(now, source_time, speed)`, `pause(now)`, `time_at(now)`, `frame_index(times, now)`
- Produces: `TrajectoryCanvas.set_trajectory(trajectory, edges)`, `set_frame_index(index)`, `fit_all()`

- [ ] **Step 1: Write failing clock and canvas state tests**

```python
def test_clock_uses_elapsed_time_and_does_not_accumulate_timer_ticks(self):
    clock.start(now=10.0, source_time=1.0, speed=2.0)
    self.assertEqual(clock.time_at(10.5), 2.0)
    self.assertEqual(clock.frame_index((1.0, 1.5, 2.0), 10.5), 2)

def test_canvas_does_not_connect_trail_across_nan_gap(self):
    canvas.set_trajectory(trajectory_with_gap, (("Hip", "Neck"),))
    canvas.set_frame_index(2)
    self.assertEqual(canvas.visible_trail_segment_count("Hip"), 1)
```

- [ ] **Step 2: Run tests and verify RED**

Run each file with `unittest discover`: `$patterns=@('test_playback_clock.py','test_trajectory_canvas.py'); foreach($pattern in $patterns){ .venv\Scripts\python.exe -m unittest discover -s tests -p $pattern -v; if($LASTEXITCODE -ne 0){ exit $LASTEXITCODE } }`

Expected: clock and canvas modules missing.

- [ ] **Step 3: Implement monotonic clock and QPainter canvas**

Keep clock free of Qt for deterministic tests. Draw grid, axes, trails, edges and points from the current immutable trajectory. Add mouse rotation, Shift-left/middle pan, wheel zoom and nearest-visible-point selection. Keep trail storage bounded by the selected 0–120-frame window.

- [ ] **Step 4: Run clock/canvas and GUI layout tests**

Run each file with `unittest discover`: `$patterns=@('test_playback_clock.py','test_trajectory_canvas.py','test_gui_layout.py'); foreach($pattern in $patterns){ .venv\Scripts\python.exe -m unittest discover -s tests -p $pattern -v; if($LASTEXITCODE -ne 0){ exit $LASTEXITCODE } }`

Expected: all pass.

- [ ] **Step 5: Commit and push**

```text
git add app/playback/clock.py app/gui/widgets tests/test_playback_clock.py tests/test_trajectory_canvas.py
git commit -m "feat: render interactive 3d trajectories"
git push origin codex/phase-9
```

### Task 5: 三维回放页面和后台加载

**Files:**
- Create: `app/gui/pages/playback_3d_page.py`
- Modify: `app/gui/main_window.py`
- Modify: `app/gui/style.py`
- Test: `tests/test_playback_3d_page.py`

**Interfaces:**
- Produces: page ID `playback_3d`
- Produces: `Playback3DPage.set_project(project)`, `open_target(person_id, frame)` and `stop()`
- Consumes: `TrajectoryCatalog`, `load_playback_trajectory`, `PlaybackClock`, `TrajectoryCanvas`

- [ ] **Step 1: Write failing page registration and playback tests**

```python
def test_project_trc_is_listed_loaded_and_played_without_blocking(self):
    window = MainWindow()
    self.assertTrue(window.open_project(project_with_trc))
    page = window._pages["playback_3d"]
    self.assertGreater(page.source_selector.count(), 0)
    wait_until(lambda: page.trajectory is not None)
    page.play()
    wait_until(lambda: page.frame_index > 0)
    self.assertLess(max_heartbeat_gap, 0.250)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p test_playback_3d_page.py -v`

Expected: missing page key/module.

- [ ] **Step 3: Implement resizable page and cancellable loader**

Build source controls, central canvas, collapsible inspector and bottom timeline. Load via the existing task controller with project ID/generation checks. Drive rendering with a 16 ms `QTimer` and `PlaybackClock`; skip render frames when necessary without changing source time. Persist only view/layout settings in `QSettings`.

- [ ] **Step 4: Run page, shell and lifecycle tests**

Run each file with `unittest discover`: `$patterns=@('test_playback_3d_page.py','test_gui_shell.py','test_gui_layout.py','test_application_controller.py'); foreach($pattern in $patterns){ .venv\Scripts\python.exe -m unittest discover -s tests -p $pattern -v; if($LASTEXITCODE -ne 0){ exit $LASTEXITCODE } }`

Expected: all pass; page closes with no active timer/task.

- [ ] **Step 5: Commit and push**

```text
git add app/gui/pages/playback_3d_page.py app/gui/main_window.py app/gui/style.py tests/test_playback_3d_page.py
git commit -m "feat: add 3d skeleton playback page"
git push origin codex/phase-9
```

### Task 6: 三维质检精确跳转

**Files:**
- Modify: `app/gui/pages/quality_3d_page.py`
- Modify: `app/gui/main_window.py`
- Test: `tests/test_quality_3d_playback_jump.py`

**Interfaces:**
- Produces: `Quality3DPage.playback_requested = Signal(str, int)`
- Consumes: `Playback3DPage.open_target(person_id: str, frame: int)`

- [ ] **Step 1: Write failing semantic jump test**

```python
def test_quality_issue_opens_matching_person_and_frame_in_player(self):
    quality.select_issue(issue_for(person="P1", frame=286))
    quality.open_in_playback()
    self.assertIs(window.current_page, window._pages["playback_3d"])
    self.assertEqual(window.current_page.pending_target, ("P1", 286))
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p test_quality_3d_playback_jump.py -v`

Expected: signal/button missing.

- [ ] **Step 3: Implement jump with explicit failure states**

Enable the button only when the selected issue has a non-negative 3D frame. Pass semantic person ID when present; if the catalog has zero or multiple matches, navigate to the player but require source selection and show the reason.

- [ ] **Step 4: Run quality and playback regressions**

Run each file with `unittest discover`: `$patterns=@('test_quality_3d_playback_jump.py','test_quality_pages.py','test_playback_3d_page.py'); foreach($pattern in $patterns){ .venv\Scripts\python.exe -m unittest discover -s tests -p $pattern -v; if($LASTEXITCODE -ne 0){ exit $LASTEXITCODE } }`

Expected: all pass.

- [ ] **Step 5: Commit and push**

```text
git add app/gui/pages/quality_3d_page.py app/gui/main_window.py tests/test_quality_3d_playback_jump.py
git commit -m "feat: open quality issues in 3d playback"
git push origin codex/phase-9
```

### Task 7: 真实轨迹、完整回归和 EXE 验收

**Files:**
- Modify: `scripts/real_data_acceptance.py`
- Modify: `tests/test_existing_results_acceptance.py`
- Modify: `docs/user-guide.md`
- Create: `docs/superpowers/test-records/2026-09-06-3d-skeleton-playback.md`

**Interfaces:**
- Consumes: `D:\test\data` TRC/C3D copied into isolated acceptance output.
- Produces: playback format/frame/marker/diagnostic/heartbeat fields in `acceptance.json`.

- [ ] **Step 1: Add failing acceptance assertions**

```python
def test_real_pose2sim_trajectory_is_ready_for_playback(self):
    playback = run_acceptance(source, output)["playback_3d"]
    self.assertIn(playback["format"], {"trc", "c3d"})
    self.assertGreater(playback["frame_count"], 1)
    self.assertGreater(playback["marker_count"], 1)
    self.assertGreater(playback["skeleton_edge_count"], 1)
    self.assertLess(playback["max_heartbeat_gap_ms"], 250)
```

- [ ] **Step 2: Verify RED, then add isolated real-data playback check**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p test_existing_results_acceptance.py -v`

Expected RED: `playback_3d` report is missing. Copy one TRC and matching C3D to output, load/read only the copies, and report diagnostics without changing source data.

- [ ] **Step 3: Run full verification**

```text
.venv\Scripts\python.exe -m unittest discover -s tests -q
.venv\Scripts\python.exe -m compileall -q app tests scripts
powershell -ExecutionPolicy Bypass -File scripts\run_real_data_acceptance.ps1 -Root D:\test\data
```

Expected: all exit 0; a frame-count mismatch is a recorded playback warning, not a silent success.

- [ ] **Step 4: Rebuild and smoke the frozen application**

```text
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
powershell -ExecutionPolicy Bypass -File scripts\smoke_exe.ps1 -Executable outputs\build\dist\MotionAnalysisStudio.exe -Mode All
```

Expected: DLL audit and all three smoke modes pass; workflow smoke constructs and advances the 3D player.

- [ ] **Step 5: Document, commit and push**

```text
git add scripts/real_data_acceptance.py tests/test_existing_results_acceptance.py docs/user-guide.md docs/superpowers/test-records/2026-09-06-3d-skeleton-playback.md docs/superpowers/plans/2026-09-06-3d-skeleton-playback.md
git commit -m "test: verify 3d skeleton playback"
git push origin codex/phase-9
```
