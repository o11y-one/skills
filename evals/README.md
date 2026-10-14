# Evals

`run.py` runs the `o11y-one-setup` skill the way a user would, against small fixture apps.
It decides pass or fail from what actually happened: spans that reached the sink, calls the mock MCP server logged, files on disk, and the agent's own words.
No model grades anything.

## How a scenario runs

1. The fixture is copied to a temp directory and committed to a fresh git repo, so the `.gitignore` and `git status` checks are real.
2. `mock_o11y.py` starts one local HTTP server that is both the o11y-one MCP server (`/mcp`) and an OTLP/HTTP sink (`/v1/traces`, `/v1/logs`, `/v1/metrics`).
   - Its `get_ingest_config.v1` points at the sink.
   - Its `get_onboarding_status.v1` reports what the sink decoded, filtered to one service when the call passes `service_name`.
   - Its `create_ingestion_token.v1` mints `TEST-` keys, and the sink refuses any other key.
3. Claude Code runs headless with `--plugin-dir <repo root> --mcp-config <mock> --strict-mcp-config` and an empty `CLAUDE_CONFIG_DIR`.
   - Only this plugin's skill and Claude Code's built-in skills load, and only the mock server connects. Your own settings, plugins, hooks, memory and login stay out of the run.
   - The prompt is `Set up o11y.one in this repo.`, so the skill has to load from its description, as it does for a user.
   - `--bare` is not used: in Claude Code 2.1.296 it removes the Skill tool, so the skill could load only by slash command.
4. The checks run, and the agent's leftover processes are stopped. Every scenario also fails if the transcript has no Skill tool call for `o11y-one:o11y-one-setup`. The temp directories are deleted on a pass, and kept on a failure.

## Scenarios

Covers names the launch check each scenario automates: a launch-gate run, or one Review Focus case.

| Scenario | Covers | Fixture | Mock mode | Passes when |
| --- | --- | --- | --- | --- |
| `node-express` | Launch gate | `node-express` | owner | A trace from `eval-node-api` arrives, from one key that is only in a gitignored `.env` and never printed |
| `busy-org` | Review Focus: the first trace not arriving within 2 minutes | `node-express` | busy (another service sends a newer trace before every status call, and the org flags are already true) | A trace from `eval-node-api`, confirmed through a status call with `service_name=eval-node-api` |
| `node-ts` | Launch gate | `node-ts` | owner | The same, for `eval-ts-api` (TypeScript compiled to CommonJS) |
| `python-fastapi` | Launch gate | `python-fastapi` | owner | The same, for `eval-py-api` |
| `langchain-agent` | Launch gate | `langchain-agent` | owner | The same, for `eval-lc-agent`: a LangChain chain on a fake chat model, so no provider key is needed |
| `already-instrumented` | Review Focus: a repo that already has OpenTelemetry | `node-otel` | owner | A trace from `eval-node-otel`, and still exactly one `new NodeSDK(` in the repo |
| `member` | Review Focus: a user who is a member | `node-express` | member (no key tool) | OpenTelemetry is installed, `.env` holds the `<ingestion key>` placeholder, and the agent tells the user an owner or admin must create the key |
| `monorepo-3` | Review Focus: a monorepo with 3 services | `monorepo` | owner | Traces from `eval-orders`, `eval-billing` and `eval-notify` with namespace `eval-mono`, all from one key |
| `stale-mcp` | Review Focus: the MCP server not connected, or the OAuth token stale | `node-express` | stale (no tools) | No file changes, and the agent tells the user to sign in again with `/mcp` |
| `no-trace` | Review Focus: the first trace not arriving within 2 minutes | `node-express` | blackhole (a 3-day-old trace that never updates) | The agent polls for 100 to 600 seconds, in at most 60 calls, then stops without printing the key |

## Run

You need:
- `claude`, `node` and `npm`
- Python 3.10 or later, with `venv`
- `git` and `lsof`
- network access to npm and PyPI
- `ANTHROPIC_API_KEY`. The agent runs with an empty config dir, so it has no other login.

The agent runs with permissions bypassed inside the temp directory, and after each run the runner kills whatever listens on the fixture's ports (3000 to 3002, 3101 to 3103 and 8000), so run the evals in CI or a throwaway VM.

```bash
python3 evals/test_mock.py                 # the mock alone: no agent, no key, no network
python3 evals/run.py                       # every scenario
python3 evals/run.py node-express member   # just these
```

Each scenario is one agent run of up to 20 minutes, and it uses model credits.
CI runs the evals only when someone starts the workflow by hand (Actions, CI, Run workflow), and it needs the `ANTHROPIC_API_KEY` repository secret.

## Add a scenario

1. Add a fixture directory under `fixtures/`, with synthetic names: `eval-*` services, `TEST-` tokens and `example.test` addresses.
2. If the mock has no recipe for its language and framework, add one to `recipe()` in `mock_o11y.py`. Give package names only; versions are looked up from npm or PyPI when the mock runs.
3. Add a line to `SCENARIOS` in `run.py`, with the ports the app listens on and its checks.
