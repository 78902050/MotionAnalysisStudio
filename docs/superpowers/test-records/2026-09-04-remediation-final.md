# 稳定性、易用性与准确性整改最终测试记录

日期：2026-09-05

## 状态

开发机验收通过。阶段 1～8 的整改任务已完成；阶段 9 已完成开发机上的真实数据复制工作区验收、Windows EXE 构建、DLL 审计、GUI smoke、冻结产物工作流 smoke 和能力 smoke。

独立干净 Windows 电脑尚未验证，因此跨电脑部署门禁和总体路线图仍为“未完全完成”，当前构建不标记为正式发布就绪。

## 本轮完成内容

- 恢复相机标定页面的逐相机参数展示，包括图像尺寸、内参、畸变、旋转、平移和重投影误差。
- 完成后台任务生命周期、真实 Caliscope/Pose2Sim 数据适配、修正事务、多相机解码、语义人物关联、单位化分析、事件周期、对比报告和响应式桌面页面整改。
- 修复 Pose2Sim/OpenPose 扁平 `pose_keypoints_2d` 文件可保存但恢复审计为零的问题；恢复记录现在保留人物和关节点语义以及完整 before/after 三元组。
- 增加可重复的真实数据验收脚本，默认把输入复制到独立项目后执行，不修改源 pose JSON。
- 增加冻结 EXE 工作流 smoke，在最终产物内实际执行质量问题定位、二维修正、事务保存、首次备份和恢复。

## 自动化验证

```text
.venv\Scripts\python.exe -m unittest discover -s tests -q
Ran 208 tests in 141.951s
OK
GUI smoke check passed
Motion Analysis Studio smoke test: OK
Workflow smoke check passed

.venv\Scripts\python.exe -m compileall -q app tests scripts
通过

git diff --check
通过；仅出现 Windows 工作区 LF/CRLF 转换提示
```

覆盖范围包括中文路径、v2 到 v3 幂等迁移、原子事务故障注入、损坏 JSON/JSONL、二维撤销恢复、四路视频 heartbeat、项目切换与取消、人物语义关联、单位与坐标系约束、事件和周期、6000 行对比表响应性、报告导出和应用关闭回收。

## 真实数据验收

命令：

```text
scripts\run_real_data_acceptance.ps1 -Root D:\test\data
```

报告：`outputs/real-data-acceptance/20260905-202716/acceptance.json`

结果：

- Caliscope 标定：4 台相机，ID 为 1、2、3、4。
- TRC：739 帧、22 个标记、60 Hz、单位 m；生成 `Hip.speed` 指标。
- Pose2Sim：cam01 第 0 帧，2 人、每人 26 个关节点。
- 二维修正：保存 1 条操作，建立首次备份，恢复 1 条操作。
- 源 Pose2Sim JSON 前后字节一致。
- 选择性重跑为 `personAssociation`、`triangulation`、`filtering`、`markerAugmentation`、`kinematics`，不包含 `poseEstimation`。

验收只复制标定、TRC 和单帧 pose 到独立输出项目；MP4 仅作为绝对路径引用，不转码、不覆盖。

## Windows EXE 验收

构建：

```text
scripts\build_windows.ps1
```

结果：PyInstaller 构建成功；DLL 审计通过，未选择不兼容的 Poppler ICU 库。

产物：`outputs/build/dist/MotionAnalysisStudio.exe`

大小：233,483,993 字节；构建时间：2026-09-05 20:44:19。

冻结产物验证：

```text
scripts\smoke_exe.ps1 -Executable outputs\build\dist\MotionAnalysisStudio.exe -Mode All
MotionAnalysisStudio.exe Gui smoke test passed
MotionAnalysisStudio.exe Workflow smoke test passed
MotionAnalysisStudio.exe Capabilities smoke test passed
```

GUI smoke 实际导入 `PySide6.QtWidgets`、创建 `QApplication` 和 `MainWindow` 并处理事件循环。工作流 smoke 在冻结包内部创建临时项目并完成质量问题定位、二维保存、备份和恢复，随后正常删除临时项目。

## 已知限制

- 尚未在一台不含 Python、项目虚拟环境和开发工具的独立 Windows 电脑上启动并完成相同 smoke；这是当前唯一阻止阶段 9 和总体路线图完全完成的发布门禁。
- 对比成员目前由页面或应用服务提供，尚未从多个项目目录自动枚举人物、试次和指标版本。
- PyInstaller 分析报告提示未找到 `scipy.special._cdflib` 隐藏导入；当前应用路径和三段冻结 smoke 未使用或触发该模块，未造成可达失败。若后续引入依赖该内部模块的 SciPy 功能，应增加对应真实功能测试后再决定是否显式收集。
