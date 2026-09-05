# Motion Analysis Studio 使用指引

## 启动和环境检查

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m app.main --smoke-test
```

该命令只检查 Python、PySide6、NumPy、OpenCV、PyInstaller、Pose2Sim 和 Caliscope 能力，不打开界面，也不修改项目数据。

正常打开桌面程序：

```powershell
.\.venv\Scripts\python.exe -m app.main
```

## 项目工作流

1. 打开或创建项目，确认项目路径和相机清单。
2. 依次完成标定、同步、二维质检、二维修正、多人关联、三维质检和运动学指标。
3. 在“事件周期”页选择指标列和阈值，检测事件并人工调整需要修正的事件。
4. 在“对比报告”页明确选择项目、人物和试次，再选择帧、精确时间或事件出现序号对齐。
5. 只通过“导出 JSON/CSV/HTML”生成报告；项目上下文下默认写入 `reports/comparisons`。

报告会记录输入版本、对齐来源、指标列和缺失原因。缺失值保持为空，不会被静默当成零。

## 主要页面

- “相机标定”在导入前显示源文件、内容差异和阻断问题；激活后按相机显示图像尺寸、内参矩阵、畸变、旋转、平移和重投影误差。内容等价的文件会明确提示，不会伪装成一次数据更新。
- “媒体”在后台扫描视频元数据，列表较大时不会在界面线程逐个读取；“设置”可配置工具路径、缓存大小、关键点微调步长和界面布局。
- “二维质检/二维修正”使用相机、同步帧、原始帧、项目人物和关节点名称定位。首次保存保留备份，撤销、重做和文件恢复同时处理坐标与置信度。
- “人物关联”把检测人物、项目人物和轨迹段分开显示；候选只提供证据，必须人工确认后才物化。
- “运动分析/事件周期/对比报告”强制记录坐标单位、采样率、输入版本和算法版本。不兼容单位不能比较；缺失值不会按零处理。

二维修正后的选择性重跑从 `personAssociation` 开始，不会再次执行 `poseEstimation`。

## 诊断包

诊断包只包含脱敏后的项目清单、运行时能力和小型日志，不包含视频、姿态 JSON、TRC 或其他大型输入。应用服务调用示例：

```python
from app.diagnostics.bundle import DiagnosticBundle

DiagnosticBundle().create(project, project.root / "diagnostics.zip")
```

## Windows 打包和 smoke

```powershell
.\scripts\build_windows.ps1
.\scripts\smoke_exe.ps1
```

构建产物位于项目内 `outputs/build/dist/MotionAnalysisStudio.exe`。`smoke_exe.ps1` 默认依次验证 Qt 界面构造、质检问题到二维修正/备份/恢复事务和运行时能力，也可用 `-Mode Gui`、`-Mode Workflow` 或 `-Mode Capabilities` 单独检查。构建脚本通过项目相对路径定位入口，不依赖开发机绝对路径。

## 真实数据验收

默认使用 `D:\test\data`，从中选择一份可读标定、TRC 和 Pose2Sim JSON，复制到仓库内独立验收项目后完成读取、二维修正、首次备份、恢复和指标计算：

```powershell
.\scripts\run_real_data_acceptance.ps1
```

可用 `-Root` 指定其他样本根目录，用 `-OutputRoot` 指定一个尚不存在且位于样本目录之外的输出目录。验收报告写入输出目录的 `acceptance.json`；视频仅记录绝对引用，不复制、不转码。

## 数据保护

- 应用只修改项目工作区内的工作文件；原始 MP4 不转码、不覆盖。
- `D:\test\data` 已获准用于测试操作，但自动验收仍默认复制标定、TRC 和 pose 样本到独立输出目录，以便结果可复查且不污染样本。
- 对比报告和诊断包写入项目工作区或用户指定的临时目录。
- 阶段任务关闭时先请求取消，再等待后台线程退出。
- 发生输入缺失或能力不可用时，界面显示原因，不伪造成功结果。

## 已知限制

- 对比成员目前由页面或应用服务提供；从多个项目目录自动枚举人物、试次和指标版本将在后续工程化增强中接入。
- 当前构建已在开发机完成 DLL 审计、GUI smoke 和能力 smoke，但尚未在一台不含开发环境的独立 Windows 电脑上验证，因此不能把“跨电脑部署”门禁标记为完成。
