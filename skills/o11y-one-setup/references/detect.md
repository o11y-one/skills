---
title: Detect services, languages and frameworks
impact: CRITICAL
tags: [detect, services, languages, frameworks, entrypoints, package-managers]
---

# Detect services, languages and frameworks

Do this before any edit.
The result is one row per service, and its columns are the arguments for `get_instrumentation_guide.v1`.

## Find the services

A service is a directory whose code runs as its own process: it has a start script, a `main` function or package, a server entrypoint, a `Dockerfile`, or a `Procfile` line.
A library that other packages import, with no start command, is not a service; leave it alone.
When the repo root declares a workspace, check every member; [monorepo](monorepo.md) lists the markers.

## Language

| In the service directory | `language` |
| --- | --- |
| `package.json` plus `tsconfig.json`, or `typescript` among its dependencies | `typescript` |
| `package.json` only | `javascript` |
| `pyproject.toml`, `requirements*.txt`, `Pipfile`, `setup.py` or `setup.cfg` | `python` |
| `go.mod` | `go` |
| `pom.xml`, `build.gradle` or `build.gradle.kts` | `java` |

If a directory matches two rows, the start command decides:
- `node`, `next`, `tsx` or `ts-node` means JavaScript or TypeScript.
- `python`, `uvicorn`, `gunicorn` or `manage.py` means Python.

Any other language is not covered yet. Tell the user, point them to the "I'll do it" door on the o11y.one Connect page, and skip the service.

## Framework

Read the service's own dependency list.
If two rows match, use the framework the entrypoint imports.

| Dependency | `framework` |
| --- | --- |
| `next` | `nextjs` |
| `fastify` | `fastify` |
| `express` | `express` |
| `fastapi` | `fastapi` |
| `django` | `django` |
| `flask` | `flask` |
| `github.com/gin-gonic/gin` | `gin` |
| `github.com/labstack/echo/v4` | `echo` |
| A Go service that calls `http.ListenAndServe` or builds an `http.Server`, with neither of the two above | `net_http` |
| `spring-boot-starter-web` or `spring-boot-starter-webflux` | `spring` |
| None of these | `none` |

Next.js has its own reference, [nextjs](nextjs.md), even when the app also uses Express.

## Agent framework

| Dependency | `agent_framework` |
| --- | --- |
| Python `langchain`, `langchain-core` or `langgraph`; npm `langchain`, `@langchain/core` or `@langchain/langgraph` | `langchain` |
| Python `openai-agents`; npm `@openai/agents` | `openai_agents` |
| npm `ai` (the Vercel AI SDK) | `vercel_ai` |
| Python `crewai` | `crewai` |
| Python `llama-index` or `llama-index-core`; npm `llamaindex` | `llamaindex` |

Leave `agent_framework` out when nothing matches.
If two match, ask the user which one runs the agent loop.
A plain model client such as `openai` or `anthropic`, without one of these, is not an agent framework.

## Module type

This applies to JavaScript and TypeScript only.
`"type": "module"` in the service's `package.json` means `esm`; anything else means `commonjs`.
For TypeScript, also note `module` in `tsconfig.json`, because the compiled output is what runs.

## Entrypoint

| Language | Where to look, in order |
| --- | --- |
| JavaScript, TypeScript | The file the `start` script runs, then `main` in `package.json`, then `src/index.*`, `src/server.*`, `index.*`, `server.*` |
| Python | The module in the start command (`uvicorn main:app` means `main.py`), then `manage.py`, `wsgi.py` or `asgi.py`, `app.py`, `main.py`, `[project.scripts]` |
| Go | The `package main` file with `func main()`, often `cmd/<name>/main.go` |
| Java | The class with `@SpringBootApplication` or `public static void main` |

## Start commands

List every place that starts the service, because each one needs the same change:
- `package.json` scripts (`start`, `dev`, `serve`)
- `Procfile`
- `Dockerfile` `CMD` and `ENTRYPOINT`
- `docker-compose*.yml` `command`
- `Makefile` run targets
- platform files such as `fly.toml` or `render.yaml`

## Package manager

| Lockfile or file | Manager |
| --- | --- |
| `pnpm-lock.yaml` | pnpm |
| `package-lock.json` | npm |
| `yarn.lock` | yarn |
| `bun.lock` or `bun.lockb` | bun |
| `uv.lock` | uv |
| `poetry.lock` | poetry |
| `Pipfile.lock` | pipenv |
| `requirements*.txt` and no other lockfile | pip |
| `go.mod` | go |
| `pom.xml` | maven |
| `build.gradle` or `build.gradle.kts` | gradle |

In a workspace, the lockfile is usually at the root, and that manager applies to every member.
JavaScript with no lockfile means npm.
Python with `pyproject.toml` and none of `uv.lock`, `poetry.lock`, `Pipfile.lock` or `requirements*.txt` means pip: add the packages to `[project] dependencies` in `pyproject.toml`, then install them with pip into the active virtualenv.

## Report before you edit

Show the user one line per service: its directory, language, framework, agent framework, `service.name` from [service-identity](service-identity.md), and package manager.
