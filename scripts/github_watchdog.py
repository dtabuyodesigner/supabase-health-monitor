"""Detect a missing daily cloud run and request it using a repository-only key."""
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

REPOSITORY = "dtabuyodesigner/supabase-health-monitor"
WORKFLOW = "health.yml"


def instant(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def decide(runs, now, previous=None):
    due = now.replace(hour=9, minute=17, second=0, microsecond=0)
    if now < due:
        return "not_due"
    for run in runs:
        created = instant(run["created_at"])
        if created >= due and run["status"] == "completed" and run.get("conclusion") == "success":
            return "healthy"
    for run in runs:
        created = instant(run["created_at"])
        if created >= due and run["status"] != "completed" and now - created < dt.timedelta(minutes=15):
            return "running"
    if previous and previous.get("action") in ("dispatched", "awaiting_dispatch"):
        requested = instant(previous.get("last_request_at", previous["checked_at"]))
        if now - requested < dt.timedelta(minutes=15):
            return "awaiting_dispatch"
    return "dispatch"


def read_runs():
    url = f"https://api.github.com/repos/{REPOSITORY}/actions/workflows/{WORKFLOW}/runs?per_page=30"
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                 "User-Agent": "SupabaseMonitorWatchdog/1.0"})
    with urllib.request.urlopen(request, timeout=25) as response:
        data = json.loads(response.read(1024 * 1024))
    if not isinstance(data, dict) or not isinstance(data.get("workflow_runs"), list):
        raise ValueError("Invalid GitHub API response")
    return data["workflow_runs"]


def git_call(arguments, directory, environment):
    return subprocess.run(["/usr/bin/git", *arguments], cwd=directory, env=environment,
                          capture_output=True, text=True, timeout=60, check=True).stdout.strip()


def request_run(base, now):
    private = Path.home() / ".config/supabase-health-monitor"
    key = private / "github-dispatch-key"
    hosts = private / "github-known-hosts"
    if not key.is_file() or not hosts.is_file() or key.stat().st_mode & 0o077:
        raise ValueError("Missing or unsafe repository-only SSH key")
    ssh = ["/usr/bin/ssh", "-i", str(key), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
           "-o", "StrictHostKeyChecking=yes", "-o", "UserKnownHostsFile=" + str(hosts)]
    environment = {**os.environ, "GIT_SSH_COMMAND": shlex.join(ssh), "GIT_TERMINAL_PROMPT": "0"}
    repo = base / "repo"
    origin = f"git@github.com:{REPOSITORY}.git"
    if not repo.exists():
        git_call(["clone", "--depth=1", "--no-tags", origin, str(repo)], base, environment)
    if git_call(["remote", "get-url", "origin"], repo, environment) != origin:
        raise ValueError("Unexpected Git repository")
    git_call(["fetch", "--depth=1", "origin", "main"], repo, environment)
    git_call(["reset", "--hard", "FETCH_HEAD"], repo, environment)
    request = repo / "dispatch/request.json"
    request.parent.mkdir(exist_ok=True)
    request.write_text(json.dumps({"requested_at": now.isoformat(),
                                   "source": "nas-watchdog", "reason": "missing-daily-cloud-success"}, sort_keys=True) + "\n")
    git_call(["config", "user.name", "supabase-monitor-bot"], repo, environment)
    git_call(["config", "user.email", "supabase-monitor-bot@users.noreply.github.com"], repo, environment)
    git_call(["add", "--", "dispatch/request.json"], repo, environment)
    git_call(["-c", "core.hooksPath=/dev/null", "commit", "-m", "chore: request missing daily cloud availability check"], repo, environment)
    git_call(["push", "origin", "HEAD:main"], repo, environment)
    return git_call(["rev-parse", "HEAD"], repo, environment)


def save(path, status):
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(status, stream, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    os.umask(0o077)
    base = Path.home() / ".local/share/supabase-health-monitor/github-dispatch"
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    status_file = base / "status.json"
    now = dt.datetime.now(dt.timezone.utc)
    with (base / "watchdog.lock").open("a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        previous = json.loads(status_file.read_text()) if status_file.exists() else {}
        status = {"checked_at": now.isoformat()}
        try:
            runs = read_runs()
            decision = decide(runs, now, previous)
            status.update(ok=True, action=decision)
            if decision == "dispatch":
                status.update(action="dispatched", request_sha=request_run(base, now), last_request_at=now.isoformat())
            elif decision == "awaiting_dispatch":
                status["last_request_at"] = previous.get("last_request_at", previous["checked_at"])
                status["request_sha"] = previous.get("request_sha")
            elif decision == "healthy":
                due = now.replace(hour=9, minute=17, second=0, microsecond=0)
                status["successful_run_id"] = next(r["id"] for r in runs if instant(r["created_at"]) >= due and r.get("conclusion") == "success")
        except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError, subprocess.SubprocessError) as error:
            status.update(ok=False, action="error", error_type=type(error).__name__)
        save(status_file, status)
        print(json.dumps(status, sort_keys=True))
        return 0 if status["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
