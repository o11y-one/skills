---
title: Troubleshooting
impact: HIGH
tags: [troubleshooting, mcp, oauth, 401, 404, protocol, no-spans, workers, first-trace]
---

# Troubleshooting

Each entry gives a symptom, the checks in order, and the fix.
Work through one entry at a time, retry verify once, and then report what you checked.
Never print the key while you debug; print variable names only.

## MCP tools missing or not allowed

Symptom: the o11y-one tools are not in your tool list, or a call fails with `oauth token does not grant permission`.

1. There is no o11y-one server at all: the user hasn't added it. Give them the add command for their client from [Before you start](../SKILL.md#before-you-start), and stop.
2. The server is there but has no tools, or not the onboarding ones: the sign-in is missing, or older than these tools. Ask the user to sign in again, then retry once:
   - Claude Code: run `/mcp`, pick `o11y-one`, and authenticate.
   - Codex: run `codex mcp login o11y-one`.
   - Cursor: sign in to `o11y-one` from its MCP settings.
3. Only `create_ingestion_token.v1` is missing or refused: don't ask for a new sign-in. Follow the member path in [keys-and-secrets](keys-and-secrets.md#members-without-key-rights).

## 401 or 403 from the exporter

Symptom: the app's log shows the exporter getting 401 or 403.

1. `.env` has exactly one `OTEL_EXPORTER_OTLP_HEADERS` line: `grep -c '^OTEL_EXPORTER_OTLP_HEADERS=' .env` prints `1`.
2. The header name in it equals `auth_header` from `get_ingest_config.v1`. `grep -o '^OTEL_EXPORTER_OTLP_HEADERS=[^=]*' .env` prints the variable and the header name, not the key.
3. The value is not the `<ingestion key>` placeholder: `grep -c '<ingestion key>' .env` prints `0`.
4. The process got the variable: in the shell that starts it, `env | grep -o '^OTEL_[A-Z_]*'` lists `OTEL_EXPORTER_OTLP_HEADERS`.
5. The key is not expired or revoked: the `expires_at` returned when it was created is in the future. A key revoked in o11y.one can't be fixed here; take the member path to get a new one.
6. Nothing else overrides the headers: there is no `OTEL_EXPORTER_OTLP_TRACES_HEADERS`, and no `headers` passed to an exporter in code. If you added one that isn't in the guide's file, take it out; otherwise ask.

## 404 from the exporter

Symptom: a 404, or "not found", from the exporter.

1. `OTEL_EXPORTER_OTLP_ENDPOINT` equals `otlp_http_endpoint` from `get_ingest_config.v1`, exactly.
2. It is the base URL. HTTP exporters add `/v1/traces` themselves, so a base that already ends in `/v1/traces` becomes `/v1/traces/v1/traces`.
3. `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` is not set anywhere. When it is set, exporters use it as is, so it must end in `/v1/traces`. Remove it only if this skill added it; otherwise ask.
4. No exporter in code is given its own `url` or `endpoint`. If you added one that isn't in the guide's file, take it out; otherwise ask.
5. Check the route without the key: `curl -s -o /dev/null -w '%{http_code}\n' -X POST -H 'Content-Type: application/x-protobuf' '<otlp_http_endpoint>/v1/traces'`.
   - `401` means the route exists, so the exporter is sending elsewhere. In the shell that starts the app, list the endpoint variables the process got, names only: `env | grep -o '^OTEL_EXPORTER_OTLP[A-Z_]*ENDPOINT'`. Recheck steps 3 and 4 against that list, including any endpoint set in code. If `OTEL_EXPORTER_OTLP_ENDPOINT` is not in it, the process didn't get `.env`.
   - `404` means the endpoint from the tool is wrong for this network. Report it, and don't guess another host.
   - Any other code, such as `000` or `403`: report the code, and don't guess another host.

## Wrong protocol

Symptom: connection resets, HTTP/2 or gRPC errors, `415`, or `UNIMPLEMENTED` from the exporter.

1. `OTEL_EXPORTER_OTLP_PROTOCOL` equals `default_protocol` from `get_ingest_config.v1`, and the endpoint is the one that goes with it: `otlp_http_endpoint` for `http/protobuf`, and `otlp_grpc_endpoint` for `grpc`.
2. The exporter package matches the protocol:
   - Python: `opentelemetry-exporter-otlp-proto-http` for HTTP, `opentelemetry-exporter-otlp-proto-grpc` for gRPC.
   - Go: `otlptracehttp` for HTTP, `otlptracegrpc` for gRPC. Go picks the protocol by package, not by environment variable.
