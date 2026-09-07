# 视频导入与 Pose2Sim 配置工作流 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户直接导入 Pose2Sim 分析视频和 Config.toml，在中文说明辅助下修改标准及自定义参数，并保证 Pose2Sim 从当前项目根目录读取输入和写入结果。

**Architecture:** 使用项目托管的 `videos` 和 `config/Config.toml`，分别由视频导入服务和保留格式的 TOML 文档模型管理。媒体页面通过现有后台任务控制器复制文件，流程页面通过结构化参数树与源码双视图编辑同一文档；运行入口把配置解析为字典并强制注入当前项目根目录。

**Tech Stack:** Python 3.12、PySide6、OpenCV、标准库 `tomllib`/`unittest`、`tomlkit`、Pose2Sim 0.10.49、PyInstaller。

**Spec:** `docs/superpowers/specs/2026-09-07-video-and-pose2sim-config-workflow-design.md`

## Global Constraints

- 不修改、不转码用户选择的外部视频。
- 导入 Config 后只编辑项目副本，外部 Config 保持不变。
- 参数界面只显示中文说明；英文注释仅作为翻译参考。
- 保留 TOML 的注释、顺序、未知参数和复杂数组表。
- `project_dir` 运行时固定为当前项目根目录。
- 视频复制和探测不得阻塞 Qt 主线程。
- 每个产品行为先写失败测试并确认按预期失败，再写最小实现。
- 不删除或提交本计划之外既有的未跟踪文档。

---

### Task 1: 建立项目托管视频导入模型

**Files:**
- Create: `app/media/importer.py`
- Modify: `app/project/manifest.py`
- Test: `tests/test_video_import_service.py`

**Interfaces:**
- Produces: `normalize_camera_name(name: str) -> str`
- Produces: `VideoImportItem`, `VideoImportPlan`, `VideoImportResult`
- Produces: `VideoImportService.plan(project: ProjectManager, paths: Iterable[Path]) -> VideoImportPlan`
- Produces: `VideoImportService.execute(project, plan, *, replace_existing: bool, token: CancellationToken, progress: Callable[[int, int, Path], None] | None = None) -> VideoImportResult`

- [ ] **Step 1: 写相机名规范化和导入计划失败测试**

```python
def test_plan_matches_numeric_camera_aliases_and_targets_project_videos():
    project.manifest["cameras"] = [{"camera_id": "cam01"}, {"camera_id": "cam02"}]
    plan = VideoImportService.plan(project, [root / "Camera 1.mp4", root / "2.mp4"])
    assert [(item.camera, item.destination.name) for item in plan.items] == [
        ("cam01", "cam01.mp4"), ("cam02", "cam02.mp4")
    ]
```

- [ ] **Step 2: 运行 `\.venv\Scripts\python.exe -m unittest tests.test_video_import_service -v`，确认因导入服务不存在而失败。**
- [ ] **Step 3: 实现不可变计划模型、支持格式过滤、派生视频排除、相机别名规范化和自然排序候选映射。**
- [ ] **Step 4: 添加无相机清单时按 stem 创建记录、数量不等时不猜测、重复目标和缺失来源测试并确认失败。**
- [ ] **Step 5: 实现临时文件复制、flush、原子替换、取消清理、项目相对 `video_path` 和一次性清单保存。**
- [ ] **Step 6: 运行聚焦测试，确认源文件字节不变、中文路径可用、取消后无 `.tmp` 残留。**
- [ ] **Step 7: 提交 `feat: add managed Pose2Sim video imports`。**

### Task 2: 将视频素材页面改为真正的分析视频导入

**Files:**
- Modify: `app/gui/pages/media_page.py`
- Modify: `app/media/bindings.py`
- Test: `tests/test_media_bindings.py`
- Test: `tests/test_video_import_gui.py`

**Interfaces:**
- Consumes: Task 1 的 `VideoImportService.plan/execute`
- Produces: `MediaPage._choose_videos()` 和可取消的后台导入状态

