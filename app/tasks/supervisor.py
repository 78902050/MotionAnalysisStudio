"""Primary task API returning cancellable handles immediately."""

from collections.abc import Callable

from .base import CancellationToken, TaskRequest
from .center import TaskCenter
from .handle import TaskHandle


class TaskSupervisor(TaskCenter):
    def start(
        self, request: TaskRequest, work: Callable[[CancellationToken], object]
    ) -> TaskHandle:
        return self.start_handle(request, work)
