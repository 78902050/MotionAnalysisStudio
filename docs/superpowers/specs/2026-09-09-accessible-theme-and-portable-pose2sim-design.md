# 可读主题与可移植 Pose2Sim 运行时设计

**日期：** 2026-09-09
**状态：** 已实施并通过开发机验收
**范围：** MotionAnalysisStudio 桌面界面的主题与字号、冻结 EXE 中 Pose2Sim 二维姿态估计运行时、Pose2Sim 官方示例验收

## 1. 目标

1. 默认界面不再过暗，正文和控件文字在常见 Windows 显示器上清晰可读。
2. 用户可以在浅色、深色和跟随系统三种模式之间切换，并能调整全局字体大小；修改立即生效并持久化。
3. 页面、表格、日志、配置编辑器、二维修正画布和三维回放画布在两种主题下保持一致的视觉语义。
4. 冻结后的 EXE 必须包含 Pose2Sim/RTMLib 在 OpenVINO 路径读取 ONNX 模型所需的前端和执行 CPU 推理所需的设备插件。
5. Pose2Sim 二维姿态估计失败时，软件必须区分安装包缺件、模型下载、缓存损坏、视频读取和配置错误，避免统一显示为模型参数无效。
6. 使用 Pose2Sim 自带的单人与多人示例，在临时副本中完成源码环境和最终 EXE 的短帧验证。

## 2. 已确认的根因

另一台电脑的日志在读取 `yolox_m_8xb8-300e_humanart-c2c7a14a.onnx` 时失败，并报告：

```text
Available frontends: jax pytorch
```

同一版本的开发环境能够报告 `ir, jax, onnx, paddle, pytorch, tf, tflite`，且
`.venv/Lib/site-packages/openvino/libs/openvino_onnx_frontend.dll` 存在。当前
PyInstaller `Analysis-00.toc` 和 `PKG-00.toc` 只包含 JAX、PyTorch 前端，没有 ONNX
前端；`MotionAnalysisStudio.spec` 的 `binaries`、`datas` 和 `hiddenimports` 均为空，
完全依赖自动收集。

因此用户日志中的可达故障是冻结包漏收集 OpenVINO ONNX 前端。补入 ONNX 前端后的首次
冻结 EXE 真实样本验收进一步报告 `Device with "CPU" name is not registered`；构建 TOC
也确认缺少 `openvino_intel_cpu_plugin.dll`。这说明文件格式前端和执行设备插件是两个独立
门禁，最终安装包必须同时包含并在运行时加载二者。日志同时证明项目路径、四路
视频发现和 HALPE_26 模型配置已被 Pose2Sim 正确读取，不能把本次故障归因于视频绑定或
`Config.toml`。

## 3. 非目标

- 不修改已安装的 Pose2Sim、RTMLib、OpenVINO 或 Caliscope 源代码。
- 不把全部 OpenVINO 前端、NPU 插件或所有模型权重无差别打入安装包。
- 不自动删除用户模型缓存。
- 不提供任意颜色编辑器；本阶段只提供经过验证的浅色、深色和跟随系统模式。
- 不修改 Pose2Sim 官方示例目录；所有会产生输出的验收均使用临时副本。

## 4. 视觉方向

产品面向需要长时间查看相机画面、数值表格和运动轨迹的动作分析人员。界面的单一职责是
让“数据、画面和任务状态”比装饰更醒目。视觉签名采用类似实验仪器状态灯的青绿色强调线，
只用于当前选择、焦点和可操作提示；其余区域保持安静、高对比。

### 4.1 色彩令牌

| 语义 | 浅色 | 深色 |
|---|---|---|
| 主背景 | `#F4F7FA` | `#18222D` |
| 面板背景 | `#FFFFFF` | `#23313D` |
| 凹陷/列表背景 | `#EAF0F4` | `#16212B` |
| 主要文字 | `#17212B` | `#F5F8FA` |
| 次要文字 | `#506273` | `#C1CED8` |
| 边框 | `#C7D2DC` | `#435666` |
| 强调色 | `#087F8C` | `#58C7C2` |
| 选中背景 | `#CDEBED` | `#27565B` |
| 警告 | `#9A6700` | `#F5C451` |
| 错误 | `#B42318` | `#FF8A80` |

