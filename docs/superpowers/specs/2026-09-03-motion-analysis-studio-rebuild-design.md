# Motion Analysis Studio 重建总体设计

## 1. 文档目的

本文档定义 Motion Analysis Studio 的完整重建设计。它把历史对话中已经确认的需求、阶段 1～5 中暴露的问题、阶段 2～9 的目标，以及本次工作区丢失后的工程改进统一为一套可以独立执行的设计。

本次重建不假设旧源码仍然存在。实现者只需要本目录文档、标准项目输入格式和测试数据，就应当可以从空项目建立可运行程序。

## 2. 产品目标

建立一个 Windows 桌面应用，用于管理多相机运动分析项目，调用用户已经安装的 Caliscope 和 Pose2Sim，完成：

- 视频和标定资料管理；
- 相机标定质量诊断与实验空间校验；
- 多相机同步分析与人工偏移校准；
- 2D 姿态质量检查、人工修正、审计、撤销、恢复和选择性重跑；
- 多人身份关联诊断与人工确认；
- 3D 轨迹、重投影质量、运动学指标、动作事件和周期分析；
- 多人物、多试次对比、报告导出和跨电脑打包。

## 3. 明确不做的事情

- 不修改原始 MP4，不转码原始视频。
- 不修改已安装的 Pose2Sim、Caliscope 或其 site-packages 文件。
- 不自动“认定”某个关节点错误，不自动移动人工点，不自动合并人物身份。
- 不把相机偏移、人物编号、关节点裸索引或安装路径写死在业务逻辑中。
- 不在 GUI 主线程中读取视频、扫描大量 JSON、计算全量报告或等待外部进程。
- 不把“文件读到了”当作“界面流畅”；主线程响应有单独的性能门禁。

## 4. 核心原则

### 4.1 语义优先

所有跨阶段定位使用显式对象：

```python
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
class KeypointAddress:
    model_name: str
    keypoint_name: str
    source_index: int | None = None
```

数组下标只能作为输入文件内部的临时信息，不能作为跨文件或跨阶段的身份依据。

### 4.2 时间轴明确

原始视频帧、同步后帧、2D 姿态帧和 3D 结果帧属于不同时间轴。任何跳转请求都必须携带时间轴；同步帧到原始帧的关系由 `FrameMapping` 读取或生成，不能凭经验使用 `-1`、`-2` 或其他固定常量。

### 4.3 人工确认优先

自动分析产生 `Candidate`，人工确认后才能写入 `CorrectionOperation`、`AssociationOverride` 或阶段配置。多个候选、映射缺失、输入不完整和语义名称无法匹配时，界面必须显示原因并禁用应用按钮。

### 4.4 数据可恢复

工作 JSON 通过临时文件、flush、原子替换更新；首次修改前保留不可覆盖的备份；每次修改、恢复、重跑和状态变化都有审计记录。启动时发现未完成事务必须恢复到旧版本或明确提示用户。

## 5. 系统分层

```text
GUI Shell
  ├─ Project Workspace
  ├─ Media / Calibration / Synchronization Pages
  ├─ Quality and Correction Pages
  ├─ Analysis and Comparison Pages
  └─ Task Center / Settings
Application Services
  ├─ ProjectService
  ├─ StageGraphService
  ├─ QualityAuditService
  ├─ CorrectionService
  ├─ AssociationService
  ├─ AnalysisService
  └─ ReportService
Infrastructure Adapters
  ├─ Pose2SimAdapter
  ├─ CaliscopeAdapter
  ├─ VideoFrameProvider
  ├─ AtomicStore / JSONL Store
  └─ QThread Task Runner
Project Files
  ├─ manifest.json
  ├─ Config.toml and user-owned inputs
  ├─ pose / pose-sync / pose-associated / pose-3d
  ├─ calibration / synchronization / kinematics
  └─ reports / corrections / logs
```

依赖方向只能从 GUI 到应用服务、从应用服务到领域模型和适配器；领域模型不能导入 PySide6，Pose2Sim 适配器不能反向调用 GUI。

## 6. 阶段图与失效规则

```text
project inputs
    ↓
calibration ──→ synchronization ──→ poseEstimation ──→ personAssociation
                         ↓                  ↓                 ↓
                    sync report        pose-2d report     association report
                                                               ↓
                                                     triangulation
                                                               ↓
                                                      filtering
                                                               ↓
                                                   markerAugmentation
                                                               ↓
                                                         kinematics
                                                               ↓
                                                events / cycles / comparisons
```

实际执行顺序由 `StageGraph` 定义，图中只表达依赖。阶段状态有 `not_started`、`running`、`completed`、`pending`、`stale`、`failed`、`cancelled`。

