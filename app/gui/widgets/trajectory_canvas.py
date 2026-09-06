"""Interactive native QPainter canvas for semantic 3D trajectories."""

from __future__ import annotations

import math
from dataclasses import replace

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import QWidget

from app.playback.model import PlaybackTrajectory, Point3D
from app.playback.projection import ViewTransform, project_points, view_coordinates
from app.visualization.skeleton import keypoint_side, skeleton_edge_side


class TrajectoryCanvas(QWidget):
    point_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.trajectory: PlaybackTrajectory | None = None
        self.edges: tuple[tuple[str, str], ...] = ()
        self.frame_index = 0
        self.trail_frames = 45
        self.ghost_poses_enabled = True
        self.max_ghost_poses = 8
        self.view_transform = ViewTransform(yaw=-0.35, pitch=-0.20)
        self.selected_label = ""
        self._last_mouse: QPointF | None = None
        self._drag_mode = ""
        self.setMinimumSize(220, 180)
        self.setMouseTracking(True)

    def set_trajectory(
        self,
        trajectory: PlaybackTrajectory | None,
        edges: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self.trajectory = trajectory
        self.edges = tuple(edges)
        self.frame_index = 0
        self.selected_label = ""
        if trajectory is not None:
            self.fit_all()
        self.update()

    def set_frame_index(self, index: int) -> None:
        if self.trajectory is None:
            self.frame_index = 0
            return
        self.frame_index = min(len(self.trajectory.frames) - 1, max(0, int(index)))
        self.update()

    def set_trail_frames(self, count: int) -> None:
        self.trail_frames = min(120, max(0, int(count)))
        self.update()

    def set_ghost_poses_enabled(self, enabled: bool) -> None:
        self.ghost_poses_enabled = bool(enabled)
        self.update()

    def set_view(self, yaw: float, pitch: float) -> None:
        self.view_transform = replace(self.view_transform, yaw=float(yaw), pitch=float(pitch))
        self.fit_all()

    def rotate_by(self, yaw_delta: float = 0.0, pitch_delta: float = 0.0) -> None:
        before = self._current_pose_screen_center(self.view_transform)
        yaw = self.view_transform.yaw + float(yaw_delta)
        yaw = (yaw + math.pi) % (2 * math.pi) - math.pi
        pitch = min(
            math.pi / 2,
            max(-math.pi / 2, self.view_transform.pitch + float(pitch_delta)),
        )
        updated = replace(self.view_transform, yaw=yaw, pitch=pitch)
        after = self._current_pose_screen_center(updated)
        if before is not None and after is not None:
            updated = replace(
                updated,
                pan_x=updated.pan_x + before.x() - after.x(),
                pan_y=updated.pan_y + before.y() - after.y(),
            )
        self.view_transform = updated
        self.update()

    def _current_pose_screen_center(self, transform: ViewTransform) -> QPointF | None:
        trajectory = self.trajectory
        if trajectory is None:
            return None
        current = {
            label: series[self.frame_index]
            for label, series in trajectory.points.items()
        }
        projected = project_points(current, transform, (self.width(), self.height()))
        points = [point for point in projected.values() if point is not None]
        if not points:
            return None
        return QPointF(
            sum(point.x() for point in points) / len(points),
            sum(point.y() for point in points) / len(points),
        )

    def fit_all(self) -> None:
        self._fit_frames((self.frame_index,))

    def fit_motion_window(self) -> None:
        self._fit_frames((*self.ghost_frame_indices(), self.frame_index))

    def _fit_frames(self, frame_indices: tuple[int, ...]) -> None:
        trajectory = self.trajectory
        if trajectory is None:
            return
        rotated = [
            coordinate
            for frame_index in dict.fromkeys(frame_indices)
            for series in trajectory.points.values()
            if (coordinate := view_coordinates(series[frame_index], self.view_transform))
            is not None
        ]
        if not rotated:
            return
        minimum_x = min(point[0] for point in rotated)
        maximum_x = max(point[0] for point in rotated)
        minimum_z = min(point[2] for point in rotated)
        maximum_z = max(point[2] for point in rotated)
        available_width = max(40.0, self.width() - 48.0)
        available_height = max(40.0, self.height() - 48.0)
        span_x = max(maximum_x - minimum_x, 1e-9)
        span_z = max(maximum_z - minimum_z, 1e-9)
        zoom = min(
            1e6,
            max(1e-6, min(available_width / span_x, available_height / span_z)),
        )
        midpoint_x = (minimum_x + maximum_x) / 2
        midpoint_z = (minimum_z + maximum_z) / 2
        self.view_transform = replace(
            self.view_transform,
            zoom=zoom,
            pan_x=-midpoint_x * zoom,
            pan_y=midpoint_z * zoom,
        )
        self.update()

    def visible_trail_segment_count(self, label: str) -> int:
        trajectory = self.trajectory
        if trajectory is None or label not in trajectory.points or self.trail_frames <= 0:
            return 0
        start = max(0, self.frame_index - self.trail_frames)
        series = trajectory.points[label]
        return sum(
            self._finite(series[index - 1]) and self._finite(series[index])
            for index in range(start + 1, self.frame_index + 1)
        )

    def ghost_frame_indices(self) -> tuple[int, ...]:
        if (
            not self.ghost_poses_enabled
            or self.trail_frames <= 0
            or self.frame_index <= 0
        ):
            return ()
        start = max(0, self.frame_index - self.trail_frames)
        available = list(range(start, self.frame_index))
        if len(available) <= self.max_ghost_poses:
            return tuple(available)
        last = len(available) - 1
        return tuple(
            available[round(index * last / (self.max_ghost_poses - 1))]
            for index in range(self.max_ghost_poses)
        )

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0b151d"))
        self._draw_grid(painter)
        trajectory = self.trajectory
        if trajectory is None:
            painter.setPen(QColor("#82939f"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "选择 TRC 或 C3D 轨迹开始回放")
            return
        current = {
            label: series[self.frame_index]
            for label, series in trajectory.points.items()
        }
        projected = project_points(current, self.view_transform, (self.width(), self.height()))
        self._draw_ghost_poses(painter, trajectory)
        self._draw_trails(painter, trajectory)
        for left, right in self.edges:
            start = projected.get(left)
            end = projected.get(right)
            if start is not None and end is not None:
                painter.setPen(QPen(self._side_color(skeleton_edge_side((left, right))), 2.4))
                painter.drawLine(start, end)
        for label, point in projected.items():
            if point is None:
                continue
            selected = label == self.selected_label
            painter.setPen(QPen(QColor("#ffd166") if selected else QColor("#b8fff5"), 2))
            painter.setBrush(QColor("#ffd166") if selected else QColor("#35b9a9"))
            radius = 5 if selected else 3
            painter.drawEllipse(point, radius, radius)
        painter.setPen(QColor("#91a7b5"))
        painter.drawText(12, 22, f"帧 {trajectory.frames[self.frame_index]}  ·  {trajectory.coordinate_unit}")

    def _draw_ghost_poses(
        self,
        painter: QPainter,
        trajectory: PlaybackTrajectory,
    ) -> None:
        indices = self.ghost_frame_indices()
        for ordinal, frame_index in enumerate(indices, start=1):
            alpha = 22 + round(78 * ordinal / max(1, len(indices)))
            pose = {
                label: series[frame_index]
                for label, series in trajectory.points.items()
            }
            projected = project_points(
                pose,
                self.view_transform,
                (self.width(), self.height()),
            )
            for left, right in self.edges:
                start = projected.get(left)
                end = projected.get(right)
                if start is None or end is None:
                    continue
                color = self._side_color(skeleton_edge_side((left, right)))
                color.setAlpha(alpha)
                painter.setPen(QPen(color, 1.5))
                painter.drawLine(start, end)
            for label, point in projected.items():
                if point is None:
                    continue
                color = self._side_color(keypoint_side(label))
                color.setAlpha(alpha)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawEllipse(point, 2, 2)

    @staticmethod
    def _side_color(side: str) -> QColor:
        return QColor(
            {
                "left": "#4da3ff",
                "right": "#ff8a4c",
                "center": "#56ddcd",
            }.get(side, "#56ddcd")
        )

    def _draw_grid(self, painter: QPainter) -> None:
        painter.setPen(QPen(QColor(35, 57, 70, 150), 1))
        spacing = 40
        for x in range(0, self.width(), spacing):
            painter.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), spacing):
            painter.drawLine(0, y, self.width(), y)
        center = QPointF(self.width() / 2 + self.view_transform.pan_x, self.height() / 2 + self.view_transform.pan_y)
        painter.setPen(QPen(QColor("#345c70"), 1.4))
        painter.drawLine(QPointF(0, center.y()), QPointF(self.width(), center.y()))
        painter.drawLine(QPointF(center.x(), 0), QPointF(center.x(), self.height()))

    def _draw_trails(self, painter: QPainter, trajectory: PlaybackTrajectory) -> None:
        if self.trail_frames <= 0:
            return
        start = max(0, self.frame_index - self.trail_frames)
        denominator = max(1, self.frame_index - start)
        for series in trajectory.points.values():
            for index in range(start + 1, self.frame_index + 1):
                first = series[index - 1]
                second = series[index]
                if not self._finite(first) or not self._finite(second):
                    continue
                projected = project_points(
                    {"a": first, "b": second},
                    self.view_transform,
                    (self.width(), self.height()),
                )
                alpha = 25 + int(95 * (index - start) / denominator)
                painter.setPen(QPen(QColor(53, 185, 169, alpha), 1.2))
                painter.drawLine(projected["a"], projected["b"])

    @staticmethod
    def _finite(point: Point3D) -> bool:
        return all(math.isfinite(float(value)) for value in point)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._last_mouse = event.position()
        if event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton
            and event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self._drag_mode = "pan"
        elif event.button() == Qt.MouseButton.LeftButton:
            self._drag_mode = "rotate"
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._last_mouse is None or not self._drag_mode:
            super().mouseMoveEvent(event)
            return
        delta = event.position() - self._last_mouse
        self._last_mouse = event.position()
        if self._drag_mode == "pan":
            self.view_transform = replace(
                self.view_transform,
                pan_x=self.view_transform.pan_x + delta.x(),
                pan_y=self.view_transform.pan_y + delta.y(),
            )
        else:
            self.view_transform = replace(
                self.view_transform,
                yaw=self.view_transform.yaw + delta.x() * 0.008,
                pitch=max(-math.pi / 2, min(math.pi / 2, self.view_transform.pitch + delta.y() * 0.008)),
            )
        self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_mode == "rotate" and self._last_mouse is not None:
            self._select_nearest(event.position())
        self._last_mouse = None
        self._drag_mode = ""
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.12 if event.angleDelta().y() > 0 else 1 / 1.12
        self.view_transform = replace(
            self.view_transform,
            zoom=min(1e6, max(1e-6, self.view_transform.zoom * factor)),
        )
        self.update()
        event.accept()

    def _select_nearest(self, position: QPointF) -> None:
        if self.trajectory is None:
            return
        current = {
            label: series[self.frame_index]
            for label, series in self.trajectory.points.items()
        }
        projected = project_points(current, self.view_transform, (self.width(), self.height()))
        candidates = [
            ((point.x() - position.x()) ** 2 + (point.y() - position.y()) ** 2, label)
            for label, point in projected.items()
            if point is not None
        ]
        if not candidates:
            return
        distance, label = min(candidates)
        if distance <= 12**2:
            self.selected_label = label
            self.point_selected.emit(label)
            self.update()