- [ ] **Step 1: 写 GUI 失败测试，要求只有一个主按钮“导入视频”，并通过 `QFileDialog.getOpenFileNames` 接收多个文件。**
- [ ] **Step 2: 运行两个媒体测试文件，确认旧按钮文案、单文件/文件夹入口和清单绑定行为导致预期失败。**
- [ ] **Step 3: 将页面说明改为 Pose2Sim 分析输入；保留 Pose2Sim 标记视频作为二维查看来源，但与分析视频导入分组。**
- [ ] **Step 4: 在执行自然顺序映射或替换冲突前展示一次摘要确认；语义唯一匹配直接执行。**
- [ ] **Step 5: 使用 `ApplicationController` 后台任务执行复制，以线程安全队列传递 `已完成/总数/文件名`，增加“取消导入”。**
- [ ] **Step 6: 测试项目切换和关闭页面会取消任务，旧项目结果不能刷新当前页面。**
- [ ] **Step 7: 运行 `tests.test_media_bindings tests.test_video_import_gui tests.test_gui_workflows` 并提交 `feat: import Pose2Sim input videos from media page`。**

### Task 3: 实现 Config 文件导入和保留格式的参数模型

**Files:**
- Modify: `pyproject.toml`
- Modify: `app/pose2sim/config_document.py`
- Create: `app/pose2sim/config_model.py`
- Modify: `app/pose2sim/__init__.py`
- Test: `tests/test_pose2sim_config_document.py`
- Create: `tests/test_pose2sim_config_model.py`

**Interfaces:**
- Produces: `ConfigDocument.import_file(source: Path, reason: str = "") -> ConfigSaveResult`
- Produces: `ConfigParameter(path, value, value_type, editable, custom)`
- Produces: `ConfigModel.parse(text: str) -> ConfigModel`
- Produces: `ConfigModel.set_value(path: tuple[str, ...], toml_value: str) -> str`
- Produces: `ConfigModel.add_parameter(section: tuple[str, ...], key: str, toml_value: str) -> str`
- Produces: `ConfigModel.remove_parameter(path: tuple[str, ...]) -> str`

- [ ] **Step 1: 添加 `tomlkit>=0.13,<1` 依赖并安装到 `.venv`，记录实际版本。**
- [ ] **Step 2: 写 Config 导入失败测试：有效文件复制到项目副本、原文件不变、旧副本进入备份；无效 TOML 不改变项目文件。**
- [ ] **Step 3: 运行配置文档测试，确认缺少 `import_file` 而失败；实现读取、验证并复用原子保存。**
- [ ] **Step 4: 写参数模型失败测试，使用包含注释、嵌套表、列表和 `[[pose.CUSTOM]]` 的字面量 fixture，修改标量后断言注释、数组表和顺序仍存在。**
- [ ] **Step 5: 用 `tomlkit` 实现文档遍历和值替换；复杂数组表标记不可在表格编辑，但原文完整保留。**
- [ ] **Step 6: 添加非法 TOML 值、重复键、删除不存在参数和未知参数保留测试并实现。**
- [ ] **Step 7: 运行两个配置模型测试并提交 `feat: import and preserve Pose2Sim config files`。**

### Task 4: 建立中文参数帮助和自定义说明持久化

**Files:**
- Create: `app/pose2sim/parameter_help_zh.py`
- Create: `app/pose2sim/custom_help_store.py`
- Create: `tests/test_pose2sim_parameter_help.py`

**Interfaces:**
- Produces: `ParameterHelp(description: str, choices: tuple[str, ...], unit: str, stage: str, warning: str)`
- Produces: `help_for(path: tuple[str, ...]) -> ParameterHelp`
- Produces: `CustomHelpStore.load(project_root: Path) -> dict[str, str]`
- Produces: `CustomHelpStore.save(project_root: Path, values: Mapping[str, str]) -> None`

