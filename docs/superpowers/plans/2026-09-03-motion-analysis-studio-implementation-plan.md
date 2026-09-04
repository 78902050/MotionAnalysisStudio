# Motion Analysis Studio 重建 Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

Goal: 从空项目重新建立一个可恢复、可审计、可验证的多相机运动分析桌面应用，覆盖阶段 1～9 的完整闭环。

Architecture: 采用领域模型、应用服务、第三方适配器、后台任务和 PySide6 界面五层结构。所有跨阶段定位依赖相机、时间轴、帧号、语义人物和关节点名称。

Tech Stack: Python 3.12、PySide6、OpenCV、NumPy、JSON/JSONL、TOML、标准库 unittest、PyInstaller。

Spec: docs/superpowers/specs/2026-09-03-motion-analysis-studio-rebuild-design.md、docs/superpowers/specs/2026-09-03-motion-analysis-studio-data-contract.md、docs/superpowers/specs/2026-09-03-motion-analysis-studio-ui-design.md

## Global Constraints

- 不修改原始 MP4，不转码原始视频。
- 不修改已安装的 Pose2Sim、Caliscope 或其 site-packages 文件。
- 不写死同步偏移、人物编号、关节点裸索引或安装路径。
- 自动结果只能作为候选，写入、身份关联和人工点位移动必须人工确认。
- 视频读取、JSON 扫描、质量计算、报告生成和重跑不得阻塞 GUI 主线程。
- 项目清单使用 schema v3；旧项目 v2 迁移必须幂等，保留 manual_pose_edits。
- 测试默认使用 python -m unittest；不因缺少 pytest 自动安装依赖。
- 每个任务必须先写失败测试，再实现，再运行聚焦测试和回归测试。
- 每个阶段完成后必须建立 Git 提交、源码压缩归档、测试记录和已知限制记录。
- 真实项目 D:\test\test 只能复制到临时目录验收，原目录禁止写入。

## 代码目录约定

~~~text
app/domain                  领域对象、地址、阶段图
app/project                 清单、路径和迁移
app/io                      原子文件、JSONL、备份和事务
app/tasks                   QThread 任务协议和任务中心
app/adapters/pose2sim       Pose2Sim 配置、阶段和日志适配
app/adapters/caliscope      标定数据读取适配
app/media                   后台视频帧服务和缓存
app/quality                 指标、问题、报告和查看器
app/correction              2D 修正、历史、恢复和选择性重跑
app/synchronization         同步映射、诊断和人工校准
app/association              多人关联、候选和人工确认
app/analysis                运动学、事件、周期和比较
app/reporting               报告和导出
app/gui                     主窗口、页面、布局、样式和绑定
tests                       单元、集成、GUI 和验收测试
~~~

## Task 1: 建立安全重建骨架

Files: pyproject.toml、.gitignore、app/__init__.py、tests/test_bootstrap.py、scripts/run_tests.ps1、scripts/archive_project.ps1。

Interfaces:

~~~python
def project_version() -> str: ...
def runtime_capabilities() -> dict[str, bool]: ...
~~~

- [ ] 写 test_package_reports_version_and_no_development_path；先运行 python -m unittest tests.test_bootstrap -v，确认因 app 不存在而失败。
- [ ] 创建包、版本和依赖声明；测试脚本只调用 unittest，不隐式安装依赖；忽略虚拟环境、构建目录、缓存和项目数据。
- [ ] 运行聚焦测试、python -m compileall -q app tests，再运行完整 unittest。
- [ ] 提交：git commit -m "chore: bootstrap rebuild project"。

## Task 2: 建立领域定位对象和阶段图

Files: app/domain/addresses.py、app/domain/stages.py、app/domain/issues.py、tests/test_domain_contract.py。

Interfaces:

~~~python
@dataclass(frozen=True)
class FrameAddress:
    camera: str
    timeline: Literal["raw", "synchronized", "pose2d", "pose3d"]
    frame: int

@dataclass(frozen=True)
class PersonAddress:
    project_person_id: str
    track_segment_id: str | None = None
    raw_person_index: int | None = None

@dataclass(frozen=True)
class CorrectionTarget:
    address: FrameAddress
    project_person_id: str | None
    raw_person_index: int
    keypoint_name: str
    keypoint_index: int

