---
name: o11y-one-setup
description: Connect a repo to o11y.one so its services and AI agents send OpenTelemetry traces, logs and metrics. Use when the user asks to set up o11y.one, connect an app, service or agent to o11y.one, add OpenTelemetry, or send traces, logs or metrics to o11y.one. Detects each service's stack, installs the SDK from the o11y.one MCP recipe, creates an ingestion key in a gitignored .env, and confirms the first trace arrived. Not for dashboards, alerts, SLOs, querying or investigating telemetry that already arrives, or sending telemetry to another vendor.
license: Apache-2.0
compatibility: Needs the o11y-one MCP server added and signed in, a shell that can install packages and run the app, and network access to the repo's package registries.
metadata:
  author: o11y.one
  version: "1.0.0"
  repository: https://github.com/o11y-one/skills
---

# Set up o11y.one in this repo

Connect every service in this repo to o11y.one, and prove it with that service's own first trace.
Work through the steps in order; each one links the reference that holds the detail.
The endpoint, protocol, auth header, packages, versions and setup-file contents come from the o11y-one MCP tools while you work.
Never write any of them from memory.

This skill only connects a repo.
For dashboards, alerts, SLOs, querying telemetry that already arrives, or sending telemetry to another vendor, say this skill doesn't apply and stop.

## Before you start

- Check your tool list for the o11y-one tools `get_ingest_config.v1`, `get_instrumentation_guide.v1`, `create_ingestion_token.v1` and `get_onboarding_status.v1`. Your client may prefix them with the server name or replace the dot, as in `mcp__o11y-one__get_ingest_config_v1`.
- No o11y-one server at all: stop, and give the user the command for their client. Claude Code: `claude mcp add --transport http o11y-one https://mcp.o11y.one/mcp`, then `/mcp` to sign in. Cursor: an `"o11y-one": { "url": "https://mcp.o11y.one/mcp" }` entry under `mcpServers` in `.cursor/mcp.json`, then sign in from its MCP settings. Codex: `codex mcp add o11y-one --url https://mcp.o11y.one/mcp`, then `codex mcp login o11y-one`.
- The server is there but these tools are missing, or a call comes back with `oauth token does not grant permission`: the sign-in predates them. Ask the user to sign in again (`/mcp` in Claude Code, `codex mcp login o11y-one` in Codex, the server's sign-in in Cursor's MCP settings), then retry once. See [troubleshooting](references/troubleshooting.md#mcp-tools-missing-or-not-allowed).
- Only `create_ingestion_token.v1` is missing: carry on; step 3 covers it.
- Call `get_ingest_config.v1` and keep its answer (`otlp_http_endpoint`, `otlp_grpc_endpoint`, `default_protocol`, `auth_header`, `env`) for steps 3, 4 and 6.
- The app must be able to run here, so the first trace can be checked before you finish. If it can't (its runtime is missing, or it needs services you can't start), do steps 1 to 5 and tell the user how to do step 6.

## 1. Detect the stack

