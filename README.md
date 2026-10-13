# o11y.one skills

[Agent Skills](https://agentskills.io) for [o11y.one](https://o11y.one), packaged as a Claude Code plugin.
The one skill here, `o11y-one-setup`, connects a repo to o11y.one: your coding agent instruments each service and stops when o11y.one has that service's first trace.

## What the skill does

Ask your agent `Set up o11y.one in this repo.` and it will:

1. Find each service, with its language, its framework and any agent framework: LangChain or LangGraph, OpenAI Agents SDK, Vercel AI SDK, CrewAI or LlamaIndex.
2. Look for OpenTelemetry or another vendor's SDK already in the repo, and build on what is there instead of adding a second SDK.
3. Ask the o11y.one MCP server for the recipe: packages and versions, the setup file, where it loads, and the lockfile command.
4. Create an ingestion key through the MCP server and write it to a gitignored `.env`, or to the secret manager the repo already uses. A member without key rights is asked for a key instead, and the rest of the setup still runs.
5. Start the app, send it one request, and wait up to 2 minutes for o11y.one to report the trace, then tell you the service and its root span.

Running it again changes nothing that is already in place.

## What it never does

- Commit a key, or print one in full.
- Remove or replace telemetry the repo already has.
- Send data anywhere except the endpoint the o11y.one MCP server returns.
- Change code outside its setup files and start commands without asking.
- Write a package, version, endpoint or header from memory. They all come from the MCP server each time the skill runs, so the skill tracks latest and an old install doesn't go stale.

## Install

**1. Connect the MCP server.** Claude Code: `claude mcp add --transport http o11y-one https://mcp.o11y.one/mcp`, then `/mcp` to sign in. Cursor: add `"o11y-one": { "url": "https://mcp.o11y.one/mcp" }` under `mcpServers` in `.cursor/mcp.json`, then sign in from Cursor's MCP settings. Codex: `codex mcp add o11y-one --url https://mcp.o11y.one/mcp`, then `codex mcp login o11y-one`. The Claude Code plugin below does this step for you.

**2. Install the skill**, in one of three ways:

- Any agent that reads Agent Skills, including Claude Code, Cursor and Codex:

  ```bash
  npx skills add o11y-one/skills
  ```

- The Claude Code plugin, which adds the MCP server and the skill together, so you can skip step 1:

  ```text
  /plugin marketplace add o11y-one/skills
  /plugin install o11y-one@o11y-one
  ```

  Run `/mcp` afterwards to sign in. The plugin's skill is `/o11y-one:o11y-one-setup`.

- By hand: copy `skills/o11y-one-setup/` into a skills directory your agent reads.

  ```bash
  git clone --depth 1 https://github.com/o11y-one/skills /tmp/o11y-one-skills
  mkdir -p .claude/skills
  cp -R /tmp/o11y-one-skills/skills/o11y-one-setup .claude/skills/
  ```

  | Agent | In the repo | For your user |
  | --- | --- | --- |
  | Claude Code | `.claude/skills/` | `~/.claude/skills/` |
  | Codex | `.agents/skills/` | `~/.agents/skills/` |
  | Cursor | `.agents/skills/`, `.cursor/skills/` or `.claude/skills/` | `~/.cursor/skills/` |

**3. Ask your agent:** `Set up o11y.one in this repo.`

The full guide is at [o11y.one/docs/o11y/agent-skill](https://o11y.one/docs/o11y/agent-skill).

## Repo layout

| Path | What it is |
| --- | --- |
| `skills/o11y-one-setup/SKILL.md` | The skill: a short router through the setup steps |
| `skills/o11y-one-setup/references/` | One self-contained file per topic |
| `.claude-plugin/` | The Claude Code marketplace and plugin manifests |
| `scripts/check.py` | The checks CI runs |
| `evals/` | The eval harness: fixture apps, a mock MCP server and an OTLP sink |

## Contributing

Read [AGENTS.md](AGENTS.md) before you change the skill.
Versions follow semver; see [CHANGELOG.md](CHANGELOG.md).

## License

[Apache-2.0](LICENSE)
