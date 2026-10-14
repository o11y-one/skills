# Evals

`run.py` runs the `o11y-one-setup` skill the way a user would, against small fixture apps.
It decides pass or fail from what actually happened: spans that reached the sink, calls the mock MCP server logged, files on disk, and the agent's own words.
No model grades anything.

## How a scenario runs

1. If another process already listens on one of the fixture's ports, the scenario fails at once and nothing is killed.
2. The fixture is copied to a temp directory and committed to a fresh git repo, so the `.gitignore` and `git status` checks are real.
   A Python fixture (one with `pyproject.toml`) also gets a `.venv`, made with `python3 -m venv`, and the agent runs with it active (`VIRTUAL_ENV` set, its `bin` first on `PATH`). The skill asks before it creates a virtualenv, and under `-p` nobody can answer.
3. `mock_o11y.py` starts one local HTTP server that is both the o11y-one MCP server (`/mcp`) and an OTLP/HTTP sink (`/v1/traces`, `/v1/logs`, `/v1/metrics`) that takes protobuf or JSON, as the real ingest does.
   - Every tool answers in the real server's envelope, with its values under `result`, in `structuredContent` and again as JSON text. A refusal is a JSON-RPC error whose message starts with its code, which `data.code` repeats.
   - Its `get_ingest_config.v1` points at the sink.
   - Its `get_instrumentation_guide.v1` answers as the real server does for the fixtures' stacks, at the versions the real server pins, and `unsupported` for any other stack.
   - Its `get_onboarding_status.v1` reports what the sink decoded, filtered to one service when the call passes `service_name`.
   - Its `create_ingestion_token.v1` mints `TEST-` keys, five at most, and the sink refuses any other key. A sixth is refused with `hourly_limit_reached`.
4. Claude Code runs headless with `--plugin-dir <repo root> --mcp-config <mock> --strict-mcp-config` and an empty `CLAUDE_CONFIG_DIR`.
   - Only this plugin's skill and Claude Code's built-in skills load, and only the mock server connects.
   - Your own Claude Code settings, plugins, hooks and memory stay out of the run, and so does every `OTEL_*` variable. Admin-managed settings still apply, and the rest of your environment, `ANTHROPIC_API_KEY` included, reaches the agent and every command it runs.
   - Each run stops at `--max-budget-usd 5`, or at the value of `EVAL_MAX_BUDGET_USD`.
   - The prompt is `Set up o11y.one in this repo.`, so the skill has to load from its description, as it does for a user.
   - `--bare` is not used: in Claude Code 2.1.296 it removes the Skill tool, so the skill could load only by slash command.
5. The checks run. The agent's process group is stopped, and so is any TCP listener whose working directory is inside the temp directory; nothing else is killed. Every scenario also fails if the transcript has no Skill tool call for `o11y-one:o11y-one-setup`. The temp directories are deleted on a pass, and kept on a failure.

## Scenarios

| Scenario | Fixture | Mock mode | Passes when |
| --- | --- | --- | --- |
| `node-express` | `node-express` | owner | A trace from `eval-node-api` arrives, from one key that is only in a gitignored `.env`, never printed, and never passed to a tool call other than a `.env` write |
| `busy-org` | `node-express` | busy (before every status call, `eval-other-service` sends a newer trace, so `has_sent_traces` is true from the first call) | A trace from `eval-node-api`, confirmed through a status call with `service_name=eval-node-api`, so the other service's newer trace can't stand in for it |
| `node-ts` | `node-ts` | owner | The same, for `eval-ts-api` (TypeScript compiled to CommonJS) |
| `python-fastapi` | `python-fastapi` | owner | The same, for `eval-py-api` |
| `langchain-agent` | `langchain-agent` | owner | The same, for `eval-lc-agent`: a LangChain chain on a fake chat model, so no provider key is needed |
| `already-instrumented` | `node-otel` | owner | A trace from `eval-node-otel`, and still exactly one `new NodeSDK(` in the repo |
| `member` | `node-express` | member (the key tool refuses with `not_owner_or_admin`, as for an owner demoted since sign-in) | OpenTelemetry is installed, `.env` holds the `<ingestion key>` placeholder, and the agent tells the user an owner or admin must create the key |
| `monorepo-3` | `monorepo` | owner | Traces from `eval-orders`, `eval-billing` and `eval-notify` with namespace `eval-mono`, all from one key |
| `stale-mcp` | `node-express` | stale (no tools) | No file changes, and the agent tells the user to sign in again with `/mcp` |
| `no-trace` | `node-express` | blackhole (a 3-day-old trace that never updates) | The agent polls for 100 to 600 seconds, in at most 60 calls, then stops without printing the key |

## Run

You need:
- `claude`, `node` and `npm`
- Python 3.10 or later, with `venv`
- `git` and `lsof`
- network access to npm and PyPI
- `ANTHROPIC_API_KEY`, which the agent signs in with. The agent and every command it runs, the fixture apps included, inherit it.

The agent runs with permissions bypassed, so run the evals in CI or a throwaway VM.
A scenario needs its fixture's ports free (3000 to 3002, 3101 to 3103 and 8000), and fails at once if another process holds one.

```bash
python3 evals/test_mock.py                 # the mock alone: no agent, no key, no network
python3 evals/run.py                       # every scenario
python3 evals/run.py node-express member   # just these
```

Each scenario is one agent run of up to 20 minutes, and it uses model credits: at most $5 a run, or `EVAL_MAX_BUDGET_USD` dollars when that is set.
CI runs the evals only when someone starts the workflow by hand (Actions, CI, Run workflow), and it needs the `ANTHROPIC_API_KEY` repository secret.

## Add a scenario

1. Add a fixture directory under `fixtures/`, with synthetic names: `eval-*` services, `TEST-` tokens and `example.test` addresses.
2. If the mock has no guide for its language and framework, add one to `recipe()` in `mock_o11y.py`: copy what the real `get_instrumentation_guide.v1` answers for it, versions included. The mock never looks a version up. Pin the fixture's own dependencies to exact versions too.
3. Add a line to `SCENARIOS` in `run.py`, with the ports the app listens on and its checks.
