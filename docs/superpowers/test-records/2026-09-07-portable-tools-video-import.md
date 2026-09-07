# 外部工具文件夹与自定义视频导入测试记录

日期：2026-09-07

## 结果

- 设置页改用文件夹选择器，可从常见 Windows 虚拟环境根目录、`Scripts` 目录或 Pose2Sim 包目录识别运行入口。
- Pose2Sim 保存所属环境的 `python.exe`；普通八阶段流程和二维修正后的选择性重跑都会动态读取该设置。
- Caliscope 保存识别出的 `caliscope.exe`，相机标定页继续使用同一设置启动 GUI。
- 旧版直接保存的可执行文件路径可继续读取并显示为安装目录。
- 视频页支持为选中相机导入任意文件名的单个原视频，以及从一个文件夹按相机名批量导入。
- 批量导入只写项目清单，不复制或转码视频；只有唯一匹配才绑定，多个候选会列为歧义。
- 导入原视频时忽略 `_pose`、`_sync`、`_tracked` 和 `_calibration` 等已知派生视频名称。

## 自动化证据

- TDD 红灯复现了原问题：设置页拒绝文件夹、启动器忽略用户选择的 Python、批量导入接口与按钮动作缺失。
- 路径解析、设置持久化、普通流程、选择性重跑、单文件绑定、批量绑定、来源优先级和四路帧 provider 聚焦测试通过。
- 完整回归：`.venv\Scripts\python.exe -m unittest discover -s tests -q`，315 项通过，耗时 529.923 秒。
- 编译检查：`.venv\Scripts\python.exe -m compileall -q app tests scripts` 通过。
- Windows 构建和 DLL 审计通过；GUI、Workflow、Capabilities 三种冻结包 smoke 全部通过。

## 真实环境与数据证据

- 从项目 `.venv` 文件夹识别到 `.venv\Scripts\python.exe` 和 `.venv\Scripts\caliscope.exe`。
- 识别出的 Python 可导入 Pose2Sim 的八个阶段函数。
- `D:\test\data\8.12\起跑\pose` 中的 `cam01_pose.mp4` 至 `cam04_pose.mp4` 可按四个相机唯一匹配为 Pose2Sim 标记视频。
- 完整真实数据验收通过；报告：`outputs/real-data-acceptance/20260907-portable-tools-video-import/acceptance.json`。

冻结程序：`outputs/build/dist/MotionAnalysisStudio.exe`。

## 已知限制

- 自动识别针对常见 Windows Python、venv 和 conda 目录结构；非标准启动脚本仍需把包含对应环境的目录整理为可识别结构。
- 批量视频导入只扫描所选文件夹顶层，不递归扫描子目录；任意命名或放在其他目录的视频可使用“为选中相机导入原视频”。
