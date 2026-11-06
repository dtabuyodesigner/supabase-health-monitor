import datetime as dt
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("github_watchdog", Path(__file__).with_name("github_watchdog.py"))
watchdog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watchdog)


class DecisionTests(unittest.TestCase):
    now = dt.datetime(2026, 11, 6, 10, 0, tzinfo=dt.timezone.utc)

    def run_record(self, status="completed", conclusion="success", created="2026-11-06T09:20:00Z"):
        return {"id": 123, "status": status, "conclusion": conclusion, "created_at": created}

    def test_recent_success_does_not_dispatch(self):
        self.assertEqual(watchdog.decide([self.run_record()], self.now), "healthy")

    def test_previous_day_success_does_not_hide_missing_run(self):
        self.assertEqual(watchdog.decide([self.run_record(created="2026-11-05T09:20:00Z")], self.now), "dispatch")

    def test_manual_check_before_schedule_does_not_hide_missing_schedule(self):
        self.assertEqual(watchdog.decide([self.run_record(created="2026-11-06T09:12:00Z")], self.now), "dispatch")

    def test_recent_running_job_prevents_duplicate(self):
        run = self.run_record(status="in_progress", conclusion=None, created="2026-11-06T09:55:00Z")
        self.assertEqual(watchdog.decide([run], self.now), "running")

    def test_failed_job_can_be_replaced(self):
        self.assertEqual(watchdog.decide([self.run_record(conclusion="failure")], self.now), "dispatch")

    def test_before_schedule_does_not_dispatch(self):
        now = self.now.replace(hour=8)
        self.assertEqual(watchdog.decide([], now), "not_due")

    def test_recent_push_request_is_not_repeated_while_github_registers_it(self):
        previous = {"action": "dispatched", "checked_at": "2026-11-06T09:59:00+00:00"}
        self.assertEqual(watchdog.decide([], self.now, previous), "awaiting_dispatch")


if __name__ == "__main__":
    unittest.main()