普通正文对背景的目标对比度不低于 4.5:1，大号标题和非文本控件边界不低于 3:1。

### 4.2 字体和密度

- 应用字体优先使用 `Microsoft YaHei UI`，其次 `Segoe UI` 和系统无衬线字体。
- 默认正文为 12pt；设置范围为 10–16pt，步长 1pt。
- 页面标题、分区标题、正文、弱提示和等宽日志通过语义角色派生，不再由页面写死像素字号。
- 控件高度随字体自然扩张；1120×720 保持主要操作无需滚动，620×480 允许通过现有滚动容器访问全部控件。
- 二维修正和三维回放继续使用可调分栏，放大字体不能压缩掉主要画布。

### 4.3 主题应用模型

新增 `app/gui/theme.py`：

```python
ThemeName = Literal["light", "dark", "system"]

@dataclass(frozen=True)
class ThemePalette:
    name: Literal["light", "dark"]
    window: str
    panel: str
    recessed: str
    text: str
    muted_text: str
    border: str
    accent: str
    selection: str
    warning: str
    error: str
    canvas: str
    canvas_grid: str

@dataclass(frozen=True)
class UiPreferences:
    theme: ThemeName = "light"
    font_point_size: int = 12

def load_ui_preferences(settings: QSettings) -> UiPreferences: ...
def save_ui_preferences(settings: QSettings, preferences: UiPreferences) -> None: ...
def resolve_palette(theme: ThemeName, application: QApplication) -> ThemePalette: ...
def build_stylesheet(palette: ThemePalette) -> str: ...
def apply_theme(application: QApplication, preferences: UiPreferences) -> ThemePalette: ...
```

`QApplication` 保存当前已解析主题名作为动态属性。普通控件使用 `uiRole` 动态属性和全局
QSS；需要自行绘制的 `CorrectionCanvas`、`TrajectoryCanvas` 以及树项目强调色从当前调色板
读取。设置保存后由 `MainWindow` 重新应用主题、刷新自绘控件，不重建项目或业务页面。

## 5. Pose2Sim 运行时设计

### 5.1 精确收集 ONNX 前端和 CPU 插件

`MotionAnalysisStudio.spec` 在分析前定位当前构建环境中的 OpenVINO 包目录，只把
`openvino_onnx_frontend.dll` 和 `openvino_intel_cpu_plugin.dll` 加入目标目录
`openvino/libs`。若任一源 DLL 不存在，构建立即失败。
保留现有 Poppler ICU 过滤规则。

构建后的 `scripts/audit_dist_dlls.ps1` 同时执行两项判断：

1. 拒绝来自 Poppler 的冲突 ICU DLL。
2. 要求 `Analysis-00.toc` 同时包含 `openvino_onnx_frontend.dll` 和
   `openvino_intel_cpu_plugin.dll`。

文件名审计只证明收集发生，不能替代运行时验证。

### 5.2 运行时探针

新增 `app/pose2sim/runtime_diagnostics.py`：

```python
@dataclass(frozen=True)
class PoseRuntimeReport:
    ok: bool
    available_frontends: tuple[str, ...]
    user_message: str
    technical_detail: str = ""
    available_devices: tuple[str, ...] = ()

def inspect_openvino_runtime() -> PoseRuntimeReport: ...
def require_pose_estimation_runtime() -> None: ...
def classify_pose2sim_failure(log_text: str, stage: str | None) -> str | None: ...
```

`inspect_openvino_runtime` 延迟导入 OpenVINO，按排序后的前端和设备名称返回结果。
`onnx` 缺失时使用固定错误标识 `MAS_POSE_RUNTIME_ONNX_MISSING`；CPU 设备缺失时使用
`MAS_POSE_RUNTIME_CPU_MISSING`，两者都给出不同的中文说明。`app.main` 新增
`--pose2sim-runtime-check`，使源码入口和冻结 EXE 都能执行同一探针。

