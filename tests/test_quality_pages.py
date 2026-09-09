import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QScrollArea, QWidget

from app.domain.addresses import FrameAddress, KeypointAddress, PersonAddress
from app.domain.issues import QualityIssue
from app.gui.pages.quality_2d_page import Quality2DPage
from app.gui.pages.quality_3d_page import Quality3DPage
from app.gui.main_window import MainWindow
from app.project.manager import ProjectManager
from app.quality.model import QualityReport
from app.quality.report_store import QualityReportStore
from app.quality.viewer import QualityViewerModel


def _locatable_issue() -> QualityIssue:
    return QualityIssue(
        issue_id="issue-reprojection-17",
        kind="reprojection",
        severity="warning",
        target=FrameAddress("cam03", "pose2d", 42),
        person=PersonAddress("person-02", "segment-b", 1),
        keypoint=KeypointAddress("coco17", "left_ankle", 15),
        message="左脚踝重投影误差偏高",
        disposition="handled",
        modification_count=3,
    )


def _report(*issues: QualityIssue) -> QualityReport:
    return QualityReport(
        report_id="quality-report-v7",
        generated_at="2026-09-05T10:00:00+00:00",
        metrics_data={
            "missing_rate": 0.1,
            "average_reprojection_error": 2.5,
            "coverage_start_frame": 0,
            "coverage_end_frame": 100,
        },
        issues_data=tuple(issues),
        inputs={"pose_3d": {"available": True}},
    )


class QualityViewerModelTests(unittest.TestCase):
    def test_issue_rows_expose_audit_fields_and_report_version(self) -> None:
        model = QualityViewerModel(_report(_locatable_issue()))

        row = model.issues[0]

        self.assertEqual(row.issue_id, "issue-reprojection-17")
        self.assertEqual(row.severity, "warning")
        self.assertEqual(row.disposition, "handled")
        self.assertEqual(row.modification_count, 3)
        self.assertEqual(row.message, "左脚踝重投影误差偏高")
        self.assertEqual(row.report_version, "quality-report-v7")

    def test_target_is_the_report_target_and_missing_parts_have_specific_reasons(self) -> None:
        complete = _locatable_issue()
        missing_person = QualityIssue(
            "issue-no-person",
            "mapping_missing",
            "blocking",
            FrameAddress("cam01", "pose2d", 9),
            None,
            KeypointAddress("coco17", "right_wrist", 10),
            "无法确定人物",
        )
        model = QualityViewerModel(_report(complete, missing_person))

        self.assertIs(model.target(complete.issue_id), model.issues[0].target)
        self.assertEqual(model.target(complete.issue_id), _report(complete).target(complete.issue_id))
        self.assertIsNone(model.target(missing_person.issue_id))
        self.assertEqual(model.unlocatable_reason(missing_person.issue_id), "缺少人物定位信息")


class QualityPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_pages_are_real_scrollable_widgets_at_supported_window_sizes(self) -> None:
        for page_class in (Quality2DPage, Quality3DPage):
            with self.subTest(page=page_class.__name__):
                page = page_class()
                self.assertIsInstance(page, QWidget)
                for width, height in ((1120, 720), (620, 480)):
                    page.resize(width, height)
                    page.show()
                    self.application.processEvents()
                    scroll = page.findChild(QScrollArea, "quality_page_scroll")
                    self.assertIsNotNone(scroll)
                    assert scroll is not None
                    self.assertEqual(
                        scroll.horizontalScrollBarPolicy(),
                        Qt.ScrollBarPolicy.ScrollBarAsNeeded,
                    )
                    self.assertEqual(
                        scroll.verticalScrollBarPolicy(),
                        Qt.ScrollBarPolicy.ScrollBarAsNeeded,
                    )
                    self.assertGreaterEqual(scroll.widget().minimumWidth(), 900)
                    self.assertGreaterEqual(scroll.widget().minimumHeight(), 600)
                page.close()

    def test_clicking_a_locatable_issue_emits_the_same_correction_target_on_both_pages(self) -> None:
        report = _report(_locatable_issue())
        expected = report.target("issue-reprojection-17")

        for page_class in (Quality2DPage, Quality3DPage):
            with self.subTest(page=page_class.__name__):
                page = page_class()
                emitted: list[object] = []
                page.target_requested.connect(emitted.append)
                page.set_report(report, {})

                page.issue_table.cellClicked.emit(0, 0)

                self.assertEqual(len(emitted), 1)
                self.assertIs(emitted[0], page.viewer_model.issues[0].target)
                self.assertEqual(emitted[0], expected)
                page.close()

    def test_clicking_an_unlocatable_issue_shows_reason_without_emitting(self) -> None:
        issue = QualityIssue(
            "issue-no-keypoint",
            "mapping_missing",
            "blocking",
            FrameAddress("cam02", "pose2d", 6),
            PersonAddress("person-01", raw_person_index=0),
            None,
            "关节点名称无法匹配",
        )
        page = Quality2DPage()
        emitted: list[object] = []
        page.target_requested.connect(emitted.append)
        page.set_report(_report(issue), {})

        page.issue_table.cellClicked.emit(0, 0)

        self.assertEqual(emitted, [])
        self.assertIn("缺少关节点定位信息", page.location_status.text())
        page.close()

    def test_2d_page_names_the_raw_camera_frame_person_and_keypoint(self) -> None:
        issue = QualityIssue(
            "low-confidence-raw",
            "low_confidence",
            "warning",
            FrameAddress("camA", "raw", 12),
            PersonAddress("raw-1", raw_person_index=1),
            KeypointAddress("HALPE_26", "LWrist", 9),
            "相机 camA 原始帧 12 人物 1 的 LWrist 置信度 0.180 低于阈值 0.500",
            {"confidence": 0.18, "threshold": 0.5},
        )
        page = Quality2DPage()

        page.set_report(_report(issue), {})

        self.assertEqual(page.issue_table.rowCount(), 1)
        self.assertEqual(
            page.issue_table.item(0, 6).text(),
            "camA · 原始帧 12 · 人物 1 · LWrist",
        )
        self.assertEqual(page.issue_table.item(0, 5).text(), "0.180 < 0.500")
        page.close()

    def test_2d_page_requests_manual_scan_and_pages_large_result_sets(self) -> None:
        issues = tuple(
            QualityIssue(
                issue_id=f"low-confidence-{index:03d}",
                kind="low_confidence",
                severity="warning",
                target=FrameAddress("camA", "raw", index),
                person=PersonAddress("raw-1", raw_person_index=0),
                keypoint=KeypointAddress("HALPE_26", "LWrist", 9),
                message="低置信度",
                evidence={"confidence": 0.2, "threshold": 0.5},
            )
            for index in range(205)
        )
        page = Quality2DPage()
        requested: list[bool] = []
        page.scan_requested.connect(lambda: requested.append(True))

        page.set_report(_report(*issues), {})
        page.scan_button.click()

        self.assertEqual(requested, [True])
        self.assertEqual(page.issue_table.rowCount(), 200)
        self.assertEqual(page.issue_table.item(0, 0).text(), "low-confidence-000")
        self.assertIn("第 1/2 页 · 共 205 项", page.issue_page_label.text())
        self.assertTrue(page.next_issue_page_button.isEnabled())

        page.next_issue_page_button.click()

        self.assertEqual(page.issue_table.rowCount(), 5)
        self.assertEqual(page.issue_table.item(0, 0).text(), "low-confidence-200")
        self.assertIn("第 2/2 页 · 共 205 项", page.issue_page_label.text())
        page.close()

    def test_2d_page_filters_by_camera_frame_keypoint_and_confidence(self) -> None:
        issues = (
            QualityIssue(
                "low-camera-a-4",
                "low_confidence",
                "warning",
                FrameAddress("camA", "raw", 4),
                PersonAddress("raw-0", raw_person_index=0),
                KeypointAddress("HALPE_26", "LWrist", 9),
                "camA 第 4 帧左手腕置信度低",
                {"confidence": 0.2, "threshold": 0.5},
            ),
            QualityIssue(
                "low-camera-b-16",
                "low_confidence",
                "warning",
                FrameAddress("camB", "raw", 16),
                PersonAddress("raw-0", raw_person_index=0),
                KeypointAddress("HALPE_26", "RWrist", 10),
                "camB 第 16 帧右手腕置信度低",
                {"confidence": 0.3, "threshold": 0.5},
            ),
            QualityIssue(
                "low-camera-a-30",
                "low_confidence",
                "warning",
                FrameAddress("camA", "raw", 30),
                PersonAddress("raw-0", raw_person_index=0),
                KeypointAddress("HALPE_26", "RWrist", 10),
                "camA 第 30 帧右手腕置信度低",
                {"confidence": 0.4, "threshold": 0.5},
            ),
        )
        page = Quality2DPage()
        page.set_report(
            QualityReport(
                "quality-filter-report",
                "2026-09-05T10:00:00+00:00",
                {},
                issues,
                {"pose_2d": {"raw_person_indices": [0, 1]}},
            ),
            {},
        )

        page.camera_filter.setCurrentIndex(page.camera_filter.findData("camA"))
        self.assertGreaterEqual(page.person_filter.findData(1), 0)
        self.assertEqual(
            page.person_filter.itemText(page.person_filter.findData(0)), "人物 0"
        )
        page.person_filter.setCurrentIndex(page.person_filter.findData(0))
        page.frame_start_filter.setValue(20)
        page.frame_end_filter.setValue(30)
        page._toggle_keypoint_filter(
            page.keypoint_filter.model().index(
                page.keypoint_filter.findData("LWrist"), 0
            )
        )
        page._toggle_keypoint_filter(
            page.keypoint_filter.model().index(
                page.keypoint_filter.findData("RWrist"), 0
            )
        )
        page.confidence_operator.setCurrentIndex(
            page.confidence_operator.findData("at_most")
        )
        page.confidence_threshold.setValue(0.45)

        self.assertEqual(page.issue_table.rowCount(), 3)
        self.assertIn("点击“开始筛选”", page.location_status.text())
        page.apply_filters_button.click()
        self.assertEqual(page.issue_table.rowCount(), 1)
        self.assertEqual(page.issue_table.item(0, 0).text(), "low-camera-a-30")
        self.assertIn("筛选后显示 1/3", page.location_status.text())
        page.close()

    def test_project_manifest_and_current_report_feed_quality_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory) / "项目", "质量页面")
            report = _report(_locatable_issue())
            QualityReportStore(project).save(report)
            project.manifest["quality"] = {
                "status": "current",
                "current_report_id": report.report_id,
                "last_rerun_at": "2026-09-05T11:30:00+00:00",
                "comparison": {
                    "before_report_id": "quality-report-v6",
                    "after_report_id": report.report_id,
                    "before_metrics": {"missing_rate": 0.2},
                    "after_metrics": {"missing_rate": 0.15},
                },
            }
            project.save_manifest()

            page = Quality3DPage(project)

            self.assertIn("missing_rate: 0.2", page.before_metrics.text())
            self.assertIn("missing_rate: 0.1", page.current_metrics.text())
            self.assertNotIn("missing_rate: 0.15", page.current_metrics.text())
            self.assertIn("2026-09-05 11:30", page.last_rerun.text())
            self.assertIn("quality-report-v7", page.report_version.text())
            page.close()

    def test_navigating_back_to_quality_page_reloads_latest_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory), "质量刷新")
            QualityReportStore(project).save(_report(_locatable_issue()))
            window = MainWindow()
            self.assertTrue(window.open_project(project, dirty_decision="discard"))
            updated = QualityReport(
                "quality-report-v8",
                "2026-09-05T12:00:00+00:00",
                {"missing_rate": 0.05},
                (),
                {},
            )
            QualityReportStore(project).save(updated)

            self.assertTrue(window.navigate("quality_2d"))

            quality_page = window._pages["quality_2d"]
            self.assertIn("quality-report-v8", quality_page.report_version.text())
            window.close()

    def test_main_window_routes_quality_issue_through_service_to_correction_page(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "项目"
            project = ProjectManager.create(root, "质量到修正")
            project.manifest["cameras"] = [{"camera_id": "cam03"}]
            project.manifest["people"] = [{"project_person_id": "person-02"}]
            project.save_manifest()
            (root / "synchronization" / "mapping.json").write_text(
                json.dumps(
                    {"offsets": [{"camera": "cam03", "frame_delta": 2, "source": "sync-map"}]}
                ),
                encoding="utf-8",
            )
            (root / "pose" / "cam03.json").write_text(
                json.dumps(
                    {
                        "camera": "cam03",
                        "keypoint_names": ["left_ankle"],
                        "frames": [
                            {
                                "frame": 44,
                                "people": [
                                    {
                                        "raw_person_index": 1,
                                        "keypoints": {
                                            "left_ankle": {"x": 10, "y": 20, "confidence": 0.5}
                                        },
                                    }
                                ],
                            },
                            {
                                "frame": 45,
                                "people": [
                                    {
                                        "raw_person_index": 1,
                                        "keypoints": {
                                            "left_ankle": {"x": 11, "y": 21, "confidence": 0.6}
                                        },
                                    }
                                ],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (root / "pose-associated" / "results.json").write_text(
                json.dumps(
                    {
                        "frames": [
                            {
                                "camera": "cam03",
                                "frame": 42,
                                "people": [
                                    {"project_person_id": "person-02", "raw_person_index": 1}
                                ],
                            },
                            {
                                "camera": "cam03",
                                "frame": 43,
                                "people": [
                                    {"project_person_id": "person-02", "raw_person_index": 1}
                                ],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            report = _report(_locatable_issue())
            QualityReportStore(project).save(report)
            window = MainWindow()

            self.assertTrue(window.open_project(project))
            quality_page = window._pages["quality_3d"]
            self.assertIsInstance(quality_page, Quality3DPage)
            quality_page.issue_table.cellClicked.emit(0, 0)
            self.application.processEvents()

            self.assertIs(window.current_page, window._pages["correction_2d"])
            correction = window._pages["correction_2d"]
            self.assertEqual(correction.current_camera.text(), "cam03")
            self.assertEqual(correction.synchronized_frame.text(), "42")
            self.assertEqual(correction.raw_frame.text(), "44")
            self.assertTrue(correction.save_button.isEnabled())
            self.assertEqual(correction.timeline.maximum(), 100)

            correction.next_frame_button.click()
            self.application.processEvents()
            self.assertEqual(correction.synchronized_frame.text(), "43")
            self.assertEqual(correction.raw_frame.text(), "45")

            correction.nudge_selected(1, 0)
            active_session = correction.session
            active_value = active_session.document.value_at(correction.resolution.edit_target)
            correction.timeline.setValue(44)
            with patch.object(window, "_ask_dirty_decision", return_value="cancel"):
                correction.timeline.sliderReleased.emit()

            self.assertIs(correction.session, active_session)
            self.assertEqual(correction.timeline.value(), 43)
            self.assertEqual(
                active_session.document.value_at(correction.resolution.edit_target),
                active_value,
            )
            correction.discard_unsaved()
            second = ProjectManager.create(Path(directory) / "项目二", "第二项目")
            self.assertTrue(window.open_project(second))
            self.assertIsNone(correction.session)
            self.assertIsNone(correction.resolution)
            self.assertFalse(correction.save_button.isEnabled())
            window.close()

    def test_main_window_loads_raw_video_address_for_a_low_confidence_2d_issue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "原始二维质检"
            project = ProjectManager.create(root, "原始二维质检")
            project.manifest["cameras"] = [{"camera_id": "camA"}, {"camera_id": "camB"}]
            project.save_manifest()
            (root / "pose" / "camA.json").write_text(
                json.dumps(
                    {
                        "camera": "camA",
                        "model_name": "coco17",
                        "keypoint_names": ["left_wrist"],
                        "frames": [
                            {
                                "frame": 12,
                                "people": [
                                    {
                                        "raw_person_index": 0,
                                        "keypoints": {
                                            "left_wrist": {
                                                "x": 10,
                                                "y": 20,
                                                "confidence": 0.2,
                                            }
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            issue = QualityIssue(
                "low-confidence-raw",
                "low_confidence",
                "warning",
                FrameAddress("camA", "raw", 12),
                PersonAddress("raw-0", raw_person_index=0),
                KeypointAddress("coco17", "left_wrist", 0),
                "左手腕置信度偏低",
                {"confidence": 0.2, "threshold": 0.5},
            )
            extra_issue = QualityIssue(
                "low-confidence-other-camera",
                "low_confidence",
                "warning",
                FrameAddress("camB", "raw", 13),
                PersonAddress("raw-0", raw_person_index=0),
                KeypointAddress("coco17", "left_wrist", 0),
                "另一个相机的问题",
                {"confidence": 0.3, "threshold": 0.5},
            )
            QualityReportStore(project).save(_report(issue, extra_issue))
            window = MainWindow()
            try:
                self.assertTrue(window.open_project(project))
                correction = window._pages["correction_2d"]
                self.assertEqual(correction.issue_list.count(), 2)
                quality_page = window._pages["quality_2d"]
                quality_page.camera_filter.setCurrentIndex(
                    quality_page.camera_filter.findData("camA")
                )
                self.application.processEvents()
                self.assertEqual(correction.issue_list.count(), 2)
                quality_page.apply_filters_button.click()
                self.application.processEvents()
                self.assertEqual(correction.issue_list.count(), 1)
                queue_item = correction.issue_list.item(0)
                self.assertIn("camA · 原始帧 12 · 人物 0 · left_wrist", queue_item.text())
                correction.issue_list.itemClicked.emit(queue_item)
                self.application.processEvents()

                self.assertEqual(correction.raw_frame.text(), "12")
                self.assertEqual(
                    correction._view_addresses["camA"],
                    FrameAddress("camA", "raw", 12),
                )
                self.assertEqual(
                    correction._view_addresses["camB"],
                    FrameAddress("camB", "raw", 12),
                )
            finally:
                window.close()


def _locatable_issue_target():
    report = _report(_locatable_issue())
    target = report.target("issue-reprojection-17")
    assert target is not None
    return target


if __name__ == "__main__":
    unittest.main()
