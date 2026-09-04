# Motion Analysis Studio 数据契约与项目格式

## 1. 版本与编码

- 所有 JSON、JSONL、TOML、Markdown 使用 UTF-8。
- 项目清单当前版本为 `schema_version: 3`。
- 旧项目 `schema_version: 2` 只做幂等迁移，不删除旧字段；迁移完成后保留 `manual_pose_edits`。
- JSON 对象键使用稳定的 ASCII 名称；用户可见名称可以是中文。
- 帧号从 0 开始还是从 1 开始由 `frame_base` 声明，内部 `FrameAddress.frame` 统一使用非负整数。

## 2. 基础定位对象

```python
TimelineName = Literal["raw", "synchronized", "pose2d", "pose3d"]

@dataclass(frozen=True)
class FrameAddress:
    camera: str
    timeline: TimelineName
    frame: int

    def __post_init__(self) -> None:
        if not self.camera.strip():
            raise ValueError("camera must not be empty")
        if self.timeline not in {"raw", "synchronized", "pose2d", "pose3d"}:
            raise ValueError("unknown timeline")
        if self.frame < 0:
            raise ValueError("frame must be non-negative")

@dataclass(frozen=True)
class FrameMapping:
    camera: str
    source_timeline: TimelineName
    target_timeline: TimelineName
    source_frame: int
    target_frame: int
    method: Literal["identity", "offset", "table", "timestamp"]
    confidence: float | None
    source: str

@dataclass(frozen=True)
class PersonAddress:
    project_person_id: str
    track_segment_id: str | None
    raw_person_index: int | None

@dataclass(frozen=True)
class KeypointAddress:
    model_name: str
    keypoint_name: str
    source_index: int | None
```

映射的 `method` 可以是 `offset`，但 offset 必须来自项目数据或 Pose2Sim 输出，不能来自相机名分支和硬编码常量。`source` 必须能指向配置、报告或外部生成文件。

## 3. 项目清单 v3

最小清单结构如下：

```json
{
  "schema_version": 3,
  "project_id": "project-20260903-0001",
  "name": "试验一",
  "created_at": "2026-09-03T09:00:00+08:00",
  "updated_at": "2026-09-03T09:00:00+08:00",
  "frame_base": 0,
  "people": [
    {"project_person_id": "person-01", "display_name": "运动员 1"}
  ],
  "cameras": [
    {"camera_id": "cam01", "display_name": "左前", "video": "videos/cam01.mp4"}
  ],
  "stages": {
    "calibration": {"status": "not_started", "generation": 0},
    "synchronization": {"status": "not_started", "generation": 0},
    "poseEstimation": {"status": "not_started", "generation": 0},
    "personAssociation": {"status": "not_started", "generation": 0},
    "triangulation": {"status": "not_started", "generation": 0},
    "filtering": {"status": "not_started", "generation": 0},
    "markerAugmentation": {"status": "not_started", "generation": 0},
    "kinematics": {"status": "not_started", "generation": 0},
    "events": {"status": "not_started", "generation": 0},
    "comparison": {"status": "not_started", "generation": 0}
  },
  "paths": {
    "config": "config/Config.toml",
    "quality_report": "reports/quality/current.json",
    "correction_root": "corrections",
    "logs": "logs"
  },
  "manual_pose_edits": [],
  "migration": {"source_schema_version": null, "migrated_at": null}
}
```

新建项目必须一次性创建 `reports/`、`corrections/history.jsonl`、`corrections/sessions/`、`corrections/backups/pose/`、`logs/` 等目录。重复打开或迁移不能重复追加清单字段或覆盖用户数据。

## 4. 阶段状态

```python
StageStatus = Literal[
    "not_started", "running", "completed", "pending", "stale", "failed", "cancelled"
]

@dataclass
class StageRecord:
    stage: str
    status: StageStatus
    generation: int
    input_fingerprint: str | None
    output_fingerprint: str | None
    started_at: str | None
    completed_at: str | None
    error_code: str | None
    log_path: str | None
    invalidated_by: list[str]
```

阶段状态更新必须是原子操作；一次事务只能把同一阶段从一个已知状态迁移到允许的下一个状态。

## 5. 质量问题

