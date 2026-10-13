# Authoring rules

These rules are for anyone, person or agent, who edits this repo.
The skill's reader is a coding agent that acts on every sentence literally, so the rules aim at text an agent can carry out without guessing.

## Rules for skill text

Each rule has a BAD and a GOOD example.

### 1. Tell the agent what to do

State the action.
Explain only what the agent needs in order to choose between actions.

- BAD: `OpenTelemetry exporters can use several protocols.`
- GOOD: `Set OTEL_EXPORTER_OTLP_PROTOCOL to default_protocol from get_ingest_config.v1.`

### 2. Make every choice enumerable

Use an ordered list, a table or explicit criteria.
Never leave a choice open.

- BAD: `Pick a sensible service name.`
- GOOD: `Use the first of: OTEL_SERVICE_NAME already set, the manifest name, the service directory name; otherwise ask.`

### 3. Test conditions the agent can check

Conditions are about files, commands and tool output, not about what someone probably wants.

- BAD: `If the user probably wants ESM, ...`
- GOOD: `If package.json has "type": "module", ...`

### 4. Name tools and fields, never live values

The endpoint, protocol, auth header, packages, versions and file contents come from the MCP tools when the skill runs.
CI fails if text under `skills/` spells out an ingest host, the auth header or an OTLP port.

- BAD: `OTEL_EXPORTER_OTLP_ENDPOINT=https://ingest.example`
- GOOD: `OTEL_EXPORTER_OTLP_ENDPOINT from the env map of get_ingest_config.v1`

### 5. Never write a package or version from memory

- BAD: `npm install @opentelemetry/sdk-node@0.0.0`
- GOOD: `Install the packages get_instrumentation_guide.v1 returns, at the versions it gives.`

### 6. Keep each reference self-contained

An agent may load one reference and nothing else.
A reference may link another for more detail, but its own steps must be complete without that link.
SKILL.md links references; keep links one level deep.

- BAD: a section whose only content is `See troubleshooting.md.`
- GOOD: the section lists its own steps, then `More cases: troubleshooting.md#no-spans-while-the-app-runs`.

### 7. Keep SKILL.md a router

SKILL.md holds the order of work and one line per decision; the detail goes in a reference.
CI fails at 200 lines.

- BAD: a 40-line Next.js section in SKILL.md.
- GOOD: `Next.js: instrumentation.ts at the project root. See nextjs.`

### 8. Keep secrets out of examples

Write `<ingestion key>` where a key goes.
Eval fixtures use tokens that start with `TEST-` and addresses under `example.test`.

- BAD: a real-looking key in a sample `.env`.
- GOOD: `OTEL_EXPORTER_OTLP_HEADERS=<auth_header>=<ingestion key>`

## Structure

- `skills/<name>/SKILL.md` uses only the six Agent Skills frontmatter fields: `name`, `description`, `license`, `compatibility`, `metadata` and `allowed-tools`.
  - `name` matches the folder, and is 1 to 64 lowercase letters, digits and single hyphens.
  - `description` is one line of at most 1024 characters. It says what the skill does, when to use it, and when not to.
- Each file in `references/` starts with `title`, `impact` and `tags` frontmatter. `impact` is `CRITICAL`, `HIGH`, `MEDIUM` or `LOW`.
- Every reference is linked from the References table in SKILL.md, every link resolves, and every anchor points at a real heading.
  - Keep anchor headings to letters, digits, spaces and dots.
  - Renaming a heading that something links to is a major change.
- The MCP URL appears on exactly three lines of this repo: `.claude-plugin/plugin.json`, the install line in `README.md`, and the server line under "Before you start" in SKILL.md.
  - Change all three together.
  - Also change the docs page in the o11y.one repo, `src/content/docs/docs/o11y/agent-skill.mdx`.
- That docs page mirrors SKILL.md's numbered steps. When you change a step heading here, update the page in the same change.

Run `python3 scripts/check.py` before you push. CI runs it, together with `claude plugin validate --strict`.

## Versions

The repo has one version, kept equal in `.claude-plugin/plugin.json`, the `metadata.version` of every SKILL.md, and the top entry of `CHANGELOG.md`. CI checks that they match.

| Change | Bump |
| --- | --- |
| Wording that keeps the same steps | patch |
| A new reference, framework or language | minor |
| Removing or renaming a reference or an anchor, changing what the skill does to a repo, or depending on a changed MCP tool contract | major |

## Evals

`evals/run.py` runs the skill headless against fixture apps, with a mock MCP server and an OTLP sink in one process.
The verdict comes only from what the sink received, what the mock logged and what is on disk; no model judges it.

- Add a fixture and a scenario when you add a framework or a language.
- Keep fixture data synthetic.
- The evals call a model and cost money, so they run on demand, not on every push.
