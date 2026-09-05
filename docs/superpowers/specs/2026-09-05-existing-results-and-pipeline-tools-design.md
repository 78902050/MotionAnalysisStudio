# 已有结果导入与外部分析工具工作台设计

日期：2026-09-05

## 1. 目标

Motion Analysis Studio 必须同时支持两类工作方式：创建新项目后运行分析，以及直接读取已经由 Caliscope/Pose2Sim 处理完成的试次目录。用户可以选择单个试次目录，也可以选择上级目录批量发现多个试次。查看已有结果不以源视频存在为前提。

本设计补齐三个可达缺口：

1. 从相机标定页启动 Caliscope GUI，并显示启动失败原因和日志。
2. 从应用内编辑、校验和备份 Pose2Sim `Config.toml`，按阶段运行 Pose2Sim，并实时查看输出。
3. 将现有 `pose`、`pose-sync`、`pose-associated`、`pose-3d`、`kinematics` 等目录原地登记为项目，使对应页面直接显示已有数据。

## 2. 已有数据项目模型

### 2.1 试次根目录

满足以下任一条件的目录可作为试次候选：

- 包含 `pose`、`pose-sync`、`pose-associated`、`pose-3d` 或 `kinematics` 中至少一个目录；
- 包含可解析的 `.trc`、`.mot`、`.sto` 结果，同时其父级或自身包含标定文件。

选择单个目录时只检查该目录。选择上级目录时递归发现候选，但如果某目录已经是候选，不再把它内部的结果子目录当成独立试次。候选以规范绝对路径去重，排序稳定。

### 2.2 原地登记

采用原地轻量登记，不复制已有大型结果。导入时允许创建：

- `manifest.json`；
- Motion Analysis Studio 所需但尚不存在的工作目录；
- `reports/import/artifacts.json`、质量报告、日志、修正历史和备份；
- 缺失的项目配置目录。

导入过程不得覆盖已有 pose、TRC、MOT、STO、标定或视频。后续用户主动保存二维修正或运行 Pose2Sim 时，按现有事务和备份规则修改项目工作结果。

### 2.3 自动发现内容

每个项目记录：

- 从 `pose/*_json`、`pose-sync/*_json` 和 `pose-associated/*_json` 发现的相机名；
- 每层文件数量和代表文件；
- `pose-3d` 中的 TRC、`kinematics` 中的 MOT/STO；
- 当前目录和最近父级中的 `camera_array.toml` 或 `camera_array_aniposelib.toml`；
- 当前目录、`config/Config.toml` 和父级中的 Pose2Sim Config 候选；
- 原始视频与带 `_pose`、`_sync` 等后缀的派生视频，二者分开标记。

相机拼写按磁盘事实保留，例如 `can02` 不自动改为 `cam02`。界面可以提示相机集合不一致，但不得猜测重命名。

### 2.4 阶段状态

已有产物只能证明对应阶段“有结果”，不能证明结果质量。导入器按以下规则初始化阶段：

- `pose` 有逐帧 JSON：`poseEstimation=completed`；
- `pose-sync` 有逐帧 JSON：`synchronization=completed`；
- `pose-associated` 有逐帧 JSON：`personAssociation=completed`；
- `pose-3d` 有 TRC：`triangulation=completed`；
- 文件名或目录明确含 filtered 结果：`filtering=completed`；
- `kinematics` 有 MOT/STO：`kinematics=completed`；
- 可解析标定被激活：`calibration=completed`。

推断记录写入 `manifest.imported_artifacts`，包括来源和时间。没有产物的阶段保持 `not_started`，不伪造成功。

## 3. 无视频数据模式

视频不是打开项目或读取结果的前置条件：

- 标定页读取标定 TOML；
- 同步页读取 mapping 或根据 pose/pose-sync 文件名显示候选；
- 二维质检读取逐帧 Pose2Sim JSON；
- 三维质检和运动学读取 TRC/结果文件；
- 对比报告读取已生成指标。

缺少视频时，二维画布使用标定图像尺寸；没有标定尺寸时，根据有限二维坐标推导最小画布边界。画布显示“仅姿态数据，无视频背景”，保留缩放、选择和拖动。只有需要真实像素内容的视觉核对被标记为不可用。

缺少人物关联时允许按原始人物索引浏览二维结果，但需要跨页面语义修正时显示阻断原因。缺少质量报告时，导入完成后在后台扫描现有结果并生成初始报告；扫描失败只影响质量页，不阻止其他结果页面。

## 4. Caliscope GUI 启动

相机标定页提供“启动 Caliscope”按钮和工作区显示。命令解析顺序为：

1. 设置页用户指定的 Caliscope 可执行文件；
2. 当前 Python 环境旁的 `caliscope.exe`；
3. PATH 中的 `caliscope`。

命令固定使用 `caliscope --workspace <workspace>`。工作区默认取导入清单中的 Caliscope 工作区或当前项目根，用户可另选目录。