class StageGraph:
    def dependencies(self, stage: str) -> tuple[str, ...]: ...
    def invalidate_from(self, stage: str, reason: str,
                       operation_id: str | None = None) -> list[str]: ...
    def rerun_stages_for(self, change: str) -> tuple[str, ...]: ...
~~~

- [ ] 写负帧号、未知时间轴、空相机、语义人物和选择性重跑测试；先运行测试确认失败。
- [ ] 实现不可变地址、PersonAddress、KeypointAddress 和显式 StageGraph；未知阶段必须报错。
- [ ] 运行 domain 聚焦测试、完整 unittest 和 compileall。
- [ ] 提交：git commit -m "feat: define semantic addresses and stage graph"。

## Task 3: 项目清单和 v2 到 v3 迁移

Files: app/project/manifest.py、app/project/manager.py、app/project/migration.py、tests/test_project_manager.py。

Interfaces:

~~~python
class ProjectManager:
    @classmethod
    def create(cls, root: Path, name: str) -> "ProjectManager": ...
    @classmethod
    def open(cls, root: Path) -> "ProjectManager": ...
    def migrate_if_needed(self) -> bool: ...
    def path_for(self, key: str) -> Path: ...
    def save_manifest(self) -> None: ...
~~~

- [ ] 先写新项目目录、v3 清单、中文路径、v2 幂等迁移和保留 manual_pose_edits 的失败测试。
- [ ] 实现目录创建、相对路径、阶段初始状态和迁移记录；迁移不运行 Pose2Sim，不使已有 completed 结果失效。
- [ ] 运行项目聚焦测试、完整 unittest 和 compileall。
- [ ] 提交：git commit -m "feat: add project manifest v3 and migration"。

## Task 4: 原子存储、JSONL 历史和事务恢复

Files: app/io/atomic.py、app/io/jsonl.py、app/io/transactions.py、tests/test_atomic_storage.py。

Interfaces:

~~~python
class AtomicJsonStore:
    @staticmethod
    def replace(path: Path, data: object) -> None: ...

class JsonlStore:
    def append(self, record: dict[str, object]) -> None: ...
    def read(self) -> tuple[list[dict[str, object]], list[str]]: ...

class TransactionRecovery:
    def recover_incomplete(self) -> list[str]: ...
~~~

- [ ] 先写替换失败保持旧 JSON、首次备份不覆盖、截断 JSONL 报告行号和未完成事务检测测试，确认失败。
- [ ] 实现同目录临时文件、flush、fsync、原子替换、独占备份和可报告的 JSONL 读取。
- [ ] 运行聚焦测试、完整 unittest 和 compileall。
- [ ] 提交：git commit -m "feat: add atomic storage and transaction recovery"。

## Task 5: 后台任务与第三方适配器

Files: app/tasks/base.py、app/tasks/center.py、app/adapters/pose2sim/runner.py、app/adapters/pose2sim/stage_process.py、app/adapters/caliscope/reader.py、tests/test_task_center.py、tests/test_adapters.py。

Interfaces:

~~~python
@dataclass(frozen=True)
class TaskRequest:
    project_id: str
    generation: int
    name: str
    payload: dict[str, object]

class PipelineRunner:
    def run(self, request: TaskRequest, stages: Sequence[str]) -> RunResult: ...
    def cancel(self, task_id: str) -> None: ...
~~~

- [ ] 先写旧项目结果隔离、任务取消、阶段允许列表、外部命令配置和 stdout/stderr 日志测试，确认失败。
- [ ] 实现 QThread worker、项目和 generation 校验、协作取消、子进程清理和日志落盘；适配器禁止写 site-packages。
- [ ] 运行聚焦测试、完整 unittest 和 compileall。
- [ ] 提交：git commit -m "feat: add background tasks and external adapters"。

## Task 6: 阶段 1 三维质量审计

Files: app/quality/model.py、app/quality/audit.py、app/quality/report_store.py、tests/test_quality_audit.py。

Interfaces:

~~~python
class QualityAuditService:
    def analyze(self, project: ProjectManager) -> QualityReport: ...
    def save(self, report: QualityReport) -> None: ...

class QualityReport:
    def issues(self) -> tuple[QualityIssue, ...]: ...
    def metrics(self) -> dict[str, float | int | None]: ...
    def target(self, issue_id: str) -> CorrectionTarget | None: ...
~~~

