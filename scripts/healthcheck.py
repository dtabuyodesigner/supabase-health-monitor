#!/usr/bin/env python3
"""Check a constant, read-only Postgres RPC. Never read application rows."""
import argparse
import base64
import datetime
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Do not forward an API key to another origin.


def configuration(config_file=None, values=None):
    config = values if values is not None else (
        json.loads(Path(config_file).read_text()) if config_file else os.environ
    )
    url = config.get("SUPABASE_URL", "").rstrip("/")
    key = config.get("SUPABASE_PUBLISHABLE_KEY", "")
    match = re.fullmatch(r"https://([a-z]{20})\.supabase\.co", url)
    if not match or not key:
        raise ValueError("Missing or invalid monitor configuration")
    if key.startswith("eyJ"):
        payload = json.loads(base64.urlsafe_b64decode(key.split(".")[1] + "==="))
        if payload.get("role") != "anon" or payload.get("ref") != match[1]:
            raise ValueError("Only a matching anon key is allowed")
    elif not key.startswith("sb_publishable_"):
        raise ValueError("Only a publishable key is allowed")
    return url, key


def project_configurations(config_file=None):
    if config_file:
        config = json.loads(Path(config_file).read_text())
    elif os.environ.get("SUPABASE_PROJECTS_JSON"):
        config = json.loads(os.environ["SUPABASE_PROJECTS_JSON"])
    else:
        config = dict(os.environ)
    if not isinstance(config, dict):
        raise ValueError("Invalid monitor configuration")
    projects = config.get("projects", [{"id": "project-01", **config}])
    if not isinstance(projects, list) or not 1 <= len(projects) <= 20:
        raise ValueError("Invalid project list")
    seen = set()
    for project in projects:
        if not isinstance(project, dict):
            raise ValueError("Invalid project configuration")
        identifier = project.get("id", "")
        if not isinstance(identifier, str) or not re.fullmatch(r"project-[0-9]{2}", identifier) or identifier in seen:
            raise ValueError("Invalid or repeated project identifier")
        seen.add(identifier)
    return projects


def run_projects(projects):
    results = []
    for project in projects:
        result = {"id": project["id"]}
        try:
            url, key = configuration(values=project)
            result["checks"] = [check(url, key) for _ in range(3)]
            result["ok"] = all(item["ok"] for item in result["checks"])
        except (ValueError, KeyError, IndexError, OSError, TypeError):
            result.update(ok=False, error="invalid_project_configuration")
        results.append(result)
    return results


def check(url, key):
    request = urllib.request.Request(
        url + "/rest/v1/rpc/monitor_health", method="GET",
        headers={"apikey": key, "Accept": "application/json",
                 "Cache-Control": "no-cache", "User-Agent": "ReadOnlyHealthMonitor/1.0"},
    )
    started = time.monotonic()
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=20) as response:
            ok = response.status == 200 and json.loads(response.read(32)) is True
            result = {"ok": ok, "http_status": response.status}
    except urllib.error.HTTPError as error:
        result = {"ok": False, "http_status": error.code}
    except (urllib.error.URLError, OSError, ValueError):
        result = {"ok": False, "error": "connection_or_response_error"}
    result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    return result


def save_status(path, status):
    target = Path(path)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=target.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(status, stream, sort_keys=True)
            stream.write("\n")
        os.replace(temp_path, target)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="Private JSON configuration; otherwise use environment")
    parser.add_argument("--status-file", help="Save the latest result atomically")
    args = parser.parse_args()
    status = {"checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    try:
        projects = project_configurations(args.config)
        status["projects"] = run_projects(projects)
        status["ok"] = all(item["ok"] for item in status["projects"])
    except (ValueError, KeyError, IndexError, OSError, TypeError):
        status.update(ok=False, error="invalid_monitor_configuration")
    if args.status_file:
        save_status(args.status_file, status)
    print(json.dumps(status, sort_keys=True))
    return 0 if status["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
