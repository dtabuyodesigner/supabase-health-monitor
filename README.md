# Read-only database availability monitor

This repository runs minimal health checks against configured Supabase Postgres RPCs.
The same Python script can run independently in GitHub Actions and on a NAS.
It makes three GET requests per project per run, accepts only HTTP 200 with the JSON value
`true`, and exits with a nonzero status on any failed check. A failed project
does not stop the remaining projects from being checked.

It never queries application tables, downloads personal data, authenticates as a
person, or uses a database password or service-role key. Configuration values are
not included in this public repository or its logs.

## Cloud schedule

- GitHub-hosted standard Ubuntu runner: daily at **09:17 UTC**.
- Manual runs: Actions → Read-only database availability → Run workflow.
- Repository Actions secret: `SUPABASE_PROJECTS_JSON`.
- The JSON object contains a non-empty `projects` list, with unique neutral
  identifiers `project-01`, `project-02`, and so on. Each entry provides `id`,
  `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY`.
- Actual project names, URLs and keys remain in private configuration. No
  application-specific project name is used in public logs or reports.
- The key must be a matching legacy `anon` key or a publishable key.
- No artifacts, cache, paid runner, or paid Supabase upgrade is configured.

Standard GitHub-hosted runners in a public repository are free under the
[current GitHub billing rules](https://docs.github.com/en/billing/concepts/product-billing/github-actions).
GitHub can delay scheduled runs; the script's timeout and the job's five-minute
limit bound each run.

GitHub may disable schedules in public repositories after 60 days without
repository activity. The workflow records one genuine monthly health result
under `reports/`, using its repository-scoped ephemeral token. A coverage change
also updates the report. Public reports contain only time, overall result and
project count. This keeps an
operational history and supplies repository activity. No target URL, key, private
table data, or user identity is written to those reports. If there are no
successful runs for two months, review and re-enable the workflow from Actions.

GitHub's notification preferences determine whether failed Actions runs send a
notification. A failed run is visible in Actions; this setup does not configure a
separate email, Telegram, or SMS service.

## Automatic recovery when GitHub omits a scheduled event

The native daily schedule remains configured. An independent NAS watchdog runs
at **09:47 and 13:47 UTC** and checks GitHub's public run metadata. If no cloud
run has succeeded since that day's scheduled time, it requests a run by pushing
only `dispatch/request.json` to this dedicated repository. The workflow listens
for that path on `main`; monthly reports and unrelated commits do not trigger it.

The watchdog skips a current successful run, a recent running job, and a request
that is still being registered. API observation errors are failures, not evidence
that the schedule was missed. A lock prevents concurrent local requests.

The NAS uses an SSH deploy key restricted to **this repository**, with host keys
pinned from GitHub's official metadata. Its private key never leaves the NAS.
There is no GitHub account token or Supabase administrator credential on the NAS.
The key is writable so it can submit the one request file; it does not grant
access to other repositories. `scripts/github_watchdog.py` contains the code.

The automatic chain was verified on 2026-11-06: the NAS cron submitted a request
at 10:19 UTC, GitHub created an event of type `push`, and
[the cloud run completed successfully](https://github.com/dtabuyodesigner/supabase-health-monitor/actions/runs/42201742399).
This was not a manual workflow dispatch. The temporary every-minute proof cron
was removed afterward. A subsequent check detected the successful run and did
not submit another request.

This recovery mechanism requires the NAS to be on and connected. The cloud
runner remains separate from the NAS; the recovery trigger depends on it if
GitHub's own schedule delivery fails. The root cause inside GitHub's schedule
delivery has not been established. GitHub documents that schedule events may be
[delayed or dropped under high load](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

## NAS schedule

Recommended installation for the dedicated operating-system user:

- Script: `$HOME/.local/share/supabase-health-monitor/healthcheck.py`.
- Configuration: `$HOME/.config/supabase-health-monitor/config.json`, mode `0600`.
- Configuration contains the same `projects` JSON object as the cloud secret.
- Latest result: `$HOME/.local/share/supabase-health-monitor/status.json`.
- Cron log: `$HOME/.local/share/supabase-health-monitor/run.log`.
- Schedule: daily at **19:43 UTC**, on a NAS with its system timezone set to UTC.
- Use `flock -n` to prevent overlapping local runs.

The NAS needs power, Internet access, Python 3, and cron. It does not require an
interactive login, a running Codex app, or Tailscale for outbound HTTPS checks.
It does not receive or retain any GitHub administration credential.

Example invocation (configuration values stay outside the command line):

```sh
python3 scripts/healthcheck.py --config /private/path/config.json --status-file /private/path/status.json
```

## Database endpoint

`supabase/monitor_health.sql` defines `public.monitor_health()`: a stable SQL
function using `SECURITY INVOKER`, an empty `search_path`, and only `SELECT true`.
Only the `anon` and `authenticated` roles are explicitly granted execution.
No table permission, RLS policy, authentication setting, row, or storage object
needs to change.

The positive probe verifies that an external request reaches Postgres and
executes the RPC. This is not a complete test of application login, storage,
payment logic, or private user flows.

## Tests

```sh
python3 -m unittest discover -s scripts -p 'test_*.py' -v
```

Tests cover rejection of privileged/mismatched keys, refusal to forward keys
through redirects, HTTP failure handling, private atomic status-file writes,
empty/duplicate project validation, legacy compatibility, and isolation of
failures between projects.
Watchdog tests also cover missing, failed, previous-day, already successful,
recently running, not-yet-due and recently requested cloud runs.

The configuration is an explicit allowlist. A future Supabase project is not
covered automatically: provision its health RPC and add its public key to both
private configurations. No Supabase management token is distributed to either
scheduled job. Paused projects must be restored before the RPC can be provisioned.

## Limits and removal

[Supabase's pausing policy](https://supabase.com/docs/guides/platform/free-project-pausing)
states that a few database requests per day are typically sufficient; it does not
guarantee that a particular health check will prevent pausing. These jobs are
best-effort availability monitoring and read activity. They do not automatically
resume a paused project or change its billing plan.

To stop: disable the GitHub workflow, remove only the marked NAS cron blocks
`supabase-health-monitor` and `supabase-github-watchdog`, and optionally remove
the dedicated NAS files. Keep all unrelated cron entries. Revoke the deploy key
named `NAS availability dispatch only` in this repository's deploy-key settings
and remove its private file from the NAS when retiring the watchdog.
Remove the GitHub Actions configuration secret if retiring the monitor. Once both jobs
are disabled, the database endpoint can be removed with:

```sql
DROP FUNCTION public.monitor_health();
NOTIFY pgrst, 'reload schema';
```
