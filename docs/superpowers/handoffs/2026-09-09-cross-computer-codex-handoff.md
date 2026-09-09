# Motion Analysis Studio 跨电脑 Codex 接续说明

日期：2026-09-09

## 交接目标

把当前项目带到另一台 Windows 电脑的 Codex 中继续开发，同时保留完整 Git 历史、当前功能设计、实施计划和测试证据。不要复制 `.venv`；不同电脑应按本机 Python 与 DLL 环境重新创建虚拟环境。

## 当前代码状态

- 仓库：`https://github.com/78902050/MotionAnalysisStudio`
- 工作分支：`codex/phase-9`
- 本轮功能基线提交：`c76db23`
- Python：3.12
- 核心外部版本：Pose2Sim 0.10.49、Caliscope 0.11.6
- 完整回归：383 项通过。
- 最新 Windows EXE 已通过 GUI、Workflow、Capabilities、Runtime smoke，并在 Pose2Sim 官方四相机样例副本上完成二维姿态估计。

当前改进的设计、执行步骤和证据分别见：

- `docs/superpowers/specs/2026-09-09-accessible-theme-and-portable-pose2sim-design.md`
- `docs/superpowers/plans/2026-09-09-accessible-theme-and-portable-pose2sim.md`
- `docs/superpowers/test-records/2026-09-09-accessible-theme-and-portable-pose2sim.md`
- `docs/user-guide.md`

## 推荐导入方式：从 GitHub 克隆

在另一台电脑打开 PowerShell：

```powershell
git clone --branch codex/phase-9 https://github.com/78902050/MotionAnalysisStudio.git
Set-Location MotionAnalysisStudio
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -e ".[desktop,analysis,build,external]"
```

然后在 Codex 中把克隆目录作为项目打开。若 GitHub 暂时不可用，可用交接包里的 `.bundle`：

```powershell
git clone .\MotionAnalysisStudio-codex-phase-9.bundle MotionAnalysisStudio
Set-Location MotionAnalysisStudio
git switch codex/phase-9
```

## Codex 首次接续顺序

让另一台电脑的 Codex 依次读取：

1. `AGENTS.md`
2. 本交接说明
3. 2026-09-09 设计文档
4. 2026-09-09 实施计划
5. 2026-09-09 测试记录
6. `docs/user-guide.md`

可以直接向新的 Codex 发送：

```text
请先阅读 AGENTS.md、docs/superpowers/handoffs/2026-09-09-cross-computer-codex-handoff.md、对应的设计文档、实施计划和测试记录。核对当前分支为 codex/phase-9，先运行运行时检查与聚焦测试，确认环境后继续开发。不要修改或删除现有用户数据和未跟踪文档。
```

## 新电脑环境验收

先确认 Python 环境中的 Pose2Sim 推理能力：

```powershell
.venv\Scripts\python.exe -m app.main --pose2sim-runtime-check
```

预期同时看到 `onnx` 前端和 `CPU` 设备。随后运行：

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -q
.venv\Scripts\python.exe -m compileall -q app tests scripts\pose2sim_sample_acceptance.py
```

如需重建 EXE：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
powershell -ExecutionPolicy Bypass -File scripts\smoke_exe.ps1 -Executable outputs\build\dist\MotionAnalysisStudio.exe -Mode All
```

如果新电脑已安装 Pose2Sim 官方样例，可按 `docs/user-guide.md` 中的命令在临时副本上执行 3 帧验收。不要直接改写 `.venv\Lib\site-packages\Pose2Sim` 中的样例。

## 交接包说明

- `MotionAnalysisStudio-codex-phase-9.bundle`：可离线克隆的 Git 分支及历史，是精确恢复代码状态的首选离线文件。
- `MotionAnalysisStudio-source-2026-09-09.zip`：从最终 Git 提交生成，不含 `.git`、`.venv`、构建输出、字节码缓存和未跟踪文件的可复现源码快照。
- `MotionAnalysisStudio-untracked-review-docs-2026-09-09.zip`：四份未跟踪历史审查文档的独立补充包，只用于查阅，不会自动覆盖 Git 中的文件。
- `handoff-manifest.txt`：记录最终提交、分支、远端、文件清单和验证结果。
- `MotionAnalysisStudio.exe` 不重复放入交接 ZIP；如需直接试用，可单独复制 `outputs/build/dist/MotionAnalysisStudio.exe`。

## 新电脑上的可变路径

不要沿用旧电脑的绝对路径。首次打开软件后，在设置中选择本机的 Pose2Sim 环境文件夹和 Caliscope 安装文件夹，再为具体项目导入视频或绑定已有结果。`D:\test\data`、旧电脑 `.venv` 和模型缓存路径都不是程序必须依赖的固定路径。

## 已知限制与下一步

- 当前唯一尚未完成的发布门禁，是在一台真正干净的 Windows 电脑上验证冻结 EXE 和首次模型下载/缓存。
- 新电脑完成验收后，把硬件、Windows 版本、运行时检查输出、样例验收结果和日志位置追加到测试记录。
- 若出现二维姿态估计错误，优先保留完整任务日志；界面现在会区分 ONNX 前端缺失、CPU 插件缺失、模型下载/损坏和视频打不开。
