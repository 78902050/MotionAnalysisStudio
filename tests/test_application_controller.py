import importlib
import importlib.util
import tempfile
import threading
import time
import unittest
from pathlib import Path

from app.project.manager import ProjectManager
from app.tasks.base import TaskRequest


class _Editor:
    def __init__(self, *, dirty: bool, save_result: bool = True) -> None:
        self.dirty = dirty
        self.save_result = save_result
        self.save_calls = 0
        self.discard_calls = 0

    def dirty_state(self):
        from app.application.dirty_state import DirtyState

        return DirtyState(self.dirty, "二维修正")

    def save(self) -> bool:
        self.save_calls += 1
        if self.save_result:
            self.dirty = False
        return self.save_result

    def discard_unsaved(self) -> None:
        self.discard_calls += 1
        self.dirty = False


class _Resource:
    def __init__(self, *, close_result: bool = True) -> None:
        self.close_calls = 0
        self.close_result = close_result

    def close(self) -> bool:
        self.close_calls += 1
        return self.close_result


class ApplicationControllerTests(unittest.TestCase):
    def _controller_type(self):
        module_name = "app.application.controller"
        self.assertIsNotNone(
            importlib.util.find_spec(module_name),
            "ApplicationController is not implemented",
        )
        return importlib.import_module(module_name).ApplicationController

    def test_failed_save_prevents_project_switch(self) -> None:
        controller = self._controller_type()()
        editor = _Editor(dirty=True, save_result=False)
        with tempfile.TemporaryDirectory() as directory:
            first = ProjectManager.create(Path(directory) / "first", "first")
            second = ProjectManager.create(Path(directory) / "second", "second")
            self.assertTrue(controller.open_project(first))
            controller.register_editor("correction", editor)

            switched = controller.open_project(second, dirty_decision="save")

            self.assertFalse(switched)
            self.assertIs(controller.current_project, first)
            self.assertEqual(editor.save_calls, 1)

    def test_project_switch_cancels_tasks_releases_resources_then_updates_generation(self) -> None:
        controller = self._controller_type()()
        resource = _Resource()
        controller.register_resource(resource)
        started = threading.Event()

        def work(token):
            started.set()
            while not token.is_cancelled:
                time.sleep(0.01)
            return "stopped"

        with tempfile.TemporaryDirectory() as directory:
            first = ProjectManager.create(Path(directory) / "first", "first")
            second = ProjectManager.create(Path(directory) / "second", "second")
            self.assertTrue(controller.open_project(first))
            first_generation = controller.generation
            handle = controller.start_task(
                TaskRequest(
                    str(first.manifest["project_id"]),
                    first_generation,
                    "long",
                    {},
                ),
                work,
            )
            self.assertTrue(started.wait(1))

            self.assertTrue(controller.open_project(second, dirty_decision="discard"))

            self.assertEqual(handle.wait(2).status, "cancelled")
            self.assertEqual(resource.close_calls, 1)
            self.assertIs(controller.current_project, second)
            self.assertGreater(controller.generation, first_generation)
            self.assertTrue(controller.supervisor.wait_for_shutdown(1000))

    def test_resource_failure_still_attempts_to_release_remaining_resources(self) -> None:
        controller = self._controller_type()()
        failed = _Resource(close_result=False)
        remaining = _Resource()
        controller.register_resource(failed)
        controller.register_resource(remaining)

        self.assertFalse(controller.shutdown(dirty_decision="discard"))

        self.assertEqual(failed.close_calls, 1)
        self.assertEqual(remaining.close_calls, 1)
        self.assertIn("资源", controller.last_error)

    def test_cancelled_shutdown_preserves_dirty_editor_state(self) -> None:
        controller = self._controller_type()()
        editor = _Editor(dirty=True)
        controller.register_editor("correction", editor)

        self.assertFalse(controller.shutdown(dirty_decision="cancel"))

        self.assertTrue(editor.dirty)
        self.assertEqual(editor.save_calls, 0)
        self.assertEqual(editor.discard_calls, 0)


if __name__ == "__main__":
    unittest.main()