运行 `poseEstimation` 时：

- 使用内置冻结环境：在导入 Pose2Sim 和读取模型前调用同一探针。
- 使用用户选择的外部 Python：生成的子进程脚本在该解释器中检查 OpenVINO 前端，再调用
  Pose2Sim；检查内容同时包含 ONNX 前端和 CPU 设备，不得用 GUI 进程的环境冒充外部环境。
- 其他 Pose2Sim 阶段不要求 ONNX 前端，不因本检查被阻止。

### 5.3 错误分类

`PipelineLauncher` 在阶段失败后读取有限长度的日志尾部并分类：

1. 出现固定 ONNX 缺失标识或 `Available frontends` 不含 `onnx`：安装包/外部环境缺少 ONNX 前端。
2. `Device with "CPU" name is not registered`：安装包或外部环境缺少 CPU 插件。
3. 模型文件不存在、下载 HTTP/SSL/超时：模型尚未成功下载，显示缓存位置与网络建议。
4. ONNX 前端存在但 `read_model` 报模型解析错误：提示模型缓存可能损坏；不自动删除。
5. OpenCV 无法打开视频：显示视频路径和解码建议。
6. Pose2Sim 配置解析或参数错误：保留原始参数名和日志位置。
7. 未识别错误：显示失败阶段、退出码和日志路径，不伪造原因。

日志只读取尾部用于分类，不复制或改写原日志。项目清单继续记录真实失败阶段和日志路径。

## 6. 示例数据验收

默认候选：

- `.venv/Lib/site-packages/Pose2Sim/Demo_SinglePerson`
- `.venv/Lib/site-packages/Pose2Sim/Demo_MultiPerson`

验收脚本把所选示例复制到临时目录，将 `frame_range` 限制到少量帧，并关闭非必要视频输出。
脚本不得修改示例源目录。执行层次：

1. 源码解释器执行 `--pose2sim-runtime-check`，必须报告 `onnx` 和 `CPU`。
2. 冻结 EXE 执行同一探针，必须报告 `onnx` 和 `CPU`。
3. 源码解释器在单人示例副本执行短帧 `poseEstimation`。
4. 冻结 EXE 在单人示例副本执行短帧 `poseEstimation`。
5. 多人示例至少完成运行时探针和视频发现；在模型已缓存或网络可用时执行短帧推理。

首次下载模型属于外部网络行为。验收记录必须区分“ONNX 前端缺失”和“模型下载不可用”，
不能把后者算作打包回归。

## 7. 测试与验收门禁

- 所有生产行为先有失败测试，再实现。
- 主题设置的默认值、边界、持久化和立即应用有单元/GUI 测试。
- 浅色和深色调色板的正文对比度由测试计算验证。
- 页面不再包含会破坏浅色主题的硬编码白色标题和灰色正文。
- 620×480、12pt 和 16pt 下关键页面仍有可用滚动区域。
- DLL 审计对缺少 ONNX 前端或 CPU 插件失败，对两者都存在且没有 Poppler 冲突时通过。
- OpenVINO 探针覆盖可用、缺失 ONNX 和导入失败三条路径。
- 日志分类覆盖本次真实日志特征，并保留未知错误回退。
- 完整 `unittest`、`compileall`、PyInstaller 构建、DLL 审计、EXE GUI smoke、EXE runtime check 全部通过。
- 至少一份 Pose2Sim 官方示例副本完成最终 EXE 的短帧二维姿态估计。

## 8. 已知限制

- “跟随系统”在本阶段于应用启动和保存设置时重新解析；不保证在应用运行期间跟随 Windows
  主题瞬时切换。
- 不随安装包预置大型 RTMLib 模型；第一次使用某模型仍可能需要联网下载。
- 第三方 Pose2Sim/OpenVINO 的原始英文堆栈保留在日志中，界面只增加中文归因和行动建议。
