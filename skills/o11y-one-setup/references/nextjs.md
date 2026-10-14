---
title: Next.js
impact: HIGH
tags: [nextjs, vercel-otel, instrumentation-ts, edge, server-external-packages]
---

# Next.js

## Guide arguments

- `language`: `typescript` or `javascript`.
- `framework`: `nextjs`.
- `module_type`, `service_name` and `service_namespace`.
- `agent_framework`: `vercel_ai` when the app uses the AI SDK.

## The setup file

- The guide returns `instrumentation.ts` (or `.js`), which calls `registerOTel` from `@vercel/otel` inside `export function register()`.
- Put it at the project root, next to `package.json`, or in `src/` when the app lives in `src/app` or `src/pages`. Never put it in `next.config.*`, or inside `app/` or `pages/`.
- If `next.config.*` sets `pageExtensions`, the file name takes the same extension pattern.
- Read the `next` version from the lockfile:
  - 15 and later load `instrumentation.ts` with no config.
  - 13.2 to 14 need `experimental.instrumentationHook: true` in `next.config.*`. That edit is outside the setup edits, so ask the user first, and list it in the report.
  - Before 13.2 there is no instrumentation hook. Tell the user, and stop for this service.
- Install the guide's packages as dependencies of the Next.js app, not of the workspace root.

## Runtimes

- `@vercel/otel` runs in both the Node.js and the edge runtime, so routes with `export const runtime = 'edge'`, and `middleware.ts`, are covered.
- If the repo already has a Node-only SDK setup (`NodeSDK`), it must load only when `process.env.NEXT_RUNTIME === 'nodejs'`; see [load-order](load-order.md#nextjs). In that case, tell the user that edge routes send no spans.

## Bundling

If `next build` fails on an OpenTelemetry package (`Module not found`, or a `require` that can't be resolved), that package belongs in `serverExternalPackages` in `next.config.*`.
That is the name in Next.js 15 and later; earlier versions call it `experimental.serverComponentsExternalPackages`.
That edit is outside the setup edits, so ask the user first, and list it in the report.
Add only the package the error names, then build again.
`require-in-the-middle` and `import-in-the-middle` are already on Next.js's default list.

## Environment

Next.js loads `.env` and `.env.local` itself, so the server sees the variables in both `next dev` and `next start`.
Use `.env.local` when the repo already keeps its secrets there. The git-ignore check from [keys-and-secrets](keys-and-secrets.md) still applies.
On Vercel or another host, the variables go in the project's environment settings; say so in the report.

## Run it for verify

1. `<manager> run build` must pass.
2. Start with `<manager> run start` (or `next start`), then request `/`.
3. The root span is named after the route, like `GET /`.
