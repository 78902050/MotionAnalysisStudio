import importlib
import importlib.util
import os
import threading
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.gui.task_center import TaskStatusStrip
from app.tasks.base import TaskRequest


class TaskSupervisorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def _supervisor_type(self):
        module_name = "app.tasks.supervisor"
        self.assertIsNotNone(
            importlib.util.find_spec(module_name),
            "TaskSupervisor with immediate handles is not implemented",
        )
        return importlib.import_module(module_name).TaskSupervisor

    def test_start_returns_immediate_cancellable_handle(self) -> None:
        supervisor_type = self._supervisor_type()
        supervisor = supervisor_type()
        started = threading.Event()

        def work(token):
            started.set()
            while not token.is_cancelled:
                time.sleep(0.01)
            return "stopped"

        before = time.monotonic()
        handle = supervisor.start(TaskRequest("project-a", 3, "long", {}), work)
        elapsed = time.monotonic() - before

        self.assertLess(elapsed, 0.25)
        self.assertTrue(started.wait(1))
        self.assertEqual(handle.project_id, "project-a")
        self.assertEqual(handle.generation, 3)
        handle.cancel()
        result = handle.wait(2)
        self.assertEqual(result.status, "cancelled")
        self.assertTrue(supervisor.wait_for_shutdown(1000))

    def test_status_strip_cancels_bound_handle_without_blocking_gui(self) -> None:
        supervisor_type = self._supervisor_type()
        supervisor = supervisor_type()
        started = threading.Event()

        def work(token):
            started.set()
            while not token.is_cancelled:
                time.sleep(0.01)
            return "stopped"

        handle = supervisor.start(TaskRequest("project-a", 3, "长任务", {}), work)
        self.addCleanup(supervisor.wait_for_shutdown, 1000)
        self.addCleanup(handle.cancel)
        self.assertTrue(started.wait(1))
        strip = TaskStatusStrip()

        strip.set_handle(handle)
        self.assertTrue(strip.cancel_button.isEnabled())
        self.assertIn("长任务", strip.label.text())

        strip.cancel_button.click()
        result = handle.wait(2)
        strip.refresh_status()

        self.assertEqual(result.status, "cancelled")
        self.assertFalse(strip.cancel_button.isEnabled())
        self.assertIn("已取消", strip.label.text())
        self.assertTrue(supervisor.wait_for_shutdown(1000))

    def test_read_only_snapshot_tracks_cancellation_lifecycle(self) -> None:
        supervisor_type = self._supervisor_type()
        supervisor = supervisor_type()
        started = threading.Event()
        release = threading.Event()

        def work(token):
            started.set()
            release.wait(2)
            return "finished"

        handle = supervisor.start(TaskRequest("project-a", 4, "跟踪任务", {}), work)
        self.addCleanup(supervisor.wait_for_shutdown, 1000)
        self.addCleanup(release.set)
        self.addCleanup(handle.cancel)
        self.assertTrue(started.wait(1))

        running = supervisor.snapshot(handle.task_id)
        self.assertEqual(running.status, "running")
        self.assertEqual(running.project_id, "project-a")
        self.assertEqual(running.generation, 4)

        handle.cancel()
        self.assertEqual(supervisor.snapshot(handle.task_id).status, "cancelling")
        release.set()
        self.assertEqual(handle.wait(2).status, "cancelled")
        self.assertEqual(supervisor.snapshot(handle.task_id).status, "cancelled")

    def test_snapshots_returns_task_list_for_task_page(self) -> None:
        supervisor_type = self._supervisor_type()
        supervisor = supervisor_type()
        release = threading.Event()

        def work(token):
            release.wait(2)
            return "finished"

        handle = supervisor.start(TaskRequest("project-a", 5, "列表任务", {}), work)
        self.addCleanup(supervisor.wait_for_shutdown, 1000)
        self.addCleanup(release.set)
        self.addCleanup(handle.cancel)

        snapshots = supervisor.snapshots()

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].task_id, handle.task_id)
        self.assertEqual(snapshots[0].name, "列表任务")


if __name__ == "__main__":
    unittest.main()
