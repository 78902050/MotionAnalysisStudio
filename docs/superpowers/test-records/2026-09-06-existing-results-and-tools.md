# 已处理结果与外部工具实施测试记录

日期：2026-09-06

## 实施范围

- 单个已处理试次读取和上级目录批量扫描。
- 无源视频时读取 Pose2Sim 逐帧二维 JSON、TRC 和其他已有结果。
- Caliscope GUI 启动、日志、重复启动保护和设置编码诊断。
- Config.toml 语法验证、文本保持、原子保存和逐次备份。
- Pose2Sim 八阶段按当前、选中或从当前阶段执行，实时日志、取消和阶段结果记录。
- 二维修正选择性重跑继续排除 `poseEstimation`。

## 自动化验证

- 任务 1–6 聚焦测试与相关 GUI、项目迁移、修正重跑回归均通过。
- 完整测试：243 项通过；GUI smoke、安装 smoke、workflow smoke 通过。
- 扩展 workflow smoke 覆盖无视频已处理目录登记、嵌套 pose 质检、有效 Config 和八阶段命令构造，不启动耗时分析。
- `compileall` 与 `git diff --check` 在各任务检查点通过。

## 真实数据验证

数据根目录：`D:\test\data`

验收输出：`outputs/real-data-acceptance/20260906-011640/acceptance.json`

- 发现 14 个已处理试次。
- 读取 4 相机 Caliscope 标定。
- 读取 739 帧、22 标记点、60 Hz、米制 TRC。
- 读取 26 关键点 Pose2Sim JSON，二维修正保存和恢复各 1 次，首次备份存在。
- 无视频登记副本的二维检测人物数为 2，Config 有效，一般流程八阶段命令完整。
- 所选源 Pose2Sim JSON 验收前后字节一致。
- 当前 Caliscope 用户设置诊断为有效 GB18030；验收未执行转换。

## Windows 构建验证

- PyInstaller 6.22.2 / Python 3.12.14 构建成功。
- DLL 审计通过，未选择不兼容的 Poppler ICU。
- `outputs/build/dist/MotionAnalysisStudio.exe` 的 Gui、Workflow、Capabilities 三类 smoke 全部通过。
- 冻结 Workflow smoke 包含无视频登记、嵌套 pose 质检、Config 和八阶段命令接口。

## 已知限制

- 无视频模式没有真实影像背景，只能显示姿态坐标空间。
- 部分真实试次的 Config.toml 缺失或为空，因此可浏览已有结果但不能直接重跑；需用户提供对应有效配置。
- 尚未在不含开发环境的独立 Windows 电脑上完成净机 EXE 验证。
