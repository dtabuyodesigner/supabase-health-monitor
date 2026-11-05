# Read-only database availability monitor

This repository runs a minimal health check against a Supabase Postgres RPC.
The same Python script can run independently in GitHub Actions and on a NAS.
It makes three GET requests per run, accepts only HTTP 200 with the JSON value
`true`, and exits with a nonzero status on any failed check.

It never queries application tables, downloads personal data, authenticates as a
person, or uses a database password or service-role key. Configuration values are
not included in this public repository or its logs.

## Cloud schedule

- GitHub-hosted standard Ubuntu runner: daily at **07:17 UTC**.
- Manual runs: Actions → Read-only database availability → Run workflow.
- Repository Actions secrets: `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`.
- The key must be a matching legacy `anon` key or a publishable key.
- No artifacts, cache, paid runner, or paid Supabase upgrade is configured.

Standard GitHub-hosted runners in a public repository are free under the
[current GitHub billing rules](https://docs.github.com/en/billing/concepts/product-billing/github-actions).
GitHub can delay scheduled runs; the script's timeout and the job's three-minute
limit bound each run.

GitHub may disable schedules in public repositories after 60 days without
repository activity. The workflow records one genuine monthly health result
under `reports/`, using its repository-scoped ephemeral token. This keeps an
operational history and supplies repository activity. No target URL, key, private
table data, or user identity is written to those reports. If there are no
successful runs for two months, review and re-enable the workflow from Actions.

GitHub's notification preferences determine whether failed Actions runs send a
notification. A failed run is visible in Actions; this setup does not configure a
separate email, Telegram, or SMS service.

## NAS schedule

Recommended installation for the dedicated operating-system user:

- Script: `$HOME/.local/share/supabase-health-monitor/healthcheck.py`.
- Configuration: `$HOME/.config/supabase-health-monitor/config.json`, mode `0600`.
- Configuration contains the two variables named above as JSON properties.
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
python3 -m unittest discover -s scripts -p test_healthcheck.py -v
```

Tests cover rejection of privileged/mismatched keys, refusal to forward keys
through redirects, HTTP failure handling, and private atomic status-file writes.

## Limits and removal

[Supabase's pausing policy](https://supabase.com/docs/guides/platform/free-project-pausing)
states that a few database requests per day are typically sufficient; it does not
guarantee that a particular health check will prevent pausing. These jobs are
best-effort availability monitoring and read activity. They do not automatically
resume a paused project or change its billing plan.

To stop: disable the GitHub workflow, remove only the marked NAS cron block, and
optionally remove the dedicated NAS files. Keep all unrelated cron entries.
Remove the two GitHub Actions secrets if retiring the monitor. Once both jobs
are disabled, the database endpoint can be removed with:

```sql
DROP FUNCTION public.monitor_health();
NOTIFY pgrst, 'reload schema';
```
