---
title: Service name and namespace
impact: CRITICAL
tags: [service-name, service-namespace, resource, identity]
---

# Service name and namespace

Every service needs a stable `service.name`; without one its spans arrive as `unknown_service` and can't be told apart.
Resolve the name with the lookup below, then pass it to `get_instrumentation_guide.v1` as `service_name`, together with `service_namespace`.

## service.name

Take the first rule that gives a name.

1. **Already configured.** Look for any of these:
   - `OTEL_SERVICE_NAME`, or `service.name=` inside `OTEL_RESOURCE_ATTRIBUTES`, in the service's `.env*` files, `docker-compose*.yml`, `Dockerfile`, `Procfile` or deploy config;
   - a service name in existing OpenTelemetry setup code.

   Use it exactly as written, even if it breaks the format below: dashboards and alerts may depend on it.
   If `get_instrumentation_guide.v1` refuses it (a name may hold only letters, digits and `_.:/-`), tell the user, and propose the nearest allowed name: the same name with each other character replaced by `-`. Use that name only with their yes; without one, skip the service and say why.
2. **The manifest name**, unless it is generic (see rule 4):
   - `package.json` `name`, without the scope: `@acme/billing-api` becomes `billing-api`.
   - `pyproject.toml` `[project] name` or `[tool.poetry] name`.
   - `go.mod` `module`, last path segment, skipping a major-version segment: `github.com/acme/billing-api/v2` becomes `billing-api`.
   - Maven `artifactId`; Gradle `rootProject.name` in `settings.gradle` or `settings.gradle.kts`.
3. **The service directory name**, unless it is generic, or it is the repo root of a monorepo.
4. **Ask the user.**
   - Generic names are `app`, `api`, `server`, `service`, `web`, `backend`, `frontend`, `main`, `src`, `my-app`, and an empty value.
   - If nobody can answer, as in a non-interactive run, use `<repo directory name>-<service directory name>`.

Write a name from rules 2 to 4 in lowercase kebab-case: spaces, underscores and dots become `-`, and camelCase splits, so `OrderApi` becomes `order-api`.

Names must be distinct within the repo.
If two services resolve to the same name, keep the first, rename the others to `<name>-<service directory name>`, and tell the user.

## service.namespace

Pass `service_namespace` to `get_instrumentation_guide.v1`; the guide puts it into the setup it returns.

| Repo | `service_namespace` |
| --- | --- |
| One service | The repo owner or organisation from the `origin` remote: `git@github.com:acme/shop.git` and `https://github.com/acme/shop` both give `acme`. With no remote, leave it out, and the guide falls back to the service name. |
| Several services | The service's grouping directory, which is its parent directory. If that parent is the repo root or a generic container (`apps`, `services`, `packages`, `cmd`, `src`), use the repo name instead: the root manifest name, or else the repo directory name. |

For example, in a monorepo named `shop`, `services/payments/api` gets `payments`, and `apps/web` gets `shop`.
If the service already sets `service.namespace`, keep that value and pass it.
Write the namespace in the same format as a rule 2 name.

## Where the name lives

The guide's setup files and `env` lines carry `service_name` and `service_namespace`.
Don't add `OTEL_RESOURCE_ATTRIBUTES` yourself when the guide already sets the namespace, and never set one attribute in two places with different values.
Leave `deployment.environment.name` out of `.env`: it differs per deploy, so tell the user to set it in each environment.
