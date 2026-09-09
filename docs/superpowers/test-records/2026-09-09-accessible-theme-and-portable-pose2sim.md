# 可读主题与可移植 Pose2Sim 运行时测试记录

日期：2026-09-09

## 状态

开发机验收通过。浅色、深色、跟随系统主题和 10～16 pt 字号设置已接入；冻结 EXE 已补齐 OpenVINO ONNX 前端与 CPU 推理插件，并在 Pose2Sim 官方 `Demo_SinglePerson` 临时副本中完成真实二维姿态估计。

独立干净 Windows 电脑尚未完成现场验收，因此本记录不把当前构建标记为正式发布版本。跨电脑接续时应先执行本文和交接文档中的运行时检查。

## 修复内容

- 默认使用浅色主题，支持浅色、深色和跟随系统；字号可在 10～16 pt 范围内即时调整并持久化。
- 页面文字、面板、输入控件、二维修正画布、三维轨迹画布和配置参数帮助标记统一从语义调色板取色。
- Pose2Sim 二维姿态估计启动前，在真正执行阶段的 Python 或冻结 EXE 环境内检查 OpenVINO ONNX 前端和 CPU 设备。
- 冻结构建精确收集 `openvino_onnx_frontend.dll` 与 `openvino_intel_cpu_plugin.dll`，构建审计缺少任一文件都会失败。
- 对 ONNX 前端、CPU 插件、模型下载、模型损坏和视频读取问题提供可操作的中文错误信息。
- 官方样例验收只操作临时副本，将帧范围限制为 3 帧，不修改 Pose2Sim 安装目录中的原始示例。

## 自动化验证

```text
.venv\Scripts\python.exe -m unittest discover -s tests -q
Ran 383 tests in 747.443s
OK
GUI smoke check passed
Motion Analysis Studio smoke test: OK
Workflow smoke check passed

.venv\Scripts\python.exe -m compileall -q app tests scripts\pose2sim_sample_acceptance.py
通过

git diff --check
通过；仅出现 Windows 工作区 LF/CRLF 转换提示
```

本轮开始前的基线为 353 项测试全部通过；开发过程中一次完整回归为 379 项全部通过，最终增加 CPU 插件和 Runtime smoke 覆盖后为 383 项全部通过。

## Windows EXE 验收

产物：`outputs/build/dist/MotionAnalysisStudio.exe`

- 大小：247,784,880 字节。
- 构建时间：2026-09-09 10:44:57。
- DLL 审计：未选择不兼容的 Poppler ICU；ONNX 前端和 CPU 插件均存在。
- 冻结运行时：OpenVINO 前端为 `jax, onnx, pytorch`，设备为 `CPU`。
- `scripts/smoke_exe.ps1 -Mode All`：GUI、Workflow、Capabilities、Runtime 全部通过。

## Pose2Sim 官方样例验收

样例源：`.venv/Lib/site-packages/Pose2Sim/Demo_SinglePerson`

- 源码运行方式：4 台相机，每台 3 帧，生成 12 个 pose JSON，用时约 4 秒。
- 冻结 EXE：4 台相机，每台 3 帧，生成 12 个 pose JSON，用时约 7 秒。
- 两种方式均使用 OpenVINO CPU，成功加载人体检测与 RTMPose ONNX 模型。
- 验收目录由系统临时目录创建并自动删除；官方样例源目录未修改。

日志：

- `outputs/acceptance/pose2sim-source-single.log`
- `outputs/acceptance/pose2sim-exe-runtime.out.log`
- `outputs/acceptance/pose2sim-exe-runtime.err.log`
- `outputs/acceptance/pose2sim-exe-single.log`

## 界面验收

- Windows 原生平台确认可用 `Microsoft YaHei UI`，应用优先使用该字体。
- 1120×720 设置页面在默认 12 pt 下无控件重叠。
- 620×480、16 pt 的布局回归通过，操作区可通过滚动访问。
- 浅色和深色主题均完成 Windows 原生截图检查。

截图：

- `outputs/theme-preview/light-windows.png`
- `outputs/theme-preview/dark-windows.png`

## 已知限制

- 尚未在一台完全不含 Python、开发虚拟环境和模型缓存的独立 Windows 电脑上完成现场验收。
- 安装包包含推理运行组件，但不内置 RTMLib 模型权重；首次运行仍可能需要联网下载模型，或由用户预先复制模型缓存。
- “跟随系统”在应用启动或保存设置时解析；应用运行期间操作系统主题自动切换不会立即触发刷新。
- 控制台使用不支持 UTF-8 的旧代码页时中文输出可能显示乱码，但 GUI、日志文件和功能结果不受影响。
