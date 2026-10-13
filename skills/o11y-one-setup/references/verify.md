---
title: Verify the first trace
impact: CRITICAL
tags: [verify, first-trace, onboarding-status, polling]
---

# Verify the first trace

Setup is done when o11y.one reports a trace that the service you set up sent during this run.
Always pass `service_name` to `get_onboarding_status.v1`: `latest_trace` is then that service's newest trace, or null, while the three flags stay org-wide.
That trace can be up to 14 days old, so match it on time.

## Steps

1. Call `get_onboarding_status.v1` once with `service_name` set to this service's `service.name`, and note `has_sent_traces`, `has_sent_logs` and `has_sent_metrics`.
2. Record the current UTC time as the start time.
3. Start the service in the background, with its `.env` values in the environment and its output going to a log file, for example: `set -a; . ./.env; set +a; <start command> > /tmp/<service>.log 2>&1 &`. Run one process: no reloader and one worker (see the language file).
4. Wait until it listens (its log says so, or the port answers). Then trigger one unit of work:
   - HTTP service: `curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:<port><path>`.
     - Pick `/health`, `/healthz` or `/` when they exist, otherwise the first `GET` route that needs no auth.
     - Any status code counts; a 404 still makes a server span.
   - Worker or script: run one job or one invocation.
   - Agent: run one task; see [agents](agents.md).
5. Poll `get_onboarding_status.v1` with the same `service_name` every 5 seconds, for up to 2 minutes (24 calls).
6. Stop as soon as `latest_trace` is not null and its `ingested_at` is at or after the start time. A flag turning true is not success on its own.
7. Stop the process you started.

A `latest_trace` from before the start time is not success, even when `has_sent_traces` is true. Keep polling.

## Report

For each service, write one sentence:
"o11y.one received a trace from `<service_name>`: root span `<root_span_name>`, `<duration_ms>` ms, trace `<trace_id>`."

Then, once for the whole run, cover:

- What changed: files added, packages added, and each guide-directed edit with its file: the first-import line, `instrument_app(app)` where the app is built, framework middleware, start-command flags, and per-call `experimental_telemetry`.
- That any other edit to app code needed the user's yes, and which ones the user approved.
- Where the key is (a path or a secret manager), masked, and its `expires_at`.
- What the deployed service needs: the variable names, with the key in the platform's secret store.
- For agents: that prompts and completions are captured by default, and the switch to turn that off (see [agents](agents.md)).
- Logs and metrics: whether `has_sent_logs` and `has_sent_metrics` are true. Don't wait for them; traces are the bar.
- If the app doesn't load `.env` on its own, an offer to add that.

## When nothing matches after 2 minutes

Go to [troubleshooting](troubleshooting.md#no-trace-after-2-minutes).
Retry verify once after a fix; then report what you checked, instead of polling again.
