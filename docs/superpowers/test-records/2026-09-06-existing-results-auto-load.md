# 已处理结果自动装载测试记录

日期：2026-09-06

## 修复范围

- 已存在 `manifest.json` 的旧试次会重新扫描并刷新相机、Pose、TRC、MOT/STO 和阶段证据，不再因清单存在而提前返回。
- “读取已处理文件夹”选中多试次上级目录时自动转入候选扫描，不在上级目录建立空项目。
- 无源视频时可直接浏览 Pose2Sim 二维帧，切换相机、已有帧、人物和关节点；HALPE_26 使用标准名称。
- 质量审计可从标准 TRC 计算三维有效点、缺失点和覆盖帧，不再依赖私有 `results.json`。
- `pose-sync` 和 `pose-associated` 标准目录作为已有结果证据；关联页显示只读文件摘要，不推断未经确认的语义身份。
- 运动分析页枚举 TRC、MOT 和 STO；TRC 计算结果接入事件页与当前项目对比成员。

## 自动化验证

```text
.venv\Scripts\python.exe -m unittest discover -s tests -q
Ran 253 tests in 414.984s
OK
GUI smoke check passed
Motion Analysis Studio smoke test: OK
Workflow smoke check passed

.venv\Scripts\python.exe -m compileall -q app tests scripts
通过
```

新增验收覆盖旧清单刷新、集合目录回退、二维直接浏览、HALPE_26 语义名称、TRC 质量回退、关联摘要、TRC/MOT/STO 列表以及分析到事件/对比的联动。

## 真实数据验证

数据根目录：`D:\test\data`

验收输出：`outputs/real-data-acceptance/20260906-123533/acceptance.json`

- 发现 14 个已处理试次。
- 读取 4 相机 Caliscope 标定，ID 为 1、2、3、4。
- 读取 739 帧、22 标记点、60 Hz、单位 m 的 TRC。
- 读取 cam01 第 0 帧：2 人、每人 26 个关节点。
- 无视频登记副本可直接建立二维编辑会话，质量报告统计 16,258 个三维点，全部为有效点。
- 二维修正保存和恢复各 1 次，首次备份存在，源 Pose JSON 前后字节一致。
- 选择性重跑阶段不包含 `poseEstimation`。

## Windows EXE 验证

- PyInstaller 6.22.2 / Python 3.12.14 构建成功。
- DLL 审计通过，未选择不兼容的 Poppler ICU 库。
- 产物：`outputs/build/dist/MotionAnalysisStudio.exe`。
- 文件大小：233,551,484 字节；构建时间：2026-09-06 12:47:35。
- Gui、Workflow、Capabilities 三类冻结产物 smoke 全部通过；Gui smoke 实际导入 `PySide6.QtWidgets` 并构造主窗口，未复现 DLL 加载错误。

## 已知限制

- 没有源视频时二维画布只能显示姿态坐标空间，不能用真实影像核对关节点。
- 缺少明确身份映射时，程序不会根据 `pose-associated` 数组顺序猜测语义人物。
- 对比页目前自动接收当前项目最新一次分析结果；跨项目、跨历史版本的自动枚举尚未接入。
- 真实试次中的空或无效 `Config.toml` 不阻止浏览，但会禁用 Pose2Sim 重跑。
- 尚未在不含 Python 和开发工具的独立 Windows 电脑上完成净机验证。