```python
@dataclass(frozen=True)
class QualityIssue:
    issue_id: str
    kind: Literal[
        "missing", "low_confidence", "reprojection", "camera_insufficient",
        "interpolated", "identity_switch", "mapping_missing", "input_invalid"
    ]
    severity: Literal["info", "warning", "error", "blocking"]
    target: FrameAddress | None
    person: PersonAddress | None
    keypoint: KeypointAddress | None
    message: str
    evidence: dict[str, object]
    disposition: Literal["pending", "handled", "deferred", "ignored"]
    modification_count: int
```

质量报告必须同时记录实际人数、2D 检测人数、关联后同时人数、轨迹段数量和指标统计，不能把轨迹段数量直接显示为人物数量。

## 6. 二维修正历史

```python
@dataclass(frozen=True)
class CorrectionTarget:
    address: FrameAddress
    raw_person_index: int
    keypoint_name: str
    keypoint_index: int

@dataclass(frozen=True)
class CorrectionOperation:
    operation_id: str
    session_id: str
    target: CorrectionTarget
    before: tuple[float, float, float]
    after: tuple[float, float, float]
    note: str
    created_at: str
    source: Literal["manual", "restore", "migration"]
```

`before` 和 `after` 顺序固定为 `(x, y, confidence)`。恢复是新操作，不删除原历史；首次备份只保存第一次修改前的完整 JSON。

## 7. 多人关联数据

```python
@dataclass(frozen=True)
class SkeletonFingerprint:
    model_name: str
    keypoint_names: tuple[str, ...]
    value_hash: str

@dataclass(frozen=True)
class AssociationCandidate:
    candidate_id: str
    camera: str
    frame: int
    raw_person_index: int
    fingerprint: SkeletonFingerprint
    score: float
    method: Literal["exact", "spatial", "temporal"]
    explanation: str
    exact: bool

@dataclass(frozen=True)
class AssociationOverride:
    override_id: str
    project_person_id: str
    camera: str
    synchronized_frame: int
    raw_person_index: int
    fingerprint: SkeletonFingerprint
    confirmed_by: str
    confirmed_at: str
```

缺少同步到原始帧映射、候选不唯一、骨架指纹无法匹配或原始/关联层缺失时，不能生成可应用的 override。

## 8. 文件布局

```text
project/
├─ manifest.json
├─ config/Config.toml
├─ videos/                         # 用户视频引用或副本，不由程序转码
├─ calibration/
│  ├─ source/                       # 标定输入
│  ├─ normalized/                  # 本项目只读规范化副本
│  └─ reports/
├─ pose/
├─ pose-sync/
├─ pose-associated/
├─ pose-3d/
├─ synchronization/
├─ kinematics/
├─ reports/
│  ├─ quality/current.json
│  ├─ quality/history/
│  ├─ metrics/
│  └─ comparisons/
├─ corrections/
│  ├─ history.jsonl
│  ├─ sessions/
│  ├─ backups/pose/
│  └─ backups/association/
└─ logs/
```

程序只能在项目根目录内写入上述工作区。原始视频、原始标定文件和用户明确标记为只读的外部文件永远不写入。

## 9. 原子写入与事务

一次工作 JSON 保存事务必须按以下顺序执行：

1. 生成 `transaction_id`，写入事务开始记录。
2. 若首次修改，使用独占创建复制备份；已存在备份不得覆盖。
3. 将新 JSON 写入同目录临时文件，调用 `flush()` 和 `os.fsync()`。
4. 使用同文件系统内的原子替换更新工作文件。
5. 追加完整 JSONL 审计记录并 flush。
6. 更新 manifest 的阶段失效状态。
7. 写入事务完成标记。

任何步骤失败都必须保留原工作 JSON 可读；如果替换后历史或清单更新失败，启动恢复器应根据事务记录回滚或提示，而不是静默继续。

## 10. v2 到 v3 迁移

- 缺少 `schema_version` 时按 v2 兼容读取并记录警告。
- 为 v2 增加缺失目录、`project_id`、阶段状态和 `migration` 字段。
- 原有 `manual_pose_edits` 原样保留；不能把旧索引擅自转换成语义身份。
- 迁移只更新清单和目录，不重新运行 Pose2Sim，不使已有 completed 结果自动失效。
- 重复迁移的输出与第一次一致，迁移过程可在中途失败后重试。

