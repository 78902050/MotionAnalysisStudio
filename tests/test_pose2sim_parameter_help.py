import json
import tempfile
import unittest
from pathlib import Path

from app.pose2sim.custom_help_store import CustomHelpStore
from app.pose2sim.parameter_help_zh import help_for, known_parameter_paths


EXPECTED_PATHS = {
    tuple(value.split("."))
    for value in """
project.project_dir project.multi_person project.participant_height
project.participant_mass project.frame_rate project.frame_range project.exclude_from_batch
pose.pose_model pose.mode pose.det_frequency pose.device pose.backend
pose.parallel_workers_pose pose.display_detection pose.overwrite_pose pose.save_video
pose.output_format pose.handle_LR_swap pose.undistort_points
pose.average_likelihood_threshold pose.tracking_mode pose.predict_displacement
pose.match_by pose.max_distance_px pose.min_iou pose.max_unseen_frames
synchronization.synchronization_gui synchronization.display_sync_plots
synchronization.save_sync_plots synchronization.keypoints_to_consider
synchronization.approx_time_maxspeed synchronization.time_range_around_maxspeed
synchronization.likelihood_threshold_synchronization synchronization.filter_cutoff
synchronization.filter_order calibration.calibration_type
calibration.convert.convert_from calibration.convert.qualisys.binning_factor
calibration.calculate.save_debug_images
calibration.calculate.intrinsics.overwrite_intrinsics
calibration.calculate.intrinsics.intrinsics_extension
calibration.calculate.intrinsics.extract_every_N_sec
calibration.calculate.intrinsics.intrinsics_corners_nb
calibration.calculate.intrinsics.intrinsics_square_size
calibration.calculate.intrinsics.show_detection_intrinsics
calibration.calculate.extrinsics.calculate_extrinsics
calibration.calculate.extrinsics.extrinsics_method
calibration.calculate.extrinsics.extrinsics_extension
calibration.calculate.extrinsics.show_reprojection_error
calibration.calculate.extrinsics.moving_cameras
calibration.calculate.extrinsics.board.board_position
calibration.calculate.extrinsics.board.extrinsics_corners_nb
calibration.calculate.extrinsics.board.extrinsics_square_size
calibration.calculate.extrinsics.scene.object_coords_3d
personAssociation.single_person.likelihood_threshold_association
personAssociation.single_person.reproj_error_threshold_association
personAssociation.single_person.tracked_keypoint
personAssociation.multi_person.reconstruction_error_threshold
personAssociation.multi_person.min_affinity
triangulation.reproj_error_threshold_triangulation
triangulation.likelihood_threshold_triangulation
triangulation.min_cameras_for_triangulation triangulation.predict_displacement
triangulation.match_by triangulation.max_distance_m triangulation.max_unseen_frames
triangulation.interp_if_gap_smaller_than triangulation.interpolation
triangulation.remove_incomplete_frames triangulation.sections_to_keep
triangulation.min_chunk_size triangulation.fill_large_gaps_with
triangulation.show_interp_indices triangulation.make_c3d
filtering.reject_outliers filtering.filter filtering.type filtering.display_figures
filtering.save_filt_plots filtering.make_c3d filtering.butterworth.cut_off_frequency
filtering.butterworth.order filtering.kalman.trust_ratio filtering.kalman.smooth
filtering.one_euro.cut_off_frequency filtering.one_euro.beta
filtering.one_euro.d_cut_off_frequency filtering.gcv_spline.cut_off_frequency
filtering.gcv_spline.smoothing_factor filtering.acc_minimizing.cut_off_frequency
filtering.loess.nb_values_used filtering.gaussian.sigma_kernel
filtering.median.kernel_size filtering.butterworth_on_speed.cut_off_frequency
filtering.butterworth_on_speed.order markerAugmentation.feet_on_floor
markerAugmentation.make_c3d kinematics.use_augmentation kinematics.use_simple_model
kinematics.filter_ik kinematics.ik_filter_type kinematics.right_left_symmetry
kinematics.default_height kinematics.parallel_workers_kinematics
kinematics.remove_individual_scaling_setup kinematics.remove_individual_ik_setup
kinematics.large_hip_knee_angles kinematics.trimmed_extrema_percent
logging.use_custom_logging
""".split()
}


class Pose2SimParameterHelpTests(unittest.TestCase):
    def test_catalog_covers_all_standard_editable_sample_parameters_in_chinese(self) -> None:
        self.assertTrue(EXPECTED_PATHS.issubset(known_parameter_paths()))
        for path in EXPECTED_PATHS:
            item = help_for(path)
            self.assertTrue(item.description.strip(), ".".join(path))
            self.assertTrue(item.stage.strip(), ".".join(path))
            self.assertNotIn("With RTMLib", item.tooltip())
            self.assertNotIn("Set to false if", item.tooltip())

    def test_critical_parameters_have_actionable_chinese_warnings(self) -> None:
        for path in (
            ("project", "project_dir"),
            ("project", "multi_person"),
            ("project", "frame_rate"),
            ("pose", "overwrite_pose"),
            ("triangulation", "reproj_error_threshold_triangulation"),
        ):
            self.assertTrue(help_for(path).warning)

    def test_unknown_parameter_uses_custom_chinese_description_or_fallback(self) -> None:
        path = ("pose", "my_parameter")

        self.assertIn("自定义参数", help_for(path).description)
        self.assertEqual(
            help_for(path, {"pose.my_parameter": "控制我的模型参数"}).description,
            "控制我的模型参数",
        )

    def test_custom_help_round_trips_on_chinese_path_and_rejects_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "中文项目"
            values = {"pose.my_parameter": "控制我的模型参数"}

            CustomHelpStore.save(root, values)

            self.assertEqual(CustomHelpStore.load(root), values)
            path = root / "config" / "parameter_help.zh.json"
            path.write_text("[]\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "中文参数说明"):
                CustomHelpStore.load(root)
            path.write_text(json.dumps({"x": 1}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "中文参数说明"):
                CustomHelpStore.load(root)


if __name__ == "__main__":
    unittest.main()
