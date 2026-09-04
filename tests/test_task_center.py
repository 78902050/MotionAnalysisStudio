import threading
import time
import unittest

from app.tasks.base import TaskRequest
from app.tasks.center import TaskCenter


class TaskCenterTests(unittest.TestCase):
    def test_result_is_accepted_only_for_matching_project_and_generation(self) -> None:
        center = TaskCenter()
        request = TaskRequest("project-a", 4, "quality", {"value": 7})
        task_id = center.start(request, lambda token: request.payload["value"])

        result = center.wait(task_id, timeout=2)

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.value, 7)
        self.assertTrue(center.accepts_result(result, "project-a", 4))
        self.assertFalse(center.accepts_result(result, "project-a", 5))
        self.assertFalse(center.accepts_result(result, "project-b", 4))

    def test_cancel_requests_worker_stop_and_wait_for_shutdown(self) -> None:
        center = TaskCenter()
        started = threading.Event()

        def work(token):
            started.set()
            while not token.is_cancelled:
                time.sleep(0.01)
            return "stopped"

        task_id = center.start(TaskRequest("project-a", 1, "long", {}), work)
        self.assertTrue(started.wait(1))
        center.cancel(task_id)

        result = center.wait(task_id, timeout=2)

        self.assertEqual(result.status, "cancelled")
        self.assertTrue(center.wait_for_shutdown(1000))


if __name__ == "__main__":
    unittest.main()
