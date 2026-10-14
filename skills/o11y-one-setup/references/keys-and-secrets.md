---
title: Ingestion keys and secrets
impact: CRITICAL
tags: [keys, secrets, env, gitignore, members, security]
---

# Ingestion keys and secrets

The ingestion key is the only secret this skill handles.
It goes into one place, a gitignored `.env` or the repo's existing secret manager, and nowhere else.
It never goes into a commit, a pull request, a URL, a log, a command-line argument, or your messages to the user.

## Reuse before you create

Look for a key that is already there, in this order:

1. The service's `.env` (or `.env.local`, when the repo uses that) has an `OTEL_EXPORTER_OTLP_HEADERS` line that contains `<auth_header>=`, where `auth_header` comes from `get_ingest_config.v1`, and the value is not the `<ingestion key>` placeholder.
2. Another service in this repo has one, in a monorepo.
3. The repo's secret manager has `OTEL_EXPORTER_OTLP_HEADERS` set.

If one exists, reuse it and don't call `create_ingestion_token.v1`.

## Create

Call `create_ingestion_token.v1` with `name`:

- One service: `<repo>-<service>`, for example `shop-orders-api`.
- Several services: `<repo>`, one key shared by all of them.

`<repo>` is the repo name from the `origin` remote, or else the repo directory name.
Keep `token_id` and `expires_at` for the report.
The `env_line` it returns is the exact line to store.

## Where the key goes

| The repo has | Store the key in |
| --- | --- |
| `doppler.yaml` or `.doppler.yaml` | Doppler |
| `.infisical.json` | Infisical |
| `op://` references in a `.env*` file | 1Password |
| `.sops.yaml` | SOPS-encrypted files |
| None of these | `.env` in the service directory, the directory its start command runs in |

For a secret manager, ask the user once whether to store the key there.
- If they agree, set `OTEL_EXPORTER_OTLP_HEADERS` with that manager's own CLI. Pass the value through a file or stdin, never typed into the command line.
- If the CLI is missing or not signed in, or the user declines, use `.env`, and tell the user the secret name to add later.

## Write .env safely

1. Check that git ignores the file before it holds a key: `git check-ignore -q <service dir>/.env` exits 0 when it is ignored.
2. If it is not ignored, add the line `.env` to the `.gitignore` in the service directory (create that file if needed), and run the check again.
3. If `.env` is already tracked (`git ls-files --error-unmatch <service dir>/.env` exits 0), stop. Tell the user the file is committed, and don't write a key into it.
4. Append the key line. Keep every existing line; never rewrite or reorder the file. If an `OTEL_EXPORTER_OTLP_HEADERS` line already exists for another backend, stop and follow [partial-instrumentation](partial-instrumentation.md).
5. If `.env.example` exists, add the same variable names to it, with `<ingestion key>` in place of the key.

## Members without key rights

Only owners and admins can create ingestion keys.
Take this path when any of these happens:

- `create_ingestion_token.v1` is not in your tool list, while the other o11y-one tools are.
- It returns `not_owner_or_admin`, or fails with `oauth token does not grant permission`.
- It returns `no_user_on_session`, which means the sign-in is not tied to a person.
- It returns `hourly_limit_reached`, and [Reuse before you create](#reuse-before-you-create) found no existing key.

Then:

1. Don't call the tool again. Carry on with every other step: packages, setup files and start commands.
2. Write the `OTEL_EXPORTER_OTLP_HEADERS` value from the `env` map of `get_ingest_config.v1` into the gitignored `.env` as it is. It holds the `<ingestion key>` placeholder.
3. Tell the user, in these words or close to them: "Only owners and admins can create o11y.one ingestion keys. Ask one to create a key (Connect page, Generate key) and put it in place of `<ingestion key>` in `<path>/.env`. If you are an owner or admin, sign in to the o11y-one MCP server again and tell me to retry."
4. When `.env` no longer contains `<ingestion key>`, run verify. If the user pastes a key into the chat instead, write it to `.env` and don't repeat it back.
5. Never run verify with the placeholder still in place.

For `hourly_limit_reached`, add that the limit is 5 keys per hour, so waiting an hour also works.

## Load .env for the run

Most runtimes don't read `.env` on their own.

| The service already loads `.env` through | Then |
| --- | --- |
| Next.js (built in), a `dotenv` import (when it runs before the setup module: `node --import dotenv/config` or `--require dotenv/config` ahead of the tracing file, or a dotenv call inside the tracing file itself), `load_dotenv()` from python-dotenv (when called before the setup module's import), `env_file:` in compose, a `--env-file` flag, or `uv run --env-file` | Nothing to add. |
| None of these | For verify, export it in the shell that starts the app: `set -a; . ./.env; set +a`. Don't change how the app loads its environment; offer that in the report instead. |

## Show it masked

Never print the key.
When you show the `.env` change, mask the value after its first 4 characters, as in `OTEL_EXPORTER_OTLP_HEADERS=<auth_header>=abcd…`.
When you check `.env`, print the names only: `grep -o '^[A-Z_]*=' .env`.

## Production

`.env` stays on this machine.
In the report, list the variable names the deployed service needs, and say that `OTEL_EXPORTER_OTLP_HEADERS` belongs in the deploy platform's secret store.
