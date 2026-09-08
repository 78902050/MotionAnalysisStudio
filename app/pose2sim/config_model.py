"""Comment-preserving structured edits for Pose2Sim TOML configuration."""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass

import tomlkit
from tomlkit.container import Container
from tomlkit.items import AoT, Array, InlineTable, Item, String, Table


_KEY = re.compile(r"[A-Za-z0-9_-]+")


@dataclass(frozen=True)
class ConfigParameter:
    path: tuple[str, ...]
    value: object
    value_type: str
    editable: bool
    custom: bool


class ConfigModel:
    def __init__(
        self,
        document,
        known_paths: Collection[tuple[str, ...]] | None = None,
    ) -> None:
        self._document = document
        self._known_paths = frozenset(known_paths) if known_paths is not None else None

    @classmethod
    def parse(
        cls,
        text: str,
        known_paths: Collection[tuple[str, ...]] | None = None,
    ) -> "ConfigModel":
        try:
            document = tomlkit.parse(text)
        except Exception as exc:
            raise ValueError(f"TOML 解析失败：{exc}") from exc
        return cls(document, known_paths)

    @property
    def parameters(self) -> tuple[ConfigParameter, ...]:
        values: list[ConfigParameter] = []
        self._collect(self._document, (), values)
        return tuple(values)

    def as_text(self) -> str:
        return self._document.as_string()

    def set_value(self, path: tuple[str, ...], toml_value: str) -> str:
        candidate = tomlkit.parse(self.as_text())
        container, key = self._locate(candidate, path)
        old = container[key]
        if not self._editable(old):
            raise ValueError(f"复杂参数只能在 TOML 源码中编辑：{'.'.join(path)}")
        new = self._parse_value(toml_value)
        if isinstance(new, (Table, AoT, InlineTable)):
            raise ValueError("参数值不能是 TOML 表")
        new.trivia.indent = old.trivia.indent
        new.trivia.comment_ws = old.trivia.comment_ws
        new.trivia.comment = old.trivia.comment
        new.trivia.trail = old.trivia.trail
        container[key] = new
        self._document = candidate
        return self.as_text()

    def add_parameter(
        self,
        section: tuple[str, ...],
        key: str,
        toml_value: str,
    ) -> str:
        if not section or any(not _KEY.fullmatch(part) for part in section):
            raise ValueError("TOML 章节名称无效")
        if not _KEY.fullmatch(key):
            raise ValueError("TOML 参数名称无效")
        candidate = tomlkit.parse(self.as_text())
        container: Container = candidate
        for part in section:
            if part not in container:
                container[part] = tomlkit.table()
            item = container[part]
            if not isinstance(item, Table):
                raise ValueError(f"章节路径不是 TOML 表：{'.'.join(section)}")
            container = item
        if key in container:
            raise ValueError(f"参数已存在：{'.'.join((*section, key))}")
        value = self._parse_value(toml_value)
        if isinstance(value, (Table, AoT)):
            raise ValueError("自定义参数值不能是 TOML 表")
        container[key] = value
        self._document = candidate
        return self.as_text()

    def remove_parameter(self, path: tuple[str, ...]) -> str:
        candidate = tomlkit.parse(self.as_text())
        container, key = self._locate(candidate, path)
        del container[key]
        self._document = candidate
        return self.as_text()

    def _collect(
        self,
        container: Container,
        prefix: tuple[str, ...],
        values: list[ConfigParameter],
    ) -> None:
        for key, item in container.items():
            path = (*prefix, str(key))
            if isinstance(item, Table):
                self._collect(item, path, values)
                continue
            value = item.unwrap() if isinstance(item, Item) else item
            values.append(
                ConfigParameter(
                    path=path,
                    value=value,
                    value_type=self._value_type(item, value),
                    editable=self._editable(item),
                    custom=(
                        path not in self._known_paths
                        if self._known_paths is not None
                        else False
                    ),
                )
            )

    @staticmethod
    def _locate(document, path: tuple[str, ...]) -> tuple[Container, str]:
        if len(path) < 2:
            raise KeyError("参数路径必须包含章节和名称")
        container: Container = document
        for part in path[:-1]:
            if part not in container or not isinstance(container[part], Table):
                raise KeyError(".".join(path))
            container = container[part]
        key = path[-1]
        if key not in container:
            raise KeyError(".".join(path))
        return container, key

    @staticmethod
    def _parse_value(text: str) -> Item:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("参数值不能为空")
        try:
            parsed = tomlkit.parse(f"value = {text}\n")
        except Exception as exc:
            raise ValueError(f"TOML 参数值无效：{exc}") from exc
        return parsed["value"]

    @staticmethod
    def _editable(item: object) -> bool:
        if isinstance(item, (Table, AoT, InlineTable)):
            return False
        if isinstance(item, String) and "\n" in item.unwrap():
            return False
        return True

    @staticmethod
    def _value_type(item: object, value: object) -> str:
        if isinstance(item, AoT):
            return "table_array"
        if isinstance(item, InlineTable):
            return "inline_table"
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, int):
            return "int"
        if isinstance(value, float):
            return "float"
        if isinstance(item, Array) or isinstance(value, list):
            return "list"
        if isinstance(value, str):
            return "string"
        return type(value).__name__