失效规则固定如下：

- 标定修改：标定报告、同步及所有后续结果失效；原始视频和导入清单不失效。
- 同步修改：同步及所有后续结果失效；`poseEstimation` 是否失效由配置依赖决定，默认保留已完成的 2D 结果。
- 2D 修正：保留 `poseEstimation=completed`，仅使同步后的关联、三角化及其下游结果 stale/pending。
- 人物关联修改：不重新运行 2D 姿态估计和同步，只重跑三角化及其下游。
- 过滤、标记增强或运动学配置修改：只失效对应阶段及其下游。

所有重跑列表由依赖图计算，并通过允许列表再次校验，禁止通过字符串拼接绕过依赖图。

## 7. 主要模块边界

| 模块 | 责任 | 不负责 |
|---|---|---|
| `app/domain` | 数据类、ID、枚举、阶段图、校验 | 文件读写、GUI |
| `app/project` | 项目创建、打开、迁移、清单和路径 | 姿态算法 |
| `app/io` | 原子 JSON、JSONL、日志和备份 | 业务决策 |
| `app/media` | 后台视频帧请求、缓存、项目隔离 | 姿态解析 |
| `app/adapters/pose2sim` | 配置转换、子进程、日志和阶段结果适配 | GUI 状态 |
| `app/adapters/caliscope` | 标定数据读取和导出适配 | 修改第三方包 |
| `app/quality` | 指标、问题、报告和质量筛选 | 人工修正写入 |
| `app/correction` | 修正会话、历史、撤销、恢复和重跑请求 | 自动判断错误 |
| `app/association` | 多人关联诊断、候选和人工确认 | 强制合并身份 |
| `app/analysis` | 3D 指标、事件、周期、对比 | 原始数据修改 |
| `app/gui` | 页面、布局、信号、用户交互 | 全量扫描和子进程等待 |

## 8. 后台任务模型

所有后台工作统一实现 `TaskController`：

```python
class TaskController(Protocol):
    progress: Signal
    message: Signal
    succeeded: Signal
    failed: Signal
    cancelled: Signal

    def start(self, request: TaskRequest) -> str: ...
    def cancel(self, task_id: str) -> None: ...
    def wait_for_shutdown(self, timeout_ms: int) -> bool: ...
```

任务带 `project_id`、`generation` 和 `task_id`。结果回传 GUI 前必须检查项目和 generation；旧项目或旧请求的结果一律丢弃。窗口关闭时先请求取消，再等待线程和子进程退出，超时必须显示残留任务信息。

视频服务使用每台相机一个后台解码器和有界 LRU 缓存。GUI 线程只能提交 `FrameAddress`，不能调用 `cv2.VideoCapture.read()`。

## 9. 配置与依赖策略

- 运行时依赖由 `pyproject.toml` 声明，但不修改用户已有 Pose2Sim/Caliscope 安装。
- 外部程序调用使用配置路径、环境探测和可见错误信息；禁止把开发机路径写入源码。
- Pose2Sim 输出格式通过适配器读取；适配器对版本差异做能力检测并记录版本。
- 计算结果保存为本项目的报告和审计文件，第三方结果文件只在用户明确选择工作 JSON 时更新。

## 10. 错误处理

错误必须包含：阶段、项目 ID、相机名（如适用）、时间轴和帧号（如适用）、人物/关节点语义（如适用）、原因、日志路径和恢复建议。错误分为：

- `input_invalid`：输入结构或字段不合法；
- `mapping_missing`：时间轴、人物或关节点映射不存在；
- `candidate_ambiguous`：存在多个候选但没有人工确认；
- `io_failed`：文件不可读、不可写或原子替换失败；
- `dependency_unavailable`：外部程序或能力不可用；
- `task_cancelled`：用户取消；
- `stage_failed`：外部阶段失败。

部分相机失败不应让其他相机视图消失；部分帧损坏应在质量报告中逐项标记，不能静默跳过。

## 11. 重建完成定义

重建不是“窗口能打开”就算完成。必须同时满足：

- 阶段 1～9 的文档、实现和测试可追溯；
- 旧项目 v2 可迁移到 v3，中文路径可用；
- 二维修正、多人关联和三维质检可从同一语义目标互相跳转；
- 4 路视频预取期间 GUI 事件循环持续响应；
- 所有写入可审计、撤销、恢复；
- 选择性重跑不执行禁止阶段；
- 真实项目只在副本中完成验收；
- EXE 能完成“创建/打开项目→质量问题→二维定位→保存”最小闭环；
- 每个阶段都有独立提交、压缩归档和测试记录。