启动由后台外部进程管理器执行，不阻塞 Qt 主线程。任务中心显示命令、进程状态、启动时间、退出码和日志路径。项目切换不强制关闭用户正在操作的 Caliscope GUI；应用关闭时仅回收由应用启动且仍处于初始化/无交互状态的失败进程，不强杀正常独立 GUI。

启动前诊断用户的 Caliscope `settings.toml`。当前环境的文件可用 GB18030 解析但不能用 UTF-8 解析。程序不得自动修改；界面提供“备份并转换为 UTF-8”，只有用户点击后才把原文件备份为带时间戳副本，再原子写入 UTF-8。TOML 解析失败时不允许转换。

## 5. Pose2Sim Config 编辑器

流程页包含 Config 编辑区：

- 打开项目 `config/Config.toml` 或导入一个现有 TOML；
- 使用纯文本编辑保留注释、字段顺序和用户格式；
- 保存前用 Python 3.12 `tomllib` 验证语法；
- 首次编辑前和每次保存前在 `config/backups` 保存版本化副本；
- 使用原子替换写入工作 Config；
- 支持重新载入和查看验证错误的行列；
- 空文件、缺失文件和语法错误时禁用 Pose2Sim 运行，不影响已有结果查看。

Config 保存不尝试重写未知字段。保存后根据用户选择的起始阶段使该阶段及下游过期；如果尚未选择，保守标记全部 Pose2Sim 阶段为 stale，并显示原因。

## 6. Pose2Sim 阶段工作台

一般流程允许以下阶段：

1. `calibration`
2. `synchronization`
3. `poseEstimation`
4. `personAssociation`
5. `triangulation`
6. `filtering`
7. `markerAugmentation`
8. `kinematics`

用户可以运行单个阶段、运行选中阶段，或从选中阶段运行到最后。阶段顺序固定来自统一依赖图。二维修正后的选择性重跑继续使用独立白名单，从 `personAssociation` 开始且不包含 `poseEstimation`。

每次运行创建包含 project ID、generation、Config 路径、阶段、开始时间和日志路径的任务。标准输出和错误输出合并写入 UTF-8 日志；页面每 250 ms 增量读取新增内容，不反复读取整个大日志。实时区域最多保留最近 5000 行，磁盘日志保留完整内容。

阶段开始时状态设为 running；成功设为 completed；失败记录 failed、失败阶段和退出码；取消设为 cancelled。一个项目同一时间只允许一个一般 Pose2Sim 流程。项目切换后旧任务不得刷新新项目页面。取消必须终止整个子进程树并等待清理。

阶段成功后重新扫描产物索引，并刷新标定、同步、质量、关联、三维运动学和任务页面。

## 7. 界面布局

项目页新增：

- “读取已处理文件夹”；
- “扫描上级文件夹”；
- 候选表：名称、路径、相机数、二维/三维/运动学/视频/Config 状态；
- 单选导入和批量登记。

新增导航页“Pose2Sim 流程”，使用可调分栏：左侧阶段与运行控制，中间 Config 编辑器，右侧实时日志和阶段状态。所有控制区使用滚动容器，1120×720 不重叠，620×480 可滚动访问。

相机标定页增加 Caliscope 工作区、启动按钮、配置诊断和显式编码转换按钮。任务页继续提供全局任务列表和取消入口。

## 8. 错误和权限语义

- 缺视频：显示数据模式，不阻止项目打开和结果读取。
- 缺 Config：禁用运行，提供导入/新建入口。
- 缺标定：只禁用依赖标定的诊断和阶段。
- 已有 manifest：按普通项目打开，不重复导入。
- 只读目录：允许只读预览候选；登记前明确报告无法创建 manifest，不能半写入。
- 外部进程无法启动：显示实际命令、系统错误和日志路径。
- Caliscope 配置编码异常：显示检测结果；转换必须显式触发并保留备份。
- Pose2Sim 阶段失败：保留已有结果，失败阶段及下游不得标记 completed。

## 9. 验收

- 单个已处理目录可原地登记并打开。
- 选择 `D:\test\data` 能稳定发现各动作试次，不把 pose 子目录误识别为试次。
- 不含视频的试次能显示标定、二维姿态、TRC 和运动学摘要；二维画布显示姿态数据模式。
- 缺失或空 Config 不影响读取，且运行按钮被禁用并说明原因。
- Caliscope 启动命令包含 `--workspace`，失败不阻塞 GUI。
- GB18030 Caliscope 设置只有显式操作才转换，原文件有备份。
- Config 语法错误不落盘；有效保存原子替换并创建备份。
- Pose2Sim 每个阶段可单独运行，实时日志增量更新，取消无残留子进程。
- 选择性重跑仍不包含 `poseEstimation`。
- 全量 unittest、compileall、真实数据副本验收、DLL 审计和 EXE smoke 全部通过。

## 10. 已知边界

导入器不推测人物姓名、相机拼写修复或缺失同步偏移。已有 Pose2Sim 结果中未保存的 Config 参数无法从输出完全逆向恢复；用户必须导入有效 Config 后才能重新运行。外部 Caliscope GUI 的交互由 Caliscope 自身管理，Motion Analysis Studio 只负责启动、诊断和日志化启动失败。
