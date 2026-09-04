# Motion Analysis Studio 重建文档索引

> 文档状态：已确认方案，尚未开始重新编写程序。
>
> 本目录是重建项目的设计与验收基线。实现代码必须以这些文档为依据；历史对话和旧工作区只作为需求证据，不作为源码依赖。

## 1. 读取顺序

1. [总体设计思路](specs/2026-09-03-motion-analysis-studio-rebuild-design.md)
2. [数据契约与项目格式](specs/2026-09-03-motion-analysis-studio-data-contract.md)
3. [界面与交互设计](specs/2026-09-03-motion-analysis-studio-ui-design.md)
4. [阶段 1～9 总路线图](plans/2026-09-03-motion-analysis-studio-roadmap.md)
5. [完整编程实施计划](plans/2026-09-03-motion-analysis-studio-implementation-plan.md)
6. [测试、验收与性能计划](plans/2026-09-03-motion-analysis-studio-test-acceptance-plan.md)
7. [迁移、备份与恢复计划](plans/2026-09-03-motion-analysis-studio-migration-recovery-plan.md)
8. [需求追溯矩阵](plans/2026-09-03-motion-analysis-studio-traceability.md)
9. [编程规范与阶段执行流程](plans/2026-09-03-motion-analysis-studio-development-process.md)
10. [决策记录](decisions/2026-09-03-motion-analysis-studio-decision-log.md)
11. [文档基线测试记录](test-records/2026-09-03-planning-baseline.md)

## 2. 统一事实来源

- 产品范围、阶段边界和不可违反的约束以总体设计为准。
- 字段名、枚举值、文件位置和迁移规则以数据契约为准。
- 界面结构、最小尺寸、可调区域和交互行为以界面设计为准。
- 实现顺序、任务粒度、测试命令和提交节点以编程实施计划为准。
- 是否可以宣布阶段完成，以测试与验收计划中的门禁为准。

## 3. 重建策略

本项目采用干净重建：从新的空项目开始实现，不重放旧工作区补丁，不依赖已经消失的源码，不修改原始视频，也不修改已安装的 Pose2Sim 或 Caliscope。历史任务中发现的功能、缺陷和约束已经整理为需求、数据契约和测试门禁。

每个阶段必须先写失败测试，再实现最小功能，然后运行聚焦测试、回归测试和必要的真实项目副本验收。每个阶段完成后立即建立 Git 提交、源码压缩归档、测试记录和已知限制记录。

## 4. 当前决策

- Python 3.12、PySide6、OpenCV、NumPy、JSON/JSONL 是首选技术栈。
- 测试默认使用标准库 `unittest`，不因环境缺少 `pytest` 自动安装依赖。
- GUI 只负责交互和展示；视频解码、文件扫描、Pose2Sim 子进程和报告生成全部放入后台任务。
- 相机、帧、人物和关节点必须使用语义地址或映射对象定位，不使用固定人物编号、固定安装路径或固定同步偏移。
- 自动计算结果只能作为候选，涉及写入、人物合并或人工点位移动时必须经过明确的人工作用。
