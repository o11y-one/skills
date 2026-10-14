---
title: Repos that already have telemetry, and re-runs
impact: CRITICAL
tags: [existing-otel, vendor-sdk, idempotency, re-run, patch-in-place]
---

# Repos that already have telemetry, and re-runs

Run these checks for every service, before step 2.
Two SDKs that both patch the same libraries double the spans or break each other.
Replacing what a team already relies on breaks their dashboards.
So extend what is there, and never remove or replace it.

## What to look for

| Marker | What it is |
| --- | --- |
| `@opentelemetry/sdk-node`, `@opentelemetry/sdk-trace-node` or `@vercel/otel` in `package.json` | OpenTelemetry, Node.js |
| `opentelemetry-sdk` or `opentelemetry-distro` among the Python dependencies, or `opentelemetry-instrument` in a start command | OpenTelemetry, Python |
| `go.opentelemetry.io/otel/sdk` in `go.mod` | OpenTelemetry, Go |
| An `opentelemetry-javaagent` jar, a `-javaagent` flag pointing at it, or `io.opentelemetry` dependencies | OpenTelemetry, Java |
| `OTEL_*` variables in `.env*` files, compose files, a `Dockerfile` or deploy config | OpenTelemetry settings |
| `NODE_OPTIONS` with `--require` or `--import`, or `JAVA_TOOL_OPTIONS` or `-javaagent` with another jar | A preloaded agent: read what it loads |
| `dd-trace`, `ddtrace`, `dd-java-agent` or `dd-trace-go` | Datadog |
| `newrelic`, `newrelic.jar` or `github.com/newrelic/go-agent` | New Relic |
| `elastic-apm-node`, `elastic-apm` or `elastic-apm-agent` | Elastic APM |
| `@sentry/node` version 8 or later | Sentry, built on OpenTelemetry |
| Python `sentry-sdk` with tracing on | Sentry |
| `@traceloop/node-server-sdk`, `traceloop-sdk` or `langfuse` | LLM tracing SDKs |
| `LANGSMITH_TRACING` or `LANGCHAIN_TRACING_V2` set | LangSmith tracing |

## What to do

Take the first row that matches.

| Found | Do |
| --- | --- |
| OpenTelemetry that already exports to `otlp_http_endpoint` from `get_ingest_config.v1`: `OTEL_EXPORTER_OTLP_ENDPOINT`, or an exporter `url` or `endpoint` in code, starts with it. This skill ran here before | Go to [Re-runs](#re-runs). |
| An OpenTelemetry SDK with no destination configured: no `OTEL_EXPORTER_OTLP_*ENDPOINT` anywhere, and no `url` or `endpoint` passed to an exporter in code | Patch in place. Keep the existing setup file and how it loads, and skip the guide's `files` and `start_command`. Add only the key (step 3) and the env lines (step 4), then verify. |
| An OpenTelemetry SDK that already exports somewhere, to another backend or a Collector | Stop for this service. Tell the user where it sends today, and that this skill doesn't redirect existing telemetry. They can ask you to switch it, or add o11y.one as an exporter in their Collector. |
| `@sentry/node` version 8 or later | Stop for this service, and tell the user why: it registers its own OpenTelemetry provider, and a second provider conflicts with it. |
| LangSmith tracing only | It works through callbacks and runs alongside. Leave it on and carry on. |
| Datadog, New Relic, Elastic APM, Python Sentry, or an LLM tracing SDK | Ask the user whether to add o11y.one alongside it, so both run, or stop. Never remove it. If they choose alongside, keep the vendor's preload or agent flag where it is, and add ours after it. |

If verify finds no spans after a patch in place, compare the existing setup with the guide's `files`. Propose the missing piece, often the instrumentations list, to the user before you edit.

## Re-runs

Running the skill again must change nothing that is already right.
For each service, check in order, and skip each step that is already done:

1. The key: `.env` or the secret manager has `OTEL_EXPORTER_OTLP_HEADERS` with the `auth_header` name, and its value is not the `<ingestion key>` placeholder. Never create another key.
2. The env lines: `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_EXPORTER_OTLP_PROTOCOL` match `get_ingest_config.v1`, and the guide's `env` lines that carry no `<placeholder>` are there. Fix a line that differs, and say so.
3. The packages: each guide package is in the manifest. The Java agent is the exception, because it is never a manifest dependency: check instead that its jar is at the path its `manager_hint` names. Install only the missing ones, and leave a newer version alone.
4. The setup files: each guide file exists at its `path_hint` and loads as its `load` says. Never add a second import, a second flag or a second copy.
5. The start commands: each already contains `start_command.after`.

When all five hold, go straight to verify. A guide `env` line with a `<placeholder>`, such as the key, commit or environment line, never counts as missing or different.
