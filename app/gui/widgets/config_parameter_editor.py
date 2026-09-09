"""Structured and source views for project-local Pose2Sim configuration."""

from __future__ import annotations

from pathlib import Path

import tomlkit
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.pose2sim.config_model import ConfigModel, ConfigParameter
from app.pose2sim.custom_help_store import CustomHelpStore
from app.pose2sim.parameter_help_zh import help_for, known_parameter_paths
from app.gui.theme import palette_for_application


_ENUM_PATHS = frozenset(
    {
        ("pose", "device"),
        ("pose", "backend"),
        ("pose", "tracking_mode"),
        ("calibration", "calibration_type"),
        ("triangulation", "interpolation"),
        ("triangulation", "sections_to_keep"),
    }
)


class ConfigParameterEditor(QWidget):
    """Keep a guided parameter tree and an editable TOML source in sync."""

    text_changed = Signal(str)
    validation_changed = Signal(bool, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project_root: Path | None = None
        self._custom_help: dict[str, str] = {}
        self._model: ConfigModel | None = None
        self._items: dict[tuple[str, ...], QTreeWidgetItem] = {}
        self._editors: dict[tuple[str, ...], QWidget] = {}
        self._updating_source = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("pipeline_config_tabs")

        parameter_page = QWidget()
        parameter_layout = QVBoxLayout(parameter_page)
        parameter_layout.setContentsMargins(0, 6, 0, 0)
        self.parameter_tree = QTreeWidget()
        self.parameter_tree.setObjectName("pipeline_parameter_tree")
        self.parameter_tree.setColumnCount(3)
        self.parameter_tree.setHeaderLabels(("参数", "值", "类型 / 单位"))
        self.parameter_tree.setAlternatingRowColors(True)
        self.parameter_tree.setRootIsDecorated(True)
        self.parameter_tree.setColumnWidth(0, 230)
        parameter_layout.addWidget(self.parameter_tree)

        self.source_editor = QPlainTextEdit()
        self.source_editor.setObjectName("pipeline_config_editor")
        self.source_editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.source_editor.textChanged.connect(self._source_changed)

        self.tabs.addTab(parameter_page, "参数设置")
        self.tabs.addTab(self.source_editor, "TOML 源码")
        self.tabs.currentChanged.connect(self._tab_changed)
        layout.addWidget(self.tabs)

    def set_project_root(self, project_root: Path | None) -> None:
        self._project_root = Path(project_root) if project_root is not None else None
        self._custom_help = (
            CustomHelpStore.load(self._project_root)
            if self._project_root is not None
            else {}
        )

    def set_text(self, text: str) -> None:
        self._set_source_text(text, emit=False)
        self.refresh_parameters()

    def text(self) -> str:
        return self.source_editor.toPlainText()

    def refresh_parameters(self) -> bool:
        try:
            model = ConfigModel.parse(self.text(), known_parameter_paths())
        except ValueError as exc:
            self._model = None
            self.parameter_tree.clear()
            self._items.clear()
            self._editors.clear()
            self.validation_changed.emit(False, str(exc))
            return False

        self._model = model
        self._rebuild_tree()
        self.validation_changed.emit(True, "Config.toml 语法有效")
        return True

    def refresh_theme(self) -> None:
        accent = QBrush(QColor(palette_for_application().accent))
        for item in self._items.values():
            item.setForeground(0, accent)
        self.parameter_tree.viewport().update()

    def item_for(self, path: tuple[str, ...]) -> QTreeWidgetItem | None:
        return self._items.get(tuple(path))

    def editor_for(self, path: tuple[str, ...]) -> QWidget | None:
        return self._editors.get(tuple(path))

    def add_custom_parameter(
        self,
        section: tuple[str, ...],
        key: str,
        toml_value: str,
        description: str,
    ) -> None:
        if not self.refresh_parameters() or self._model is None:
            raise ValueError("请先修复 TOML 语法后再添加参数")
        path = (*section, key)
        updated = self._model.add_parameter(section, key, toml_value)
        description = description.strip()
        if description:
            self._custom_help[".".join(path)] = description
            if self._project_root is not None:
                CustomHelpStore.save(self._project_root, self._custom_help)
        self._set_source_text(updated, emit=True)
        self.refresh_parameters()

    def remove_selected_parameter(self) -> bool:
        item = self.parameter_tree.currentItem()
        if item is None or self._model is None:
            return False
        raw_path = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(raw_path, tuple):
            return False
        updated = self._model.remove_parameter(raw_path)
        self._custom_help.pop(".".join(raw_path), None)
        if self._project_root is not None:
            CustomHelpStore.save(self._project_root, self._custom_help)
        self._set_source_text(updated, emit=True)
        self.refresh_parameters()
        return True

    def _source_changed(self) -> None:
        if not self._updating_source:
            self.text_changed.emit(self.text())

    def _tab_changed(self, index: int) -> None:
        if index == 0:
            self.refresh_parameters()

    def _set_source_text(self, text: str, *, emit: bool) -> None:
        self._updating_source = True
        try:
            self.source_editor.setPlainText(text)
        finally:
            self._updating_source = False
        if emit:
            self.text_changed.emit(text)

    def _rebuild_tree(self) -> None:
        self.parameter_tree.clear()
        self._items.clear()
        self._editors.clear()
        if self._model is None:
            return

        sections: dict[tuple[str, ...], QTreeWidgetItem] = {}
        for parameter in self._model.parameters:
            parent = self._section_item(parameter.path[:-1], sections)
            item = QTreeWidgetItem(parent)
            item.setText(0, f"ⓘ {parameter.path[-1]}")
            item.setForeground(0, QBrush(QColor(palette_for_application().accent)))
            item.setData(0, Qt.ItemDataRole.UserRole, parameter.path)
            tooltip = help_for(parameter.path, self._custom_help).tooltip()
            item.setToolTip(0, tooltip)
            item.setToolTip(1, tooltip)
            guidance = help_for(parameter.path, self._custom_help)
            type_text = parameter.value_type
            if guidance.unit:
                type_text = f"{type_text} / {guidance.unit}"
            item.setText(2, type_text)
            item.setToolTip(2, tooltip)
            self._items[parameter.path] = item
            editor = self._make_editor(parameter)
            self._editors[parameter.path] = editor
            self.parameter_tree.setItemWidget(item, 1, editor)
        self.parameter_tree.expandToDepth(0)

    def _section_item(
        self,
        section: tuple[str, ...],
        sections: dict[tuple[str, ...], QTreeWidgetItem],
    ) -> QTreeWidgetItem:
        parent: QTreeWidgetItem | None = None
        for depth in range(1, len(section) + 1):
            path = section[:depth]
            if path not in sections:
                item = QTreeWidgetItem(parent or self.parameter_tree)
                item.setText(0, path[-1])
                item.setFirstColumnSpanned(True)
                sections[path] = item
            parent = sections[path]
        if parent is None:
            parent = QTreeWidgetItem(self.parameter_tree)
            parent.setText(0, "常规")
        return parent

    def _make_editor(self, parameter: ConfigParameter) -> QWidget:
        if not parameter.editable or parameter.path == ("project", "project_dir"):
            label = QLabel(
                "由当前项目管理"
                if parameter.path == ("project", "project_dir")
                else "请在源码页编辑"
            )
            label.setEnabled(False)
            return label

        if parameter.value_type == "bool":
            editor = QComboBox()
            editor.addItems(("false", "true"))
            editor.setCurrentText("true" if parameter.value else "false")
            editor.currentTextChanged.connect(
                lambda value, path=parameter.path: self._commit_value(path, value)
            )
            return editor

        if parameter.path in _ENUM_PATHS:
            editor = QComboBox()
            editor.addItems(help_for(parameter.path, self._custom_help).choices)
            editor.setCurrentText(str(parameter.value))
            editor.currentTextChanged.connect(
                lambda value, path=parameter.path: self._commit_value(
                    path, self._toml_literal(value)
                )
            )
            return editor

        editor = QLineEdit(self._toml_literal(parameter.value))
        editor.editingFinished.connect(
            lambda path=parameter.path, control=editor: self._commit_value(path, control.text())
        )
        return editor

    def _commit_value(self, path: tuple[str, ...], value: str) -> None:
        if self._model is None:
            return
        try:
            updated = self._model.set_value(path, value)
        except ValueError as exc:
            self.validation_changed.emit(False, str(exc))
            return
        self._set_source_text(updated, emit=True)
        self.validation_changed.emit(True, "Config.toml 语法有效")

    @staticmethod
    def _toml_literal(value: object) -> str:
        rendered = tomlkit.dumps({"value": value}).strip()
        return rendered.split("=", 1)[1].strip()