- [ ] 先写实际人数、2D 检测人数、关联人数、轨迹段数分离，关节点名称映射，完整语义目标，缺失输入和问题合并测试，确认失败。
- [ ] 实现重投影误差、有效点率、缺失率、插值率、参与相机数、覆盖区间和相机贡献；缺失层必须产生明确问题。
- [ ] 运行质量聚焦测试、完整 unittest 和 compileall。
- [ ] 提交：git commit -m "feat: add semantic 3d quality audit"。

## Task 7: GUI 壳、滚动容器和可调分栏

Files: app/gui/main_window.py、app/gui/layout.py、app/gui/style.py、app/gui/task_center.py、tests/test_gui_shell.py。

Interfaces:

~~~python
class MainWindow(QMainWindow):
    def open_project(self, project: ProjectManager) -> None: ...
    def navigate(self, page_id: str) -> None: ...
    def request_close_with_unsaved_guard(self) -> bool: ...

def make_scrollable_panel(widget: QWidget) -> QScrollArea: ...
def make_resizable_splitter(*widgets: QWidget) -> QSplitter: ...
~~~

- [ ] 先写所有页面注册、QSplitter、620×480 可滚动访问、1120×720 不重叠和无开发机绝对路径测试；以 offscreen Qt 运行，确认失败。
- [ ] 实现可折叠导航、任务状态栏、页面注册、滚动容器、QSplitter 和 QSettings 持久化；禁止绝对定位。
- [ ] 运行 GUI 聚焦测试、完整 unittest 和 compileall。
- [ ] 提交：git commit -m "feat: add resizable desktop workspace shell"。

## Task 8: 后台多相机帧服务

Files: app/media/frame_provider.py、app/media/lru_cache.py、app/gui/pages/media_page.py、app/gui/pages/quality_page.py、tests/test_frame_provider.py。

Interfaces:

~~~python
class MultiViewFrameProvider(QObject):
    frame_ready = Signal(str, int, object)
    frame_failed = Signal(str, int, str)

    def request(self, address: FrameAddress, priority: int = 0) -> None: ...
    def prefetch(self, addresses: Iterable[FrameAddress]) -> None: ...
    def cancel(self, request_group: str) -> None: ...
    def clear(self) -> None: ...
~~~

- [ ] 先写 VideoCapture 只在解码线程使用、有界 LRU、项目切换隔离和四相机 heartbeat 测试，确认失败。
- [ ] 实现每相机后台解码器、当前帧前后邻帧缓存、导航优先级和项目 generation 标记。
- [ ] 运行聚焦测试；连续 2 秒请求 4 路视频时，Qt 事件循环停顿不得超过 250 ms；然后运行完整 unittest。
- [ ] 提交：git commit -m "feat: add asynchronous multiview frame provider"。

## Task 9: 阶段 2 二维修正闭环

Files: app/correction/model.py、app/correction/history.py、app/correction/session.py、app/correction/rerun.py、app/gui/pages/correction_page.py、tests/test_correction_model.py、tests/test_correction_history.py、tests/test_correction_session.py、tests/test_correction_rerun.py。

Interfaces:

~~~python
class CorrectionHistory:
    def append(self, operation: CorrectionOperation) -> None: ...
    def operations(self, session_id: str | None = None) -> list[CorrectionOperation]: ...
    def restore_file(self, json_path: Path, reason: str) -> int: ...

class CorrectionSession:
    def apply_point(self, target: CorrectionTarget, x: float, y: float,
                    confidence: float = 1.0) -> None: ...
    def undo(self) -> None: ...
    def redo(self) -> None: ...
    def reset_frame(self, frame: int) -> None: ...
    def has_unsaved_changes(self) -> bool: ...

CORRECTION_RERUN_STAGES = (
    "triangulation", "filtering", "markerAugmentation", "kinematics"
)
~~~

- [ ] 先写置信度 1.0、坐标和置信度完整 undo/redo、首次备份、恢复历史、保存不启动任务、重跑不含 poseEstimation、模糊映射禁用和未保存导航保护测试，确认失败。
- [ ] 实现原子 JSON 保存、JSONL 审计、当前帧恢复、整文件/批次恢复、QSettings 步长和 generation 安全重跑。
- [ ] 运行 4 个 correction 聚焦模块、完整 unittest、compileall，并验证原视频不变。
- [ ] 提交：git commit -m "feat: add auditable 2d correction loop"。

## Task 10: 阶段 3 相机标定诊断

Files: app/calibration/model.py、app/calibration/diagnostics.py、app/calibration/importer.py、app/gui/pages/calibration_page.py、tests/test_calibration_import.py、tests/test_calibration_diagnostics.py。

