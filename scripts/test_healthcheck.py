import base64
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

spec = importlib.util.spec_from_file_location("healthcheck", Path(__file__).with_name("healthcheck.py"))
health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)


class HealthChecks(unittest.TestCase):
    def test_reject_privileged_or_mismatched_key(self):
        for role, ref in [("service_role", "a" * 20), ("anon", "b" * 20)]:
            payload = base64.urlsafe_b64encode(json.dumps({"role": role, "ref": ref}).encode()).decode()
            with patch.dict(os.environ, {"SUPABASE_URL": "https://" + "a" * 20 + ".supabase.co",
                                         "SUPABASE_PUBLISHABLE_KEY": "eyJ." + payload + ".signature"}):
                with self.assertRaises(ValueError):
                    health.configuration()

    def test_redirect_does_not_forward_key(self):
        self.assertIsNone(health.NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.com"))

    def test_http_failure_is_failure_without_body(self):
        error = urllib.error.HTTPError("https://example.com", 503, "failure", {}, None)
        with patch.object(health.urllib.request.OpenerDirector, "open", side_effect=error):
            self.assertEqual(health.check("https://example.com", "test-key")["ok"], False)

    def test_atomic_status_is_private(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "status.json"
            health.save_status(path, {"ok": False})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text()), {"ok": False})

    def test_one_failed_project_does_not_skip_another(self):
        projects = [
            {"id": "project-01", "SUPABASE_URL": "https://" + "a" * 20 + ".supabase.co", "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test"},
            {"id": "project-02", "SUPABASE_URL": "https://" + "b" * 20 + ".supabase.co", "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test"},
        ]
        with patch.object(health, "check", side_effect=[{"ok": False}] * 3 + [{"ok": True}] * 3) as probe:
            results = health.run_projects(projects)
        self.assertFalse(results[0]["ok"])
        self.assertTrue(results[1]["ok"])
        self.assertEqual(probe.call_count, 6)

    def test_bad_project_configuration_does_not_skip_another(self):
        projects = [{"id": "project-01", "SUPABASE_URL": "invalid"},
                    {"id": "project-02", "SUPABASE_URL": "https://" + "b" * 20 + ".supabase.co", "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test"}]
        with patch.object(health, "check", return_value={"ok": True}):
            results = health.run_projects(projects)
        self.assertFalse(results[0]["ok"])
        self.assertTrue(results[1]["ok"])

    def test_reject_empty_or_duplicated_project_list(self):
        for projects in [[], [{"id": "project-01"}, {"id": "project-01"}]]:
            with patch.dict(os.environ, {"SUPABASE_PROJECTS_JSON": json.dumps({"projects": projects})}):
                with self.assertRaises(ValueError):
                    health.project_configurations()

    def test_legacy_single_project_configuration_remains_supported(self):
        with patch.dict(os.environ, {"SUPABASE_URL": "https://" + "a" * 20 + ".supabase.co",
                                     "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test"}, clear=True):
            self.assertEqual(health.project_configurations()[0]["id"], "project-01")


if __name__ == "__main__":
    unittest.main()
