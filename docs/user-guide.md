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

构建产物位于项目内 `outputs/build/dist/MotionAnalysisStudio.exe`。构建脚本通过项目相对路径定位入口，不依赖开发机绝对路径。

## 数据保护

- 原始视频、原始标定文件和 `D:\test\data` 样本只读使用，不转码、不覆盖。
- 对比报告和诊断包写入项目工作区或用户指定的临时目录。
- 阶段任务关闭时先请求取消，再等待后台线程退出。
- 发生输入缺失或能力不可用时，界面显示原因，不伪造成功结果。

## 已知限制

- 对比成员目前由页面或应用服务提供；从多个项目目录自动枚举人物、试次和指标版本将在后续工程化增强中接入。
- 完整真实项目副本验收需要提供包含 `manifest.json` 的 `D:\test\test`；当前环境仅提供没有项目清单的 `D:\test\data` 样本目录。