Interfaces:

~~~python
class CalibrationImporter:
    def inspect(self, path: Path) -> CalibrationFingerprint: ...
    def import_file(self, project: ProjectManager, path: Path) -> ImportResult: ...

class CalibrationDiagnostics:
    def analyze(self, project: ProjectManager) -> CalibrationReport: ...

@dataclass(frozen=True)
class ImportResult:
    changed: bool
    active_path: Path
    fingerprint: str
    invalidated_stages: tuple[str, ...]
~~~

- [ ] 先写新文件内容导致指纹变化、相同文件幂等、损坏文件、缺失相机、不可写目录和当前激活文件可见测试，确认失败。
- [ ] 实现内容指纹、激活文件元数据、原子导入事务和逐相机诊断，不修改外部标定源文件。
- [ ] 运行聚焦、完整 unittest 和 compileall。
- [ ] 提交：git commit -m "feat: add calibration diagnostics and import transactions"。

## Task 11: 阶段 4 同步分析和人工校准

Files: app/synchronization/model.py、app/synchronization/analyzer.py、app/synchronization/overrides.py、app/gui/pages/synchronization_page.py、tests/test_synchronization.py。

Interfaces:

~~~python
class SynchronizationAnalyzer:
    def analyze(self, project: ProjectManager) -> SynchronizationReport: ...
    def mapping(self, camera: str, synchronized_frame: int) -> FrameMapping: ...

@dataclass(frozen=True)
class SynchronizationOverride:
    camera: str
    source: str
    frame_delta: int | None
    mapping_path: Path | None
~~~

- [ ] 先写数据映射、逐帧表、时间戳映射、可变偏移和无相机名特判测试，确认失败。
- [ ] 实现从 Pose2Sim 结果、时间戳或项目表读取映射；人工偏移保存为 override；同步帧和原始帧分开显示。
- [ ] 运行聚焦和完整测试，并扫描业务代码确认没有固定 cam03/cam04 偏移。
- [ ] 提交：git commit -m "feat: add data-driven synchronization mapping"。

## Task 12: 阶段 5 多人身份关联

Files: app/association/model.py、app/association/analyzer.py、app/association/suggestions.py、app/association/overrides.py、app/association/materializer.py、app/gui/pages/association_page.py、tests/test_association.py。

Interfaces:

~~~python
class AssociationAnalyzer:
    def analyze(self, project: ProjectManager, report: QualityReport) -> AssociationReport: ...

class AssociationOverrideStore:
    def save_confirmed(self, candidate: AssociationCandidate) -> AssociationOverride: ...
    def effective_constraints(self, report: AssociationReport) -> tuple[AssociationOverride, ...]: ...

class AssociationMaterializer:
    def materialize(self, project: ProjectManager,
                    constraints: Sequence[AssociationOverride]) -> MaterializeResult: ...

@dataclass(frozen=True)
class AssociationCandidate:
    candidate_id: str
    camera: str
    synchronized_frame: int
    raw_person_index: int
    score: float
    exact: bool
    explanation: str

@dataclass(frozen=True)
class AssociationOverride:
    override_id: str
    project_person_id: str
    camera: str
    synchronized_frame: int
    raw_person_index: int
    fingerprint: str
~~~

- [ ] 先写缺失映射、层缺失/重复、坏人物 payload、数组顺序变化、多候选、保留未约束人物、缺口分段和物化结果恢复测试，确认失败。
- [ ] 实现骨架指纹、轨迹段、候选解释、人工确认、原子物化和备份；多候选禁止自动应用。
- [ ] 运行聚焦、完整 unittest 和 compileall。
- [ ] 提交：git commit -m "feat: add human-confirmed person association"。

## Task 13: 阶段 6 运动学和技术指标

Files: app/analysis/model.py、app/analysis/coordinates.py、app/analysis/metrics.py、app/analysis/filters.py、app/gui/pages/analysis_page.py、tests/test_metrics.py。

Interfaces:

~~~python
@dataclass(frozen=True)
class MetricDefinition:
    metric_id: str
    unit: str
    required_labels: tuple[str, ...]

@dataclass(frozen=True)
class MetricConfig:
    sampling_rate_hz: float
    coordinate_unit: str
    filter_name: str | None

class Trajectory: ...
class MetricTable: ...

