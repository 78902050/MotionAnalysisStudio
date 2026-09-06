# 二维视频骨骼修正恢复设计

日期：2026-09-06

## 目标

恢复“视频画面上显示并修改二维骨骼”的工作方式。项目有原视频时显示原视频；只有 Pose2Sim 生成的 `*_pose.mp4` 时显示二维标记视频。当前工作 JSON 中的骨骼始终作为独立、可编辑的实时图层绘制，保存仍只修改 Pose JSON，不修改或转码任何视频。

## 已确认现状与根因

- `CorrectionCanvas` 能接收后台解码帧并在图像坐标空间绘制点，但只画关节点，不画骨骼连线。
- 项目打开时先设置 pose 清单并触发首帧请求，随后才调用 `MultiViewFrameProvider.set_project()`；首帧请求可能发给空的视频提供器。
- `ExistingResultImporter` 只把原视频写入相机的 `video_path`。Pose2Sim 二维标记视频只记录在 `imported_artifacts.derived_videos`，修正页不会使用。
- `MediaPage` 只能读取视频元数据，不能让用户重新绑定相机视频。
- `D:\test\data` 当前有 56 个 `*_pose.mp4`，没有原始 MP4；Pose2Sim 安装示例有 16 个原始多相机 MP4，可覆盖两种视频模式的测试。

## 视频来源模型

新增应用内部视频绑定模型：

```python
VideoKind = Literal["original", "pose2sim_overlay"]

@dataclass(frozen=True)
class CameraVideoSource:
    camera: str
    path: Path
    kind: VideoKind
```

项目清单保持向后兼容：

- `cameras[].video_path` 继续表示原视频。
- `cameras[].pose_video_path` 表示 Pose2Sim 二维标记视频。
- `cameras[].preferred_video_kind` 只在用户明确改变首选来源时写入。
- 已有 `video_path` 不改名、不移动，旧项目无需迁移数据文件。

选择顺序固定为：

1. 用户设置的 `preferred_video_kind` 且对应文件可读。
2. 可读的原视频 `video_path`。
3. 可读的 Pose2Sim 二维标记视频 `pose_video_path`。
4. 无视频坐标画布。

程序不得把 Pose2Sim 二维标记视频显示为“原视频”。画布标题和媒体页必须显示当前来源类型。

## 发现与绑定

`ExistingResultDiscovery` 继续区分原视频和衍生视频。`ExistingResultImporter` 按相机名语义匹配：

- `videos/cam01.mp4` 等原视频写入 `video_path`。
- `pose/cam01_pose.mp4` 等 Pose2Sim 标记视频写入 `pose_video_path`。
- 匹配必须基于规范化相机名，不依赖目录枚举顺序。
- 同一相机有多个候选且无法唯一判断时不自动绑定，媒体页显示冲突原因。

媒体页增加“绑定原视频”“绑定 Pose2Sim 标记视频”“清除绑定”“设为首选”操作。文件选择只保存绝对引用或项目内相对引用，不复制、不删除、不转码。保存项目清单后重新配置帧提供器，并请求当前修正帧。

## 帧地址与解码顺序

`MultiViewFrameProvider` 继续只接收 `FrameAddress(timeline="raw")`。原视频和 Pose2Sim 标记视频都按 Pose JSON 的原始帧号读取；从同步质量问题进入时，必须先经过现有同步映射得到原始帧，不允许把同步帧直接作为视频帧。

项目打开顺序调整为：

1. 收集并解析相机视频来源。
2. 调用 `frame_provider.set_project(project_id, sources)`，完成旧线程取消和新线程启动。
3. 设置修正页相机与 pose 帧清单。
4. 打开首个可读 Pose JSON，建立修正会话。
5. 请求当前帧和前后预取帧。

帧提供器的缓存键加入来源路径或来源版本，切换原视频与标记视频后不得返回旧来源缓存。旧项目、旧 generation 或过期帧的结果继续丢弃。

## 骨骼图层

新增只读骨架拓扑适配器，将 Pose2Sim 骨架树转换为名称边：

```python
class SkeletonTopologyRepository:
    def edges_for(self, model_name: str, keypoint_names: Iterable[str]) -> tuple[tuple[str, str], ...]: ...
```

- HALPE_26 等已知模型使用 Pose2Sim 的名称和父子关系。
- 连线按名称匹配，不使用未验证的裸索引。
- 未知模型只画点，并显示“未知骨架模型，未绘制连线”，不得猜测连接关系。
- 缺少任一端点、坐标非有限或置信度不大于零时不画该边。

实时图层规则：

- 当前工作 JSON 的骨骼连线使用青绿色，关节点按置信度调整透明度。
- 当前人物比其他人物更醒目；当前关节点使用黄色十字和外圈。
- Pose2Sim 二维标记视频已有烘焙标记时，实时图层使用不同颜色和略大的点，标题显示“Pose2Sim 标记视频 + 当前工作 JSON”。
- 拖动点后立即重绘关节点及相邻骨骼；撤销、重做、恢复也必须立即重绘。
- 每个可见相机只绘制与该相机 Pose 文件对应的骨骼，不把一个相机的二维坐标复制到另一相机。

## 多视图与交互

保留 1、2、4 路可调分栏。每个相机卡片独立显示：来源类型、相机名、原始帧号和错误。没有对应视频时仍显示可编辑坐标画布；没有对应 Pose 文件时只显示视频并说明“当前帧无 Pose JSON”。

缩放、拖点和选择人物/关节点保持现有行为。视频帧读取、跳帧和预取不得在 GUI 主线程调用 `cv2.VideoCapture.read()`。

## 错误与准确性

- 视频不存在、无法解码、帧数不足和相机映射冲突必须按相机显示，不影响其他视图。
- 视频帧数与 Pose 最大帧号不一致时显示诊断，不自动平移或缩放帧号。
- Pose2Sim 标记视频是合法显示来源，但不能用于恢复被烘焙进视频的旧坐标；当前可编辑 JSON 图层才是保存事实来源。
- 任何自动匹配只建立视频引用，不修改 Pose 数据。

## 测试与验收

- 单元测试覆盖相机名匹配、来源优先级、旧清单兼容和冲突拒绝。
- 画布测试覆盖背景图、HALPE_26 连线、未知模型无连线、拖动后邻边更新和来源标签。
- 集成测试证明帧提供器先配置再发出首帧请求，切换来源不会命中旧缓存。
- 使用 Pose2Sim `Demo_SinglePerson` 和 `Demo_MultiPerson` 原视频验证原视频模式。
- 使用 `D:\test\data` 的 `*_pose.mp4` 与对应 JSON 验证标记视频模式。
- 4 路连续播放/跳帧 2 秒内 Qt 事件循环不得出现超过 250 ms 的停顿。
- 完整 `unittest`、`compileall`、真实数据验收、EXE 重建和 Gui/Workflow/Capabilities smoke 均须通过。

## 非目标与已知限制

- 本任务不重新生成 Pose2Sim 标记视频。
- 本任务不尝试从标记视频反向提取或消除烘焙骨骼。
- 本任务不自动判断哪个关节点错误，自动结果仍需人工确认。
- 原视频不在磁盘时，程序无法提供没有烘焙标记的画面，只能使用 Pose2Sim 标记视频或纯坐标背景。

