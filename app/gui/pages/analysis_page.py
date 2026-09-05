"""Background 3D trajectory metric workbench."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.analysis.metrics import MetricEngine
from app.analysis.model import MetricConfig, MetricDefinition, MetricTable, Trajectory
from app.project.manager import ProjectManager

from ..layout import make_scrollable_panel


class _AnalysisWorker(QObject):
    finished = Signal(str, int, object)
    failed = Signal(str, int, str)

    def __init__(
        self,
        project_id: str,
        generation: int,
        trajectory: Trajectory | None,
        project_root: Path | None,
        definitions: tuple[MetricDefinition, ...],
        config: MetricConfig,
    ) -> None:
        super().__init__()
        self.project_id = project_id
        self.generation = generation
        self.trajectory = trajectory
        self.project_root = project_root
        self.definitions = definitions
        self.config = config

    @Slot()
    def run(self) -> None:
        try:
            self._raise_if_interrupted()
            trajectory = self.trajectory or self._load_trajectory()
            self._raise_if_interrupted()
            table = MetricEngine().calculate(trajectory, self.definitions, self.config)
            self._raise_if_interrupted()
        except Exception as exc:  # returned to the page as a visible failure
            self.failed.emit(self.project_id, self.generation, f"{type(exc).__name__}: {exc}")
            return
        self.finished.emit(self.project_id, self.generation, table)

    def _load_trajectory(self) -> Trajectory:
        if self.project_root is None:
            raise ValueError("未提供轨迹输入")
        candidates = sorted((self.project_root / "pose-3d").glob("*.trc"))
        if not candidates:
            raise FileNotFoundError(f"未找到 pose-3d TRC 文件：{self.project_root / 'pose-3d'}")
        return Trajectory.from_trc(candidates[0], coordinate_system="world")

    @staticmethod
    def _raise_if_interrupted() -> None:
        if QThread.currentThread().isInterruptionRequested():
            raise RuntimeError("运动学计算已取消")


class AnalysisPage(QWidget):
    def __init__(self, project: ProjectManager | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.trajectory: Trajectory | None = None
        self._generation = 0
        self._project_id = ""
        self._thread: QThread | None = None
        self._worker: _AnalysisWorker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        heading = QLabel("三维运动学")
        heading.setStyleSheet("font-size: 22px; font-weight: 700; color: #ffffff;")
        layout.addWidget(heading)
        description = QLabel(
            "位置、速度、加速度和角度指标在后台计算。每列保留单位、坐标系、采样率、滤波和输入来源。"
        )
        description.setWordWrap(True)
        description.setStyleSheet("color: #aab9c4; font-size: 14px;")
        layout.addWidget(description)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("采样率 Hz"))
        self.sampling_rate = QDoubleSpinBox()
        self.sampling_rate.setRange(0.001, 100000.0)
        self.sampling_rate.setDecimals(3)
        self.sampling_rate.setValue(60.0)
        self.sampling_rate.setObjectName("analysis_sampling_rate")
        controls.addWidget(self.sampling_rate)
        controls.addWidget(QLabel("坐标单位"))
        self.coordinate_unit = QComboBox()
        self.coordinate_unit.addItems(["m", "cm", "mm"])
        self.coordinate_unit.setObjectName("analysis_coordinate_unit")
        controls.addWidget(self.coordinate_unit)
        controls.addWidget(QLabel("滤波"))
        self.filter_selector = QComboBox()
        self.filter_selector.addItems(["无", "moving_average", "median"])
        self.filter_selector.setObjectName("analysis_filter")
        controls.addWidget(self.filter_selector)
        self.calculate_button = QPushButton("后台计算")
        self.calculate_button.setObjectName("analysis_calculate_button")
        self.calculate_button.clicked.connect(self.calculate)
        controls.addWidget(self.calculate_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        form = QFormLayout()
        self.input_value = QLabel("—")
        self.input_value.setObjectName("analysis_input_value")
        self.coordinate_value = QLabel("—")
        self.coordinate_value.setObjectName("analysis_coordinate_value")
        self.status = QLabel("请先打开项目或提供轨迹")
        self.status.setObjectName("analysis_status")
        self.status.setWordWrap(True)
        form.addRow("轨迹输入", self.input_value)
        form.addRow("坐标约定", self.coordinate_value)
        form.addRow("状态", self.status)
        layout.addLayout(form)

        self.metric_table = QTableWidget(0, 4)
        self.metric_table.setObjectName("analysis_metric_table")
        self.metric_table.setHorizontalHeaderLabels(["指标列", "单位", "输入标签", "结果预览"])
        self.metric_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.metric_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.metric_table, 1)

        scroll = make_scrollable_panel(body)
        scroll.setObjectName("analysis_scroll")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def set_project(self, project: ProjectManager | None) -> None:
        self._stop_worker()
        self._generation += 1
        self.project = project
        self.trajectory = None
        self._project_id = str(project.manifest.get("project_id", "")) if project else ""
        self.metric_table.setRowCount(0)
        self.input_value.setText("将从项目 pose-3d 目录读取" if project else "—")
        self.coordinate_value.setText("—")
        self.status.setText("已打开项目；点击“后台计算”开始" if project else "请先打开项目或提供轨迹")

    def set_trajectory(self, trajectory: Trajectory | None) -> None:
        self._stop_worker()
        self._generation += 1
        self.trajectory = trajectory
        if trajectory is None:
            self.input_value.setText("—")
            self.coordinate_value.setText("—")
            self.status.setText("请先提供轨迹")
            return
        self.coordinate_unit.setCurrentText(trajectory.coordinate_unit)
        sampling_rate = trajectory.metadata.get("sampling_rate_hz")
        if not isinstance(sampling_rate, (int, float)) or isinstance(sampling_rate, bool):
            if len(trajectory.frames) >= 2:
                frame_span = trajectory.frames[-1] - trajectory.frames[0]
                time_span = trajectory.times[-1] - trajectory.times[0]
                sampling_rate = frame_span / time_span if frame_span > 0 and time_span > 0 else 60.0
            else:
                sampling_rate = 60.0
        self.sampling_rate.setValue(float(sampling_rate))
        self.input_value.setText(trajectory.source_path or "内存轨迹")
        self.coordinate_value.setText(f"{trajectory.coordinate_system} / {trajectory.coordinate_unit}")
        self.status.setText("轨迹已就绪；点击“后台计算”开始")

    def calculate(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            self.status.setText("运动学计算正在进行")
            return
        if self.trajectory is None and self.project is None:
            self.status.setText("请先打开项目或提供轨迹")
            return
        self._generation += 1
        generation = self._generation
        self._project_id = str(self.project.manifest.get("project_id", "")) if self.project else self._project_id or "memory"
        unit = self.coordinate_unit.currentText()
        filter_name = self.filter_selector.currentText()
        filter_name = None if filter_name == "无" else filter_name
        config = MetricConfig(self.sampling_rate.value(), unit, filter_name)
        labels = self.trajectory.labels if self.trajectory is not None else ()
        anchor = "Hip" if "Hip" in labels else "hip" if "hip" in labels else (labels[0] if labels else "Hip")
        definitions = (
            MetricDefinition(f"position:{anchor}", unit, (anchor,)),
            MetricDefinition(f"speed:{anchor}", f"{unit}/s", (anchor,)),
            MetricDefinition(f"acceleration:{anchor}", f"{unit}/s^2", (anchor,)),
        )
        self.status.setText("正在后台计算指标…")
        self.calculate_button.setEnabled(False)
        self._thread = QThread(self)
        self._worker = _AnalysisWorker(
            self._project_id,
            generation,
            self.trajectory,
            self.project.root if self.project else None,
            definitions,
            config,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._calculation_finished)
        self._worker.failed.connect(self._calculation_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._thread_finished)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    @Slot(str, int, object)
    def _calculation_finished(self, project_id: str, generation: int, value: object) -> None:
        if project_id != self._project_id or generation != self._generation:
            return
        if not isinstance(value, MetricTable):
            self.status.setText("运动学计算返回了无效结果")
            return
        self._fill_table(value)
        self.input_value.setText(str(value.metadata.get("input_source") or "内存轨迹"))
        self.coordinate_value.setText(
            f"{value.metadata['coordinate_system']} / {value.metadata['coordinate_unit']} / {value.metadata['sampling_rate_hz']} Hz"
        )
        self.status.setText(f"计算完成：{len(value.columns)} 个指标列，{len(value.frames)} 帧")

    @Slot(str, int, str)
    def _calculation_failed(self, project_id: str, generation: int, reason: str) -> None:
        if project_id == self._project_id and generation == self._generation:
            self.status.setText(f"运动学计算失败：{reason}")

    def _fill_table(self, table: MetricTable) -> None:
        self.metric_table.setRowCount(0)
        for name, values in table.columns.items():
            row = self.metric_table.rowCount()
            self.metric_table.insertRow(row)
            self.metric_table.setItem(row, 0, QTableWidgetItem(name))
            self.metric_table.setItem(row, 1, QTableWidgetItem(table.units[name]))
            labels = table.provenance[name].get("input_labels", ())
            self.metric_table.setItem(row, 2, QTableWidgetItem(", ".join(str(label) for label in labels)))
            preview = ", ".join("NaN" if value != value else f"{value:.4g}" for value in values[:4])
            self.metric_table.setItem(row, 3, QTableWidgetItem(preview))

    def _thread_finished(self) -> None:
        self.calculate_button.setEnabled(True)
        self._thread = None
        self._worker = None

    def _stop_worker(self) -> None:
        if self._thread is None or not self._thread.isRunning():
            return
        self._generation += 1
        self._thread.requestInterruption()
        self._thread.quit()
        self._thread.wait(5000)

    def closeEvent(self, event) -> None:
        self._generation += 1
        self._stop_worker()
        event.accept()
