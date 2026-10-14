---
title: Node.js
impact: HIGH
tags: [nodejs, javascript, typescript, express, fastify, npm, pnpm, yarn]
---

# Node.js

This covers Express, Fastify and plain Node.js services. Next.js has its own file, [nextjs](nextjs.md).

## Guide arguments

| Argument | Value |
| --- | --- |
| `language` | `typescript` when the service has `tsconfig.json` or depends on `typescript`, else `javascript` |
| `framework` | `express`, `fastify` or `none` |
| `module_type` | `esm` when `package.json` has `"type": "module"`, else `commonjs` |
| `agent_framework` | Only when [detect](detect.md) found one |
| `service_name`, `service_namespace` | From [service-identity](service-identity.md) |

## Install

| Manager | Command |
| --- | --- |
| pnpm | `pnpm add <name>@<version>` |
| npm | `npm install <name>@<version>` |
| yarn | `yarn add <name>@<version>` |
| bun | `bun add <name>@<version>` |

OpenTelemetry packages are runtime dependencies. Never add them with `-D` or `--save-dev`: a production install leaves dev dependencies out, and the app then fails at start.

## Where the setup loads

Follow the guide's `load` value. The shapes are:

| Service | Setup |
| --- | --- |
| Plain JavaScript | `node --import ./tracing.mjs <entrypoint>` in every start command |
| TypeScript compiled to CommonJS | `import './tracing'` as the first import of the entrypoint source |
| Plain JavaScript started by a command that isn't `node` itself, such as `nodemon` | The same flag in `NODE_OPTIONS`, appended to any value already there |

Pitfalls:

- TypeScript: the build compiles only files inside the `include` of `tsconfig.json`, so a setup file outside it is skipped, and the app crashes on the missing module. Keep the guide's `path_hint`. If it falls outside `include`, tell the user, and list the mismatch in the report.
- A flag must point at a file the runtime loads: compiled JavaScript for `node dist/...`, and the `.ts` file only when the runner loads TypeScript itself.
- `node: bad option: --import` means the project's Node.js version predates the flag. Tell the user, and don't change the Node.js version.
- An existing `NODE_OPTIONS` with `--require` or `--import` of something else means another agent is already loaded; see [partial-instrumentation](partial-instrumentation.md).
- The Bun runtime (`bun run` as the start command) is not covered: tell the user and skip the service. A bun lockfile with a `node` start command is fine.

More on ordering: [load-order](load-order.md#nodejs).

## Run it for verify

1. Run the build script, if there is one: `<manager> run build`.
2. Start the app with the `.env` values exported. Use the production start command (`start`) rather than a watcher, so only one process runs.
3. The port is in the code or in `PORT`. Send the request from [verify](verify.md).

If the app imports `dotenv` after the setup import, or `--import ./tracing.mjs` runs before it, the user's own runs start the SDK without its config. Say so in the report, and offer to load `dotenv` ahead of the setup, with `--import dotenv/config` before the tracing flag or an `import 'dotenv/config'` above `import './tracing'`; don't change it yourself.

To debug a silent run, set `OTEL_LOG_LEVEL=debug` for one run, and read the exporter errors it logs.
The guide's setup passes its exporter in code, so `OTEL_TRACES_EXPORTER` changes nothing: spans missing from stdout are never a sign that the SDK is broken.