- [ ] **Step 1: 从用户指定的 Pose2Sim 0.10.49 示例逐项建立手工核对的中文 fixture 期望，覆盖每个可编辑标准参数路径。**
- [ ] **Step 2: 运行帮助测试，确认目录不存在而失败。**
- [ ] **Step 3: 实现中文帮助目录；tooltip 文本仅由中文字段组成，不拼接英文源码注释。**
- [ ] **Step 4: 实现未知参数中文兜底，以及 `config/parameter_help.zh.json` 的原子读写和损坏文件明确报错。**
- [ ] **Step 5: 运行帮助测试并提交 `feat: add Chinese Pose2Sim parameter guidance`。**

### Task 5: 构建参数设置与 TOML 源码双视图

**Files:**
- Create: `app/gui/widgets/config_parameter_editor.py`
- Modify: `app/gui/pages/pipeline_page.py`
- Modify: `app/gui/style.py`
- Modify: `tests/test_pipeline_page.py`
- Create: `tests/test_config_parameter_editor.py`

**Interfaces:**
- Consumes: `ConfigModel`、`help_for`、`CustomHelpStore`
- Produces: `ConfigParameterEditor.set_text(text: str)`、`text() -> str`、`validation_changed`、`text_changed`

- [ ] **Step 1: 写 Qt 失败测试：流程页存在“导入 Config.toml”、两个标签页和 `ⓘ pose_model`，tooltip 是中文且不含示例英文注释。**
- [ ] **Step 2: 写类型编辑失败测试：布尔/枚举使用下拉框，数值修改同步到源码，非法源码禁用保存和运行。**
- [ ] **Step 3: 实现可折叠参数树和编辑 delegate；沿用现有深色主题，`ⓘ` 使用青蓝强调色，键盘焦点清晰。**
- [ ] **Step 4: 实现参数页到源码页立即同步，源码页到参数页在切页/保存时解析；解析失败保留文本并显示行列。**
- [ ] **Step 5: 增加自定义参数对话框，验证章节、键和值，并把中文说明写入 sidecar。**
- [ ] **Step 6: 接入文件选择导入、最近目录、备份结果提示和未保存状态。**
- [ ] **Step 7: 在 1120×720 和 620×480 的 offscreen Qt 测试中验证分栏、滚动和控件可访问。**
- [ ] **Step 8: 运行配置 GUI 测试并提交 `feat: add guided Pose2Sim config editor`。**

### Task 6: 修正 Pose2Sim 运行时项目目录

**Files:**
- Modify: `app/main.py`
- Modify: `app/application/pipeline_launcher.py`
- Modify: `app/application/correction_rerun_launcher.py`
- Modify: `tests/test_pose2sim_pipeline.py`
- Modify: `tests/test_correction_rerun_launch.py`

**Interfaces:**
- Changes: `build_pipeline_commands(config_path, stages, *, project_root: Path, executable=None, frozen=None, pose2sim_python=None)`
- Changes: `run_pose2sim_stage(stage: str, config_path: Path, project_root: Path) -> int`

- [ ] **Step 1: 写失败测试，断言冻结入口和外部 Python 命令都携带项目根目录；阶段函数收到的配置是字典且 `project.project_dir` 为根目录。**
- [ ] **Step 2: 运行流程和修正重跑测试，确认旧命令缺少项目根目录而失败。**
- [ ] **Step 3: 使用 `tomllib` 加载项目副本，复制字典并注入根目录；不修改磁盘 Config 中的 `project_dir` 文本。**
- [ ] **Step 4: 在 `PipelineLauncher.start` 中检查 poseEstimation 所需的 `videos` 目录和至少一个支持的视频；错误时不创建任务。**
- [ ] **Step 5: 更新选择性重跑命令但保持阶段列表不含 `poseEstimation`。**
- [ ] **Step 6: 运行 `tests.test_pose2sim_pipeline tests.test_correction_rerun_launch tests.test_correction_rerun` 并提交 `fix: run Pose2Sim against the current project root`。**