class MetricEngine:
    def calculate(self, trajectory: Trajectory,
                  definitions: Sequence[MetricDefinition],
                  config: MetricConfig) -> MetricTable: ...
~~~

- [ ] 先写单位、坐标约定、有限差分、缺口边界、滤波参数和缺失传播测试，确认失败。
- [ ] 实现显式单位/坐标元数据、缺口隔离、后台计算和指标输入溯源。
- [ ] 运行聚焦、完整 unittest、compileall 和手工数值夹具。
- [ ] 提交：git commit -m "feat: add configurable kinematic metrics"。

## Task 14: 阶段 7 事件、周期和技术阶段

Files: app/analysis/events.py、app/analysis/cycles.py、app/analysis/event_history.py、app/gui/pages/events_page.py、tests/test_events_cycles.py。

Interfaces:

~~~python
class EventDetector:
    def detect(self, metrics: MetricTable, rule: EventRule) -> tuple[Event, ...]: ...

class CycleBuilder:
    def build(self, events: Sequence[Event]) -> tuple[Cycle, ...]: ...
~~~

- [ ] 先写确定性阈值事件、缺失区间不生成事件、人工调整、周期边界和帧/时间往返测试，确认失败。
- [ ] 实现可重复规则、事件历史、人工调整和不跨缺口的周期构建。
- [ ] 运行聚焦、完整 unittest 和 compileall。
- [ ] 提交：git commit -m "feat: add event and cycle analysis"。

## Task 15: 阶段 8 对比、报告和导出

Files: app/analysis/comparison.py、app/reporting/report_builder.py、app/reporting/export.py、app/gui/pages/comparison_page.py、tests/test_comparison_reporting.py。

Interfaces:

~~~python
@dataclass(frozen=True)
class ComparisonRequest:
    project_ids: tuple[str, ...]
    person_ids: tuple[str, ...]
    trial_ids: tuple[str, ...]
    alignment: Literal["frame", "time", "event"]

class ComparisonService:
    def build(self, request: ComparisonRequest) -> ComparisonReport: ...
    def export(self, report: ComparisonReport, path: Path,
               format: Literal["json", "csv", "html"]) -> None: ...
~~~

- [ ] 先写比较成员明确、对齐来源、缺失值处理、报告版本和稳定导出测试，确认失败。
- [ ] 实现版本化输入、对齐元数据、禁止缺失值静默变零和后台报告生成。
- [ ] 运行聚焦、完整 unittest、compileall，并重新读取导出文件。
- [ ] 提交：git commit -m "feat: add comparison reports and exports"。

## Task 16: 阶段 9 工程化、打包和最终验收

Files: scripts/build_windows.ps1、scripts/smoke_exe.ps1、app/diagnostics/bundle.py、tests/test_phase_acceptance.py、tests/test_domain_contract.py、tests/test_project_manager.py、tests/test_atomic_storage.py、tests/test_task_center.py、tests/test_frame_provider.py、tests/test_correction_rerun.py、tests/test_calibration_import.py、tests/test_synchronization.py、tests/test_association.py、tests/test_metrics.py、tests/test_events_cycles.py、tests/test_comparison_reporting.py、各阶段测试记录。

Interfaces:

~~~python
class DiagnosticBundle:
    def create(self, project: ProjectManager, destination: Path) -> Path: ...

def validate_installation() -> list[str]: ...
~~~

- [ ] 先写 v2 迁移、中文路径、阶段失效、4 路响应、取消、关闭、EXE 启动、原始数据保护和质量问题到二维保存闭环验收测试，确认失败。
- [ ] 实现诊断包脱敏、依赖能力检查、PyInstaller 构建、协作关闭和项目相对路径。
- [ ] 运行最终命令：

~~~powershell
python -m unittest discover -s tests -q
python -m compileall -q app tests
.\scripts\build_windows.ps1
.\scripts\smoke_exe.ps1
~~~

- [ ] 将 D:\test\test 复制到临时目录，只在副本执行全流程；比较前后指标并确认原目录没有文件和时间戳变化。
- [ ] 提交：git commit -m "release: complete motion analysis studio rebuild"，随后执行 archive_project.ps1。

## 任务执行规则

Task 1 到 Task 16 必须按顺序执行。每个阶段完成时暂停，更新需求追溯矩阵、测试记录、源码归档和已知限制。发现设计冲突时，先更新决策记录、数据契约、测试和本计划，再改代码。
