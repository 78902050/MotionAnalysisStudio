# 二维视频骨骼修正恢复测试记录

日期：2026-09-06

## 结果

- 视频来源解析：原视频优先、显式优先项、缺失回退、中文相对路径均通过。
- 已有结果导入：`*_pose.mp4` 按相机写入 `pose_video_path`，重复登记保留手工原视频绑定。
- 媒体绑定：只更新所选相机和来源字段，源视频字节不变；支持清除与切换优先来源。
- 后台帧读取：来源类型和路径参与缓存身份；项目打开时在首个 Pose 浏览请求前完成 provider 配置。
- 二维骨架：真实 HALPE_26 命名点生成 21 条有效 parent-child 边；未知模型只画点。
- 画布交互：滚轮缩放保持鼠标指向的图像坐标稳定；左键拖动空白处或中键拖动可平移，选中点的左键拖动仍用于修正。
- 四路布局：1/2/4 路分别为单画面、左右双画面和 2×2 四画面；上下行与工具区尺寸均可拖动并持久化。
- 四路联动：原始帧浏览先逆算同步帧，再按各相机映射读取对应原始帧；映射不可用时明确提示同原始帧回退。Qt heartbeat 仍满足单次事件循环停顿低于 250 ms。
- 左右分色：左侧骨架为蓝色、右侧为橙色、中轴为青绿色，判定基于语义关节点名称。

## 自动化证据

- 聚焦测试覆盖视频来源、媒体绑定、来源隔离、拓扑、平移、鼠标锚定缩放、2×2 布局、布局持久化和同步多相机地址，均通过。
- 完整回归：`.venv\Scripts\python.exe -m unittest discover -s tests -q`，305 项通过，耗时 592.467 秒。
- 编译检查：`.venv\Scripts\python.exe -m compileall -q app tests scripts` 通过。
- Windows 打包：`scripts\build_windows.ps1` 通过；DLL 审计未选择不兼容的 Poppler ICU。
- 冻结包：GUI、Workflow、Capabilities 三种 smoke 均通过；Workflow 包含二维保存/恢复和三维回放渲染。

## 真实数据证据

来源：`D:\test\data`。

- 发现 14 个 Pose2Sim 已处理试次；代表试次识别出 4 台相机和 4 路相机视频。
- 代表试次的 `cam01_pose.mp4` 被识别为 `pose2sim_overlay`。
- 与 `cam01_000000.json` 对应的视频帧实际解码成功。
- 26 个 HALPE_26 点生成 21 条语义骨架边。
- 原 Pose JSON 与视频均未写入；修正保存/备份/恢复发生在独立验收输出中。

验收报告：`outputs/real-data-acceptance/20260906-2d3d-final/acceptance.json`。

冻结程序：`outputs/build/dist/MotionAnalysisStudio.exe`。

## 已知限制

- 同一相机没有任何视频来源时只能在姿态坐标空间编辑，不能进行画面对照。
- 未知或无法唯一确认的骨架模型不自动连线。
