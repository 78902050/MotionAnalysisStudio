# Motion Analysis Studio 测试、验收与性能计划

## 1. 测试目标

测试不只验证函数返回值，还要验证数据语义、GUI 响应、外部进程隔离、异常恢复和真实项目可用性。测试结果必须能回答三个问题：结果是否正确、操作是否安全、界面是否流畅。

## 2. 测试层级

### 2.1 领域单元测试

覆盖地址校验、阶段图、状态迁移、帧映射、人物地址、关节点名称映射、指标计算和事件规则。领域测试不能依赖 PySide6、视频设备或真实项目。

### 2.2 文件和事务单元测试

覆盖 UTF-8、中文路径、原子替换、首次备份、重复保存、损坏 JSON、截断 JSONL、不可写目录、事务中断和恢复。所有失败注入都使用临时目录。

### 2.3 应用服务集成测试

覆盖项目创建/打开/迁移、质量报告生成、修正保存、关联物化、阶段失效、before/after 报告、取消和项目 generation 隔离。

### 2.4 GUI 测试

使用 QT_QPA_PLATFORM=offscreen。验证页面注册、QSplitter、QScrollArea、控件可访问性、信号更新、未保存保护、键盘快捷键、问题到修正目标的精确跳转和后台任务结果丢弃。

### 2.5 性能和流畅性测试

Qt heartbeat 每 50 ms 记录一次事件循环。四路视频连续预取 2 秒时，任意一次 GUI 事件循环停顿不得超过 250 ms；导航、缩放和选择操作必须仍能处理。测试同时记录解码线程 ID 和 GUI 线程 ID，防止“读成功但主线程被阻塞”的假通过。

### 2.6 真实项目副本测试

把 D:\test\test 复制到自动生成的临时目录，只对副本执行。记录项目相机数、同步映射、质量问题、3D 指标、导入文件列表和运行日志；测试结束后比较原目录文件名、大小和修改时间，原目录必须无变化。

## 3. 统一命令

在项目根目录运行：

~~~powershell
python -m unittest discover -s tests -q
python -m compileall -q app tests
~~~

GUI 测试前设置 QT_QPA_PLATFORM=offscreen。测试脚本不自动安装 pytest 或修改用户环境。

## 4. 需求验收矩阵

| 验收编号 | 验收内容 | 主要测试 |
|---|---|---|
| A-01 | 新建项目生成 v3 清单和完整目录 | test_project_manager |
| A-02 | v2 迁移幂等且保留旧字段 | test_project_manager |
| A-03 | 中文项目路径和文件名可读写 | test_project_manager、test_atomic_storage |
| A-04 | 负帧号和未知时间轴被拒绝 | test_domain_contract |
| A-05 | 损坏 JSON/JSONL 有明确错误且不丢有效前缀 | test_atomic_storage |
| A-06 | 首次保存备份且后续保存不覆盖 | test_correction_history |
| A-07 | 恢复同时还原坐标和置信度并写恢复历史 | test_correction_history |
| A-08 | undo/redo 恢复完整三元组 | test_correction_session |
| A-09 | 未保存导航可保存、放弃或取消 | test_correction_session、test_gui_shell |
| A-10 | 质量目标包含相机、时间轴、帧、人物和关节点 | test_quality_audit |
| A-11 | 关节点按名称映射而非裸索引 | test_quality_audit |
| A-12 | 同步偏移来自映射数据 | test_synchronization |
| A-13 | 人物数组顺序变化不破坏语义选择 | test_association |
| A-14 | 多候选、缺层、坏 payload 禁止自动应用 | test_association |
| A-15 | 2D 修正不运行 poseEstimation | test_correction_rerun |
| A-16 | 4 路预取期间 heartbeat 无超过 250 ms 停顿 | test_frame_provider |
| A-17 | 新标定内容导入后当前数据发生变化 | test_calibration_import |
| A-18 | 任务取消不会留下线程或子进程 | test_task_center、test_phase_acceptance |
| A-19 | 项目切换后旧结果不能覆盖当前项目 | test_task_center、test_phase_acceptance |
| A-20 | 3D 指标不跨缺口错误插值 | test_metrics |
| A-21 | 事件、周期和报告可重现 | test_events_cycles、test_comparison_reporting |
| A-22 | EXE 启动并完成最小闭环 | test_phase_acceptance、smoke_exe.ps1 |
| A-23 | 原始项目没有任何写入 | test_phase_acceptance |
| A-24 | 诊断包不包含不必要的原始视频和敏感信息 | test_phase_acceptance |

## 5. 阶段门禁

### 阶段 1

领域、文件、质量和 GUI 基础测试全部通过；质量报告能从问题定位到语义目标；报告在缺少单层输入时仍给出明确状态；编译通过。

### 阶段 2

修正模型、历史、恢复、后台帧服务、选择性重跑和 GUI 测试全部通过；4 路 heartbeat 通过；仅保存不启动 PipelineRunner；真实项目副本闭环通过。

### 阶段 3

相同标定文件导入幂等，内容改变会改变导入结果；损坏、缺失和不可写情况有明确提示；原始标定源不变。

### 阶段 4

映射表和时间戳测试通过；业务代码没有按相机名写死偏移；同步修改的阶段失效范围和恢复记录正确。

### 阶段 5

多人语义、轨迹段、候选、人工确认、物化和恢复测试通过；无映射或多候选时应用按钮禁用。

### 阶段 6～8

指标单位、缺口、事件、周期、比较对象、对齐方法和导出内容均有测试；报告包含参数和输入版本。

### 阶段 9

完整 unittest、compileall、EXE smoke、真实项目副本验收和关闭清理全部通过；形成发布归档和测试记录。

## 6. 测试记录格式

每个阶段在 docs/superpowers/test-records/ 下保存一个 Markdown 文件，至少包含：日期、代码提交、Python/PySide6/Pose2Sim/Caliscope 能力版本、命令、测试数量、通过/失败、真实项目副本路径、日志路径、残留进程检查、已知限制和验收结论。失败测试必须保留失败原因和修复后的重新运行结果。

## 7. 可行性判定

若外部 Pose2Sim 或 Caliscope 版本缺少某项能力，程序不得伪造成功。适配器应显示 unavailable、记录版本和替代路径；只有不影响数据正确性的功能可以降级。任何涉及语义定位、原始数据写入、身份关联和指标可信度的能力缺失，都必须阻塞对应操作。
