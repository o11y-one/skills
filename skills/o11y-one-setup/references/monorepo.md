---
title: Monorepos and several services
impact: HIGH
tags: [monorepo, workspaces, services, keys]
---

# Monorepos and several services

Use this when the repo holds more than one service.
Each service gets its own guide call, its own `service.name` and its own verify result; the key is shared.

## Workspace markers

| Marker | Members |
| --- | --- |
| `pnpm-workspace.yaml` | Its `packages:` globs |
| `workspaces` in the root `package.json` | Its globs |
| `turbo.json` or `nx.json` | The package manager's workspace members |
| `go.work` | Each `use` directory |
| `[tool.uv.workspace]` in the root `pyproject.toml` | Its `members` globs |
| `<modules>` in the root `pom.xml`, or `include(...)` in `settings.gradle*` | Each module |
| No marker, but several of `apps/*`, `services/*` or `cmd/*` with their own manifests or `main` packages | Each such directory |

Apply the service test from [detect](detect.md) to every member, because libraries are not services.

## Steps

1. List the services in one table: directory, language, framework, agent framework, `service.name` and `service_namespace`. Show it before any edit.
2. Give every service a distinct `service.name` and its grouping namespace, per [service-identity](service-identity.md).
3. Call `get_instrumentation_guide.v1` once per service.
4. Install packages into the service's own package, not the workspace root:

   | Manager | Command shape |
   | --- | --- |
   | pnpm | `pnpm --filter <package name> add <name>@<version>` |
   | npm | `npm install <name>@<version> -w <service directory>` |
   | yarn | `yarn workspace <package name> add <name>@<version>` |
   | uv | `uv add --package <project name> <name>==<version>` |
   | go | `go get <module>@<version>`, inside the service's module directory |

   Run the lockfile refresh once, at the root, after all the installs.
5. Create one key for the repo with `create_ingestion_token.v1`, named after the repo, and never one per service: the tool allows 5 keys per user per hour.
   - Write the key into each service's gitignored `.env`.
   - Write it once into a root `.env` instead when every service already loads that file, for example through `env_file: .env` in a root `docker-compose.yml`.
6. Verify one service at a time, per [verify](verify.md): start it, send one request, and poll `get_onboarding_status.v1` with that service's `service_name` until its `latest_trace` is newer than the start time. Then move on.
   - If services call each other, start them together with the repo's own command (`docker compose up`, the root `dev` script) and send one request to each.
7. A failure in one service does not stop the others. Finish them all, then report.

## Report

Give one row per service:

| Service | Directory | Result | Root span |
| --- | --- | --- | --- |
| `orders-api` | `services/orders` | Trace received | `GET /orders` |
| `billing-worker` | `services/billing` | No trace: 401 from the exporter | |

For each failed row, say which troubleshooting entry you followed and what is left for the user to do.
