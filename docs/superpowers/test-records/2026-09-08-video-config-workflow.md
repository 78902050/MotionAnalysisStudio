# 视频导入与 Pose2Sim 配置工作流测试记录

日期：2026-09-08

## 结果

- “视频素材”页面统一为“导入视频”，多文件作为 Pose2Sim 分析输入复制到项目 `videos` 目录。
- `1`、`cam1`、`cam01`、`camera01` 等数字相机别名可语义匹配；非唯一顺序映射必须人工确认。
- 视频复制在后台任务执行，支持进度、取消、目标冲突统一处理和项目切换隔离；外部视频不修改、不转码。
- “Pose2Sim 流程”支持选择现有 Config.toml，验证后复制到项目 `config/Config.toml`，外部文件保持不变。
- 参数页和 TOML 源码页编辑同一文档。布尔值与已知枚举使用下拉框，其他普通值可直接编辑；复杂表保留在源码页。
- 参数名使用 `ⓘ` 和中文悬浮说明，不显示参考文件中的英文注释。自定义参数及中文说明保存在项目内。
- Pose2Sim 的开发入口、冻结 EXE 和用户选择的外部 Python 入口均在内存配置中强制注入当前项目根目录，不改写磁盘中的外部 Config。
- `poseEstimation` 在创建后台任务前检查项目 `videos` 中至少存在一个支持的视频；二维修正选择性重跑仍不包含 `poseEstimation`。
- Pose2Sim 流程页在 620×480 下不会被控件最小宽度撑大，三栏可调整，控件区可滚动访问。

## 自动化证据

- TDD 红灯复现并覆盖：导入模型不存在、媒体页旧入口、Config 文件导入缺失、参数模型缺失、中文帮助缺失、结构化编辑器缺失、布尔 TOML 节点被错误解包、运行命令缺少项目根目录、无视频仍创建任务、枚举未使用下拉框、620 px 页面被撑到 764 px。
- 端到端测试 `tests/test_video_config_workflow_acceptance.py`：四路别名视频导入、项目相对路径、源文件不变、Config 副本编辑、中文 tooltip 和项目根目录命令全部通过。
- 构建后完整回归：`.venv\Scripts\python.exe -m unittest discover -s tests -q`，353 项通过，耗时 595.646 秒，退出码 0。
- 编译检查：`.venv\Scripts\python.exe -m compileall -q app tests scripts`，退出码 0。
- 测试中的空 MP4/MKV fixture 会产生 FFmpeg `moov atom not found` 或 `EBML header parsing failed` 警告；对应测试按预期验证错误隔离，完整套件仍通过。

## 真实数据证据

- 命令：`.venv\Scripts\python.exe scripts\real_data_acceptance.py --root D:\test\data --output outputs\acceptance\video-config-20260908`，退出码 0。
- 扫描到 14 个可识别已处理试次；代表试次含 4 台相机和 4 路可匹配视频。
- 代表二维帧含 2 个人物、26 个关节点；保存和恢复各 1 项操作，源 Pose2Sim JSON 字节不变。
- TRC 含 739 帧、22 个标记点、60 Hz；三维残影世界位移为 0.203323 m，Qt heartbeat 最大间隔约 16 ms。
- 验收报告：`outputs/acceptance/video-config-20260908/acceptance.json`。

## Windows 构建证据

- 构建环境：Python 3.12.14、PyInstaller 6.22.2、tomlkit 0.15.1；PySide6.QtWidgets、Pose2Sim 和 Caliscope 均从项目 `.venv` 导入成功。
- `scripts/build_windows.ps1` 完成，DLL 审计结果为“no incompatible Poppler ICU libraries were selected”。
- 最终产物：`outputs/build/dist/MotionAnalysisStudio.exe`，233,754,093 字节，构建时间 2026-09-08 20:24:04。
- `scripts/smoke_exe.ps1 -Mode All`：GUI、Workflow、Capabilities 三项全部通过，退出码 0；先前的 QtWidgets DLL 加载错误未复现。
- PyInstaller 报告一个未找到的可选隐藏导入 `scipy.special._cdflib`；现有 GUI、工作流、能力 smoke 和完整测试均未触发相关失败。

## 恢复归档证据

- 归档脚本已把 `MotionAnalysisStudio.spec` 纳入源码包，避免恢复后缺失 Windows 构建清单。
- 源码归档：`D:\CODEX\2026-09-02\motion-analysis-studio-video-config-20260908-complete.zip`。
- 归档关键结构检查覆盖 `app/main.py`、端到端验收测试、构建脚本、PyInstaller spec 和 `pyproject.toml`。
- 从归档解压到独立目录后运行完整测试：353 项通过，耗时 663.242 秒，退出码 0；GUI、Workflow、Capabilities 套件内 smoke 通过。

## 已知限制

- 本轮没有执行耗时较长的完整 Pose2Sim 八阶段真实分析；验证覆盖命令、项目目录注入、任务状态、既有结果读取和选择性重跑白名单。
- 冻结 EXE 已验证真实启动与页面构造，但当前自动化环境未驱动冻结程序中的系统文件选择器完成鼠标点击流程；相同页面控件和导入链路由源码 Qt 测试及端到端测试覆盖。
- 尚未在一台完全不含开发环境的独立 Windows 电脑上验证便携运行。
- 分析视频采用项目内复制，会占用与所选源视频相当的额外空间；不执行压缩或转码。