3. Never pair an HTTP endpoint with the gRPC exporter, or the other way round.

## No spans while the app runs

Symptom: the app serves the request, the log shows no exporter errors, and nothing arrives.

1. A request reached the instrumented process: the curl status came back from this app's port, not from another process.
2. The SDK is on: `OTEL_SDK_DISABLED` is not `true`, `OTEL_TRACES_EXPORTER` is not `none`, and `OTEL_TRACES_SAMPLER` is not `always_off`.
3. The SDK starts before the app's libraries load: check the entry for this runtime in [load-order](load-order.md).
4. Turn on the runtime's debug output for one run:
   - Node.js: `OTEL_LOG_LEVEL=debug`, then read the exporter errors it logs. The guide's setup passes its exporter in code, so `OTEL_TRACES_EXPORTER` changes nothing, and spans missing from stdout never mean the SDK is broken.
   - Python under `opentelemetry-instrument`: `OTEL_TRACES_EXPORTER=otlp,console`, which prints each span.
   - Java: `OTEL_JAVAAGENT_DEBUG=true`, which logs each span the agent creates.
   - Printed spans mean export is the problem; see the 401, 404 and protocol entries. Under `opentelemetry-instrument` or the Java agent, no printed spans means the setup didn't load, or saw no request.
5. A short-lived process exits before it flushes.
   - Go needs the deferred shutdown.
   - Python must not end with `os._exit`.
   - A Node.js script that exits on its own sends its last spans only if it awaits the SDK's shutdown first, unless the guide's file already does that.
   - Changing how a program exits is outside the setup edits, so ask the user first.
6. Some setups send nothing by design: Next.js edge routes with a Node-only setup, and Vercel AI SDK calls without `experimental_telemetry`. See [nextjs](nextjs.md) and [agents](agents.md).
7. Nothing arrives only from runs started without `.env` exported, such as the user's own: the app loads `.env` with `dotenv` or `load_dotenv()` after the setup module, so the SDK starts without its config. Verify's run still sends spans, because it exports `.env` in the shell. Don't move the call yourself; offer the fix in [node](node.md#run-it-for-verify) or [python](python.md#run-it-for-verify) in the report.

## Spans locally but none under worker processes

Symptom: one process works, but under gunicorn, `uvicorn --workers` or gunicorn `--preload`, the spans stop, or the workers hang at start.

1. The SDK started in the parent before the fork. Start it in each worker instead, per [load-order](load-order.md#python).
2. For verify, run one worker, so the rest of the setup can be confirmed.
3. Tell the user which production start command needs the change, and ask before you add the hook or change the server.

## No trace after 2 minutes

Symptom: verify polled for 2 minutes, and no `latest_trace` matched.

1. Read the app's log for exporter errors, and follow the 401, 404 or protocol entry that matches.
2. With no errors, follow [No spans while the app runs](#no-spans-while-the-app-runs).
3. Check that every poll passed `service_name`, and that it equals the `OTEL_SERVICE_NAME` the process got: `env | grep '^OTEL_SERVICE_NAME='` prints it, and it is not a secret. A different name, such as one the SDK sets in code, means the trace arrived under that name. Poll once with it, and report the mismatch.
4. If there is still nothing, report what you checked, what you changed, and the next step for the user.
   - Leave the setup in place, and don't undo it.
   - The Connect page in o11y.one also shows when the first trace arrives.

## Install or build fails

1. A version conflict, or a runtime or toolchain that is too old: report the error and the package. Don't change the language version, the toolchain or other dependencies to make it fit. If `go get` already raised the `go` or `toolchain` line, follow [go](go.md#install), which asks the user and undoes it on a no.
2. A frozen-lockfile error (`npm ci`, `pnpm install --frozen-lockfile`): run the guide's `lockfile_refresh`, so the lockfile matches the manifest.
3. A package the registry can't find: never substitute a similar name. Report it, because it means the guide's recipe needs fixing.
4. `next build` fails on an OpenTelemetry package (`Module not found`, or a `require` that can't be resolved): that package belongs in `serverExternalPackages` in `next.config.*`, per [nextjs](nextjs.md#bundling). That edit is outside the setup edits, so ask the user first, and list it in the report.