- Find each service with its language, framework, agent framework, module type, entrypoint, start commands and package manager, using [detect](references/detect.md).
- Name each service with the ordered lookup in [service-identity](references/service-identity.md): after the service, not the repo.
- If the repo holds more than one service, also follow [monorepo](references/monorepo.md).
- Look for telemetry that is already there: an OpenTelemetry SDK, `NODE_OPTIONS` with `--require` or `--import`, a `-javaagent` flag, or another vendor's SDK. If you find any, follow [partial-instrumentation](references/partial-instrumentation.md) and extend what is there instead of adding a second SDK.
- If this skill ran here before, only the missing steps remain; see [re-runs](references/partial-instrumentation.md#re-runs). A complete earlier run goes straight to step 6.
- Show the user one line per service (directory, language, framework, agent framework, `service.name`) before you change anything.

## 2. Get the recipe

- For each service, call `get_instrumentation_guide.v1` with `language`, `framework`, `service_name` and `service_namespace`, plus `agent_framework` and `module_type` when they apply, all from step 1.
- The answer lists `packages`, `files` (each with a `path_hint` and a `load` value), an optional `start_command`, `env` lines, and `lockfile_refresh` and `verify` commands. Apply exactly that, and add nothing it doesn't list.
- If the answer has `unsupported`, tell the user its reason and never invent a package. For an agent framework, offer the manual route in [agents](references/agents.md); otherwise skip that service.
- For an agent framework, read [agents](references/agents.md) before step 4.

## 3. Create the key

- If the service's `.env` or the repo's secret manager already holds `OTEL_EXPORTER_OTLP_HEADERS` with the `auth_header` name, reuse it. Never create a second key on a re-run.
- Otherwise call `create_ingestion_token.v1` with `name` set to `<repo>-<service>`, where `<repo>` is the repo name from the `origin` remote, or else the repo directory name. For several services, create one key named `<repo>` and use it for all of them.
- Write the returned `env_line` only to a gitignored `.env`, or to the secret manager the repo already uses, following [keys-and-secrets](references/keys-and-secrets.md). Never print the key in full.
- If the tool is missing or refuses (`not_owner_or_admin`, `no_user_on_session`, `hourly_limit_reached`, or a permission error), do not stop. Follow [members without key rights](references/keys-and-secrets.md#members-without-key-rights) and finish the other steps.

## 4. Apply the change

- Install the guide's `packages` at the versions it gives, with the package manager the repo already uses, so the manifest and the lockfile change together.
- Write each of the guide's `files` at its `path_hint`, relative to the service directory, and load it as its `load` value says (step 5). A `path_hint` that names an existing file means insert into it, never overwrite it.
- If there is a `start_command`, replace every start command that matches `before_hint` with `after`.
- Add `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_EXPORTER_OTLP_PROTOCOL` from the `env` map of `get_ingest_config.v1`, and the guide's `env` lines, to the `.env` that holds the key. Skip a line that is already there. Never write a `<placeholder>` value, except on the member path.
- Run the guide's `lockfile_refresh` commands for this package manager, then its `verify` commands. Both must pass before step 6.
- Guide-directed edits count as setup: the guide's files, the first-import line, `instrument_app(app)` where the app is built, framework middleware, start-command flags and per-call `experimental_telemetry`, plus manifests, lockfiles, `.env` and `.gitignore`. List each one in your report. Any other edit to app code needs the user's yes first.

## 5. Where it goes

The SDK must start before the app loads what it instruments. [load-order](references/load-order.md) has the pitfalls, and each language file has the detail.

- Node.js: plain JavaScript preloads the guide's `tracing.mjs` with `node --import ./tracing.mjs`, and TypeScript compiled to CommonJS imports `./tracing` first. See [node](references/node.md).
- Next.js: `instrumentation.ts` with `registerOTel` from `@vercel/otel`, at the project root or in `src/`, never in `next.config.*`. See [nextjs](references/nextjs.md).
- Python: the setup module is the entrypoint's first import. FastAPI and Flask instrument the app object where it is created, Django instruments before `get_wsgi_application()`, and forking servers start the SDK after the fork. See [python](references/python.md).
- Go: the setup function runs first in `main()` with a deferred shutdown, and `otelhttp` wraps the outermost handler. See [go](references/go.md).
- Java: `-javaagent` goes before `-jar`, in every place the service starts. See [java](references/java.md).

## 6. Verify

- Call `get_onboarding_status.v1` with `service_name` set to this service's name, and note its three flags. Then record the current UTC time as the start time.
- Start the service with the `.env` values in its environment, and send it one request or run one agent task. See [verify](references/verify.md).
- Poll `get_onboarding_status.v1` with the same `service_name` every 5 seconds, for up to 2 minutes. With `service_name`, `latest_trace` is that service's newest trace, or null; the flags stay org-wide.
- Success is a `latest_trace` whose `ingested_at` is at or after the start time. A flag turning true is not success on its own.
- A `latest_trace` can be up to 14 days old, so one from before the start time is not success: keep polling.
- Then tell the user, per service, the service name, root span, duration and trace id, and every guide-directed edit you made. Stop every process you started.

## 7. If it fails

| What you see | Go to |
| --- | --- |
| The exporter logs 401 or 403 | [401 or 403](references/troubleshooting.md#401-or-403-from-the-exporter) |
| The exporter logs 404 | [404](references/troubleshooting.md#404-from-the-exporter) |
| The app runs but exports nothing | [No spans](references/troubleshooting.md#no-spans-while-the-app-runs) |
| Connection resets, HTTP/2, gRPC or 415 errors from the exporter | [Wrong protocol](references/troubleshooting.md#wrong-protocol) |
| Spans from one process, none under gunicorn, uvicorn workers or another forking server | [Worker processes](references/troubleshooting.md#spans-locally-but-none-under-worker-processes) |
| No trace after 2 minutes, cause unknown | [No trace after 2 minutes](references/troubleshooting.md#no-trace-after-2-minutes) |
| An install, lockfile or build command fails | [Install or build fails](references/troubleshooting.md#install-or-build-fails) |

Work through one entry, retry verify once, and then report what you checked.
Never loop.

## Never

- Commit a key, print it in full, or write it anywhere but a gitignored `.env` or the repo's secret manager.
- Remove or replace telemetry the repo already has.
- Send data anywhere except the endpoint `get_ingest_config.v1` returns.
- Change code outside setup files and start commands without asking.
- Write a package name, version, endpoint or header value from memory.

## References

| File | Read it for |
| --- | --- |
| [detect](references/detect.md) | Services, languages, frameworks, entrypoints, start commands, package managers |
| [service-identity](references/service-identity.md) | The ordered lookup for `service.name`, and `service_namespace` |
| [monorepo](references/monorepo.md) | Several services: one guide call and one verify each, one shared key |
| [partial-instrumentation](references/partial-instrumentation.md) | OpenTelemetry or a vendor SDK already in the repo, and re-runs |
| [keys-and-secrets](references/keys-and-secrets.md) | Creating, storing and masking the key; members without key rights |
| [load-order](references/load-order.md) | The `load` values, and where each runtime goes wrong |
| [node](references/node.md) | Express, Fastify and plain Node.js |
| [nextjs](references/nextjs.md) | Next.js |
| [python](references/python.md) | FastAPI, Flask, Django and Python scripts |
| [go](references/go.md) | net/http, gin and echo |
| [java](references/java.md) | The Java agent and Spring Boot |
| [agents](references/agents.md) | LangChain and LangGraph, OpenAI Agents SDK, Vercel AI SDK, CrewAI, LlamaIndex |
| [verify](references/verify.md) | Starting the app, the first-trace poll, and the report |
| [troubleshooting](references/troubleshooting.md) | Failures by symptom |
