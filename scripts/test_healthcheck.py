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


if __name__ == "__main__":
    unittest.main()
