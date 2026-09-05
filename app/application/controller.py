"""Coordinate project changes, dirty editors, tasks, and resource shutdown."""

from __future__ import annotations

from collections.abc import Callable

from app.project.manager import ProjectManager
from app.tasks.base import CancellationToken, TaskRequest
from app.tasks.handle import TaskHandle
from app.tasks.supervisor import TaskSupervisor

from .dirty_state import ClosableResource, DirtyEditor, DirtyState


class ApplicationController:
    def __init__(self) -> None:
        self.current_project: ProjectManager | None = None
        self.generation = 0
        self.supervisor = TaskSupervisor()
        self.last_error = ""
        self._editors: dict[str, DirtyEditor] = {}
        self._resources: list[ClosableResource] = []
        self._task_listeners: list[Callable[[TaskHandle], None]] = []

    def register_editor(self, name: str, editor: DirtyEditor) -> None:
        if not name.strip():
            raise ValueError("editor name must not be empty")
        self._editors[name] = editor

    def register_resource(self, resource: ClosableResource) -> None:
        if resource not in self._resources:
            self._resources.append(resource)

    def add_task_listener(self, listener: Callable[[TaskHandle], None]) -> None:
        if listener not in self._task_listeners:
            self._task_listeners.append(listener)

    def dirty_states(self) -> tuple[DirtyState, ...]:
        return tuple(
            state
            for editor in self._editors.values()
            if (state := editor.dirty_state()).dirty
        )

    def start_task(
        self,
        request: TaskRequest,
        work: Callable[[CancellationToken], object],
    ) -> TaskHandle:
        project = self.current_project
        if project is None:
            raise RuntimeError("no project is open")
        if request.project_id != str(project.manifest["project_id"]):
            raise ValueError("task project does not match the current project")
        if request.generation != self.generation:
            raise ValueError("task generation does not match the current project generation")
        handle = self.supervisor.start(request, work)
        for listener in tuple(self._task_listeners):
            listener(handle)
        return handle

    def open_project(
        self,
        project: ProjectManager,
        *,
        dirty_decision: str = "cancel",
        shutdown_timeout_ms: int = 5000,
    ) -> bool:
        self.last_error = ""
        if self.current_project is project:
            return True
        if not self._resolve_dirty(dirty_decision):
            return False
        if self.current_project is not None:
            self.supervisor.cancel_all()
            if not self.supervisor.wait_for_shutdown(shutdown_timeout_ms):
                self.last_error = "后台任务未能在期限内停止"
                return False
            if not self._close_resources("项目资源未能完整释放"):
                return False
        self.current_project = project
        self.generation += 1
        return True

    def shutdown(self, *, dirty_decision: str = "cancel", timeout_ms: int = 5000) -> bool:
        self.last_error = ""
        if not self._resolve_dirty(dirty_decision):
            return False
        self.supervisor.cancel_all()
        if not self.supervisor.wait_for_shutdown(timeout_ms):
            self.last_error = "后台任务未能在期限内停止"
            return False
        return self._close_resources("应用资源未能完整释放")

    def _close_resources(self, error_message: str) -> bool:
        closed = True
        for resource in self._resources:
            try:
                resource_closed = resource.close()
            except Exception:
                resource_closed = False
            if not resource_closed:
                closed = False
        if not closed:
            self.last_error = error_message
        return closed

    def _resolve_dirty(self, decision: str) -> bool:
        dirty = [editor for editor in self._editors.values() if editor.dirty_state().dirty]
        if not dirty:
            return True
        if decision == "cancel":
            return False
        if decision == "discard":
            for editor in dirty:
                editor.discard_unsaved()
            return True
        if decision != "save":
            raise ValueError(f"unknown dirty decision: {decision}")
        for editor in dirty:
            try:
                if not editor.save():
                    self.last_error = "保存未完成"
                    return False
            except Exception as exc:
                self.last_error = f"保存失败：{exc}"
                return False
        return True