### Task 7: 集成迁移和真实工作流验收

**Files:**
- Modify: `tests/test_gui_workflows.py`
- Create: `tests/test_video_config_workflow_acceptance.py`
- Modify: `docs/user-guide.md`
- Create: `docs/superpowers/test-records/2026-09-07-video-config-workflow.md`

**Interfaces:**
- Consumes: Tasks 1–6 的公开接口
- Produces: 可重复执行的“视频 → Config → 参数 → Pose2Sim 命令”验收流程

- [ ] **Step 1: 写端到端失败测试：四个别名视频导入后位于 `<项目>/videos`，四台相机有相对路径，导入 Config 后修改 `pose.det_frequency`，最终命令指向项目根目录。**
- [ ] **Step 2: 运行验收测试并确认在至少一个尚未接通的边界失败。**
- [ ] **Step 3: 完成页面间刷新：导入视频后二维页面更新来源，导入 Config 后流程运行按钮按有效性更新。**
- [ ] **Step 4: 使用 `D:/test/data` 做只针对已处理结果读取的回归；创建临时项目并复制少量测试视频/Config 做写入验收，不改变外部样本。**
- [ ] **Step 5: 更新用户指南，说明视频被复制到项目、Config 编辑的是副本、中文 `ⓘ` 和项目目录约束。**
- [ ] **Step 6: 运行完整 `unittest discover` 和 `compileall`，把命令、数量、耗时和已知限制写入测试记录。**
- [ ] **Step 7: 提交 `test: verify managed video and config workflow`。**

### Task 8: 冻结构建和发布验收

**Files:**
- Modify: `MotionAnalysisStudio.spec`（仅当新依赖未被自动收集时）
- Modify: `scripts/build_windows.ps1`（仅当依赖安装步骤需要同步时）
- Modify: `docs/superpowers/test-records/2026-09-07-video-config-workflow.md`

**Interfaces:**
- Produces: `outputs/build/dist/MotionAnalysisStudio.exe`

- [ ] **Step 1: 运行构建前依赖探测，确认 `tomlkit`、PySide6、Pose2Sim 和 Caliscope 在指定解释器可导入；缺失依赖按 `pyproject.toml` 安装。**
- [ ] **Step 2: 运行 `scripts/build_windows.ps1` 并检查 DLL 审计；失败时依据构建日志修正明确的收集缺口。**
- [ ] **Step 3: 对 EXE 运行 `--smoke-test`、`--gui-smoke-test` 和 `--workflow-smoke-test`。**
- [ ] **Step 4: 启动 EXE 完成不运行长时分析的最小界面流程：导入视频、导入 Config、修改参数、保存并核对项目文件。**
- [ ] **Step 5: 重新运行完整测试和 `compileall`，确认构建没有污染源码环境。**
- [ ] **Step 6: 更新测试记录并提交 `build: package managed video and config workflow`。**

## 最终验收命令

```powershell
D:\CODEX\2026-09-02\d-codex-2026-09-01-ni-2\.venv\Scripts\python.exe -m unittest discover -s D:\CODEX\2026-09-02\d-codex-2026-09-01-ni-2\tests -q
D:\CODEX\2026-09-02\d-codex-2026-09-01-ni-2\.venv\Scripts\python.exe -m compileall -q D:\CODEX\2026-09-02\d-codex-2026-09-01-ni-2\app D:\CODEX\2026-09-02\d-codex-2026-09-01-ni-2\tests
D:\CODEX\2026-09-02\d-codex-2026-09-01-ni-2\outputs\build\dist\MotionAnalysisStudio.exe --smoke-test
D:\CODEX\2026-09-02\d-codex-2026-09-01-ni-2\outputs\build\dist\MotionAnalysisStudio.exe --gui-smoke-test
D:\CODEX\2026-09-02\d-codex-2026-09-01-ni-2\outputs\build\dist\MotionAnalysisStudio.exe --workflow-smoke-test
```
