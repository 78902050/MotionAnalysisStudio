"""Chinese-only guidance for Pose2Sim 0.10.49 configuration parameters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ParameterHelp:
    description: str
    choices: tuple[str, ...] = ()
    unit: str = ""
    stage: str = ""
    warning: str = ""

    def tooltip(self) -> str:
        lines = [f"用途：{self.description}"]
        if self.choices:
            lines.append("可选值：" + "、".join(self.choices))
        if self.unit:
            lines.append(f"单位：{self.unit}")
        if self.stage:
            lines.append(f"影响阶段：{self.stage}")
        if self.warning:
            lines.append(f"注意：{self.warning}")
        return "\n".join(lines)


_KNOWN = frozenset(
    tuple(value.split("."))
    for value in """
project.project_dir project.multi_person project.participant_height project.participant_mass
project.frame_rate project.frame_range project.exclude_from_batch
pose.pose_model pose.mode pose.det_frequency pose.device pose.backend pose.parallel_workers_pose
pose.display_detection pose.overwrite_pose pose.save_video pose.output_format pose.handle_LR_swap
pose.undistort_points pose.average_likelihood_threshold pose.tracking_mode pose.predict_displacement
pose.match_by pose.max_distance_px pose.min_iou pose.max_unseen_frames
synchronization.synchronization_gui synchronization.display_sync_plots synchronization.save_sync_plots
synchronization.keypoints_to_consider synchronization.approx_time_maxspeed
synchronization.time_range_around_maxspeed synchronization.likelihood_threshold_synchronization
synchronization.filter_cutoff synchronization.filter_order
calibration.calibration_type calibration.convert.convert_from calibration.convert.qualisys.binning_factor
calibration.calculate.save_debug_images calibration.calculate.intrinsics.overwrite_intrinsics
calibration.calculate.intrinsics.intrinsics_extension calibration.calculate.intrinsics.extract_every_N_sec
calibration.calculate.intrinsics.intrinsics_corners_nb calibration.calculate.intrinsics.intrinsics_square_size
calibration.calculate.intrinsics.show_detection_intrinsics
calibration.calculate.extrinsics.calculate_extrinsics calibration.calculate.extrinsics.extrinsics_method
calibration.calculate.extrinsics.extrinsics_extension calibration.calculate.extrinsics.show_reprojection_error
calibration.calculate.extrinsics.moving_cameras calibration.calculate.extrinsics.board.board_position
calibration.calculate.extrinsics.board.extrinsics_corners_nb
calibration.calculate.extrinsics.board.extrinsics_square_size
calibration.calculate.extrinsics.scene.object_coords_3d
personAssociation.single_person.likelihood_threshold_association
personAssociation.single_person.reproj_error_threshold_association
personAssociation.single_person.tracked_keypoint
personAssociation.multi_person.reconstruction_error_threshold personAssociation.multi_person.min_affinity
triangulation.reproj_error_threshold_triangulation triangulation.likelihood_threshold_triangulation
triangulation.min_cameras_for_triangulation triangulation.predict_displacement triangulation.match_by
triangulation.max_distance_m triangulation.max_unseen_frames triangulation.interp_if_gap_smaller_than
triangulation.interpolation triangulation.remove_incomplete_frames triangulation.sections_to_keep
triangulation.min_chunk_size triangulation.fill_large_gaps_with triangulation.show_interp_indices
triangulation.make_c3d
filtering.reject_outliers filtering.filter filtering.type filtering.display_figures filtering.save_filt_plots
filtering.make_c3d filtering.butterworth.cut_off_frequency filtering.butterworth.order
filtering.kalman.trust_ratio filtering.kalman.smooth filtering.one_euro.cut_off_frequency
filtering.one_euro.beta filtering.one_euro.d_cut_off_frequency filtering.gcv_spline.cut_off_frequency
filtering.gcv_spline.smoothing_factor filtering.acc_minimizing.cut_off_frequency
filtering.loess.nb_values_used filtering.gaussian.sigma_kernel filtering.median.kernel_size
filtering.butterworth_on_speed.cut_off_frequency filtering.butterworth_on_speed.order
markerAugmentation.feet_on_floor markerAugmentation.make_c3d
kinematics.use_augmentation kinematics.use_simple_model kinematics.filter_ik kinematics.ik_filter_type
kinematics.right_left_symmetry kinematics.default_height kinematics.parallel_workers_kinematics
kinematics.remove_individual_scaling_setup kinematics.remove_individual_ik_setup
kinematics.large_hip_knee_angles kinematics.trimmed_extrema_percent logging.use_custom_logging
""".split()
)

_SECTION_STAGE = {
    "project": "全部流程",
    "pose": "二维姿态估计",
    "synchronization": "视频同步",
    "calibration": "相机标定",
    "personAssociation": "人物关联",
    "triangulation": "三角化",
    "filtering": "滤波",
    "markerAugmentation": "标记点增强",
    "kinematics": "运动学",
    "logging": "运行日志",
}

_DESCRIPTION = {
    "project_dir": "Pose2Sim 读取视频并写入分析结果的项目目录。",
    "multi_person": "指定画面中是否需要同时分析多个人物。",
    "participant_height": "参与者身高，用于标记点增强和人体尺度计算。",
    "participant_mass": "参与者质量，用于运动学缩放和后续动力学计算。",
    "frame_rate": "分析时间轴使用的帧率；自动模式会从视频读取。",
    "frame_range": "限定需要分析的帧范围，自动模式会依据有效重建区间裁剪。",
    "exclude_from_batch": "批处理时需要跳过的试次目录列表。",
    "pose_model": "选择二维姿态模型及其关节点定义。",
    "mode": "选择姿态模型的速度/精度档位，或填写自定义模型字典。",
    "det_frequency": "每隔多少帧重新执行人物检测，中间帧继续跟踪。",
    "device": "选择执行姿态推理的计算设备。",
    "backend": "选择姿态模型的推理后端。",
    "parallel_workers_pose": "控制二维姿态估计并行处理的视频数量。",
    "display_detection": "运行时是否实时显示二维检测画面。",
    "overwrite_pose": "已有二维结果时是否重新计算并覆盖。",
    "save_video": "指定保存带关节点视频、逐帧图像或不保存可视化。",
    "output_format": "指定二维关节点结果的输出格式。",
    "handle_LR_swap": "控制是否尝试处理左右肢体误交换。",
    "undistort_points": "控制是否对二维关节点执行镜头畸变校正。",
    "average_likelihood_threshold": "人物平均关节点置信度低于该值时忽略该人物。",
    "tracking_mode": "选择跨帧人物跟踪算法。",
    "predict_displacement": "跟踪时是否依据历史运动预测下一帧位置。",
    "match_by": "指定跨帧匹配人物所使用的几何特征。",
    "max_distance_px": "二维跟踪中允许人物跨帧移动的最大像素距离。",
    "min_iou": "使用包围框匹配时要求的最小重叠比例。",
    "max_unseen_frames": "人物暂时不可见后仍保留原身份的最长帧数。",
    "synchronization_gui": "是否打开交互窗口人工辅助确定相机同步。",
    "display_sync_plots": "同步完成后是否显示相关性图。",
    "save_sync_plots": "是否保存同步相关性图。",
    "keypoints_to_consider": "选择用于计算相机时间偏移的关节点。",
    "approx_time_maxspeed": "指定各相机明显快速动作的大致时间。",
    "time_range_around_maxspeed": "在快速动作时间前后搜索同步偏移的范围。",
    "likelihood_threshold_synchronization": "同步计算接受二维关节点的最低置信度。",
    "filter_cutoff": "同步信号平滑滤波的截止频率。",
    "filter_order": "同步信号滤波器阶数。",
    "calibration_type": "选择转换已有标定文件或重新计算标定。",
    "convert_from": "指定需要转换的外部标定文件格式。",
    "binning_factor": "标定图像的像素合并倍率。",
    "save_debug_images": "是否保存标定点选取和重投影调试图。",
    "overwrite_intrinsics": "是否重新计算并覆盖已有相机内参。",
    "intrinsics_extension": "用于计算内参的图像或视频扩展名。",
    "extract_every_N_sec": "从内参视频中按指定秒数间隔提取一帧。",
    "intrinsics_corners_nb": "内参棋盘格的内部角点行列数。",
    "intrinsics_square_size": "内参棋盘格单格的实际尺寸。",
    "show_detection_intrinsics": "是否显示内参角点检测结果。",
    "calculate_extrinsics": "是否计算相机外参。",
    "extrinsics_method": "选择棋盘、场景点或关节点外参方法。",
    "extrinsics_extension": "用于计算外参的图像扩展名。",
    "show_reprojection_error": "是否显示外参重投影误差。",
    "moving_cameras": "标记相机在采集过程中是否移动。",
    "board_position": "指定外参棋盘摆放方向。",
    "extrinsics_corners_nb": "外参棋盘格的内部角点行列数。",
    "extrinsics_square_size": "外参棋盘格单格的实际尺寸。",
    "object_coords_3d": "人工场景点对应的三维实际坐标列表。",
    "likelihood_threshold_association": "单人物关联接受二维关节点的最低置信度。",
    "reproj_error_threshold_association": "单人物关联接受候选对应的最大重投影误差。",
    "tracked_keypoint": "单人物模式中用于稳定跟踪身份的关节点。",
    "reconstruction_error_threshold": "多人物关联接受三维候选的最大重建误差。",
    "min_affinity": "多人物跨相机对应关系的最低亲和度。",
    "reproj_error_threshold_triangulation": "三角化结果允许的最大重投影误差。",
    "likelihood_threshold_triangulation": "三角化接受单相机二维点的最低置信度。",
    "min_cameras_for_triangulation": "一个关节点能够三角化所需的最少相机数。",
    "max_distance_m": "三维人物跨帧匹配允许的最大位移。",
    "interp_if_gap_smaller_than": "仅对小于该帧数的缺失区间插值。",
    "interpolation": "选择三维缺失数据的插值方法。",
    "remove_incomplete_frames": "是否删除仍包含缺失关节点的帧。",
    "sections_to_keep": "选择保留全部、最大、最前或最后的有效连续片段。",
    "min_chunk_size": "有效连续片段必须达到的最少帧数。",
    "fill_large_gaps_with": "指定较大缺失区间的填充值策略。",
    "show_interp_indices": "是否报告发生插值的帧索引。",
    "make_c3d": "是否额外生成 C3D 文件。",
    "reject_outliers": "是否先使用异常值滤波清理突变点。",
    "filter": "是否执行选定的平滑滤波。",
    "type": "选择三维轨迹滤波算法。",
    "display_figures": "是否显示滤波前后对比图。",
    "save_filt_plots": "是否保存滤波对比图。",
    "cut_off_frequency": "滤波器截止频率，数值越低平滑越强。",
    "order": "滤波器阶数。",
    "trust_ratio": "卡尔曼滤波中测量值相对运动模型的信任比例。",
    "smooth": "是否执行前后向平滑以减少相位偏移。",
    "beta": "速度对自适应截止频率的影响强度。",
    "d_cut_off_frequency": "速度导数信号的截止频率。",
    "smoothing_factor": "自动样条滤波的平滑偏置。",
    "nb_values_used": "局部回归每次拟合使用的数据点数量。",
    "sigma_kernel": "高斯滤波核的标准差。",
    "kernel_size": "中值滤波窗口大小。",
    "feet_on_floor": "是否将足部标记整体调整到水平地面。",
    "use_augmentation": "运动学分析是否使用增强生成的标记点。",
    "use_simple_model": "是否使用计算更快的简化 OpenSim 模型。",
    "filter_ik": "是否对逆运动学结果继续滤波。",
    "ik_filter_type": "选择逆运动学结果使用的滤波方法。",
    "right_left_symmetry": "人体模型缩放时是否约束左右侧对称。",
    "default_height": "自动身高估计失败时使用的默认身高。",
    "parallel_workers_kinematics": "运动学分析同时处理的人物数量。",
    "remove_individual_scaling_setup": "完成后是否删除个人缩放临时设置文件。",
    "remove_individual_ik_setup": "完成后是否删除个人逆运动学临时设置文件。",
    "large_hip_knee_angles": "髋膝角超过该值时标记为低精度。",
    "trimmed_extrema_percent": "计算平均节段值前剔除极端值的比例。",
    "use_custom_logging": "集成外部日志系统时是否使用自定义日志配置。",
}

_CHOICES = {
    ("project", "frame_rate"): ("auto", "整数"),
    ("pose", "device"): ("auto", "CPU", "CUDA", "MPS", "ROCM"),
    ("pose", "backend"): ("auto", "openvino", "onnxruntime", "opencv"),
    ("pose", "tracking_mode"): ("sports2d", "deepsort"),
    ("synchronization", "keypoints_to_consider"): ("all", "关节点列表"),
    ("calibration", "calibration_type"): ("convert", "calculate"),
    ("triangulation", "interpolation"): ("linear", "slinear", "quadratic", "cubic", "none"),
    ("triangulation", "sections_to_keep"): ("all", "largest", "first", "last"),
}

_UNITS = {
    "participant_height": "米",
    "participant_mass": "千克",
    "frame_rate": "帧/秒",
    "max_distance_px": "像素",
    "time_range_around_maxspeed": "秒",
    "filter_cutoff": "赫兹",
    "intrinsics_square_size": "毫米",
    "extrinsics_square_size": "毫米",
    "reproj_error_threshold_association": "像素",
    "reconstruction_error_threshold": "米",
    "reproj_error_threshold_triangulation": "像素",
    "max_distance_m": "米",
    "cut_off_frequency": "赫兹",
    "d_cut_off_frequency": "赫兹",
    "default_height": "米",
    "large_hip_knee_angles": "度",
    "trimmed_extrema_percent": "百分比",
}

_WARNINGS = {
    ("project", "project_dir"): "该值由当前项目管理，运行时不会允许写入其他项目。",
    ("project", "multi_person"): "设置错误会改变人物筛选和跨相机关联方式。",
    ("project", "frame_rate"): "错误帧率会使同步偏移和时间轴换算失真。",
    ("pose", "overwrite_pose"): "启用后会重新执行二维姿态估计并覆盖已有结果。",
    ("triangulation", "reproj_error_threshold_triangulation"): "阈值过大可能接受错误三维点，过小可能造成大量缺失。",
}


def known_parameter_paths() -> frozenset[tuple[str, ...]]:
    return _KNOWN


def help_for(
    path: tuple[str, ...],
    custom: Mapping[str, str] | None = None,
) -> ParameterHelp:
    key = ".".join(path)
    if path not in _KNOWN:
        description = (custom or {}).get(key, "自定义参数，请依据当前 Pose2Sim 版本确认含义和取值。")
        return ParameterHelp(description=description, stage="自定义配置")
    parameter = path[-1]
    return ParameterHelp(
        description=_DESCRIPTION.get(parameter, f"设置“{parameter}”参数。"),
        choices=_CHOICES.get(path, ()),
        unit=_UNITS.get(parameter, ""),
        stage=_SECTION_STAGE.get(path[0], "Pose2Sim"),
        warning=_WARNINGS.get(path, ""),
    )
