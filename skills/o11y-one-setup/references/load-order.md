---
title: Load order
impact: CRITICAL
tags: [load-order, startup, preload, esm, commonjs, nextjs, gunicorn, uvicorn, otelhttp, javaagent]
---

# Load order

The SDK must start before the app loads the libraries it instruments.
If it starts later, the app runs normally and sends no spans, or only some.
`get_instrumentation_guide.v1` gives every setup file a `load` value; this file says what each one means, and where each runtime goes wrong.

## Load values

| `load` | Do this |
| --- | --- |
| `first_import` | Make the import of the setup file the first statement of the entrypoint, above every other import. |
| `start_flag` | Change every start command from [detect](detect.md): replace the command that matches `start_command.before_hint` with `start_command.after`. |
| `framework_hook` | Put the contents where the framework runs them: Next.js `instrumentation.ts`, the place the Python app object is created, a gunicorn `post_fork` hook. |
| `call_in_main` | Call the setup function as the first statement of `main()`, and defer its shutdown, so buffered spans are sent on exit. |

When a `path_hint` names a file that already exists, insert the contents at the place `load` says; never overwrite the file.
When it describes a file in angle brackets, such as `<module that creates the FastAPI app>`, find that file first.

## Node.js

- The guide's preload template is an ES module, `tracing.mjs`. Plain JavaScript preloads it with `node --import ./tracing.mjs`, whether the app is CommonJS or ESM. `--require` cannot load an ES module.
- TypeScript compiled to CommonJS imports the setup file as the first import of the entrypoint: `import './tracing'`. The compiler keeps the import order, so the setup runs before the app's other modules.
- Keep `--require` only for a CommonJS setup file that is already in the repo.
- When the start command is not a direct `node` call (`nest start`, `nodemon`), put the flag in `NODE_OPTIONS`, and append it to an existing `NODE_OPTIONS` value instead of replacing it.

```bash
# BAD: --require cannot load the guide's ES module template
node --require ./tracing.mjs server.js
# GOOD
node --import ./tracing.mjs server.js
```

```ts
// BAD: express is loaded before the SDK starts
import express from 'express'
import './tracing'

// GOOD
import './tracing'
import express from 'express'
```

## Next.js

- The setup is `instrumentation.ts` with `registerOTel` from `@vercel/otel`.
  - It goes at the project root, or in `src/` when `src/app` or `src/pages` exists.
  - It never goes in `next.config.*`, or inside `app/` or `pages/`.
- `@vercel/otel` also runs in the edge runtime. A Node-only SDK must load only when `process.env.NEXT_RUNTIME === 'nodejs'`.
- If `next build` fails on an OpenTelemetry package, that package belongs in `serverExternalPackages` in `next.config.*`.
  - Next.js 15 and later use that name; earlier versions call it `experimental.serverComponentsExternalPackages`.
  - That edit is outside the setup edits, so ask the user first, and list it in the report.
  - Add only the package the error names.

```ts
// instrumentation.ts, when a Node-only setup must stay out of the edge runtime
export async function register() {
  if (process.env.NEXT_RUNTIME === 'nodejs') {
    await import('./instrumentation.node')
  }
}
```

## Python

- The setup module, `telemetry.py`, is the entrypoint's first import, so the tracer provider exists before the framework is imported.
- FastAPI and Flask: the instrument call goes right after the app object is created, in the module that creates it.
  - `FastAPIInstrumentor.instrument_app(app)` goes after `app = FastAPI()`.
  - `FlaskInstrumentor().instrument_app(app)` goes after `app = Flask(__name__)`.
  - It is never a global `instrument()` in `telemetry.py`.
- Django: `DjangoInstrumentor().instrument()` goes after `DJANGO_SETTINGS_MODULE` is set, and before `get_wsgi_application()` or `get_asgi_application()`. Do this in `wsgi.py`, `asgi.py` and `manage.py`.
- Forking servers: `opentelemetry-instrument` and gunicorn `--preload` start the SDK in the parent process, before the workers fork. OpenTelemetry's Python docs warn that more than one worker can then break export, and recommend starting the SDK after the fork. Fix it in this order:
  1. Use the guide's `first_import` setup without `--preload`, so each worker starts its own SDK.
  2. With `--preload`, run the setup in a `post_fork(server, worker)` hook in `gunicorn.conf.py`, instead of as the entrypoint's first import.
  3. For an ASGI app with several workers, run gunicorn with a Uvicorn worker class plus that hook. This changes the server, so ask first.

  For verify, run one worker.

```python
# BAD: a global instrument() that runs after the app object exists misses that app
app = FastAPI()
FastAPIInstrumentor().instrument()

# GOOD
app = FastAPI()
FastAPIInstrumentor.instrument_app(app)
```

```python
# wsgi.py
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mysite.settings")

from django.core.wsgi import get_wsgi_application
from opentelemetry.instrumentation.django import DjangoInstrumentor

DjangoInstrumentor().instrument()
application = get_wsgi_application()
```

```python
# gunicorn.conf.py, only when the server runs with --preload
def post_fork(server, worker):
    import telemetry  # the guide's setup module; importing it starts the SDK in this worker
```

## Go

- Run the setup function first in `main()`, and `defer` its shutdown. A process that exits without the shutdown drops its buffered spans, and `os.Exit` and `log.Fatal` skip deferred calls.
- Wrap the outermost handler, the one passed to the server, with `otelhttp.NewHandler`, so every route gets a server span.
- gin and echo: register the middleware (`otelgin.Middleware`, `otelecho.Middleware`) before any route. In gin, routes registered before `Use` never get it.
- Outgoing HTTP calls carry the trace only through a client whose transport is `otelhttp.NewTransport`.

```go
// BAD: only /orders is traced; other routes send no server span
mux.Handle("/orders", otelhttp.NewHandler(orders, "orders"))
http.ListenAndServe(":8080", mux)

// GOOD
http.ListenAndServe(":8080", otelhttp.NewHandler(mux, "server"))
```

```go
// BAD: /orders was registered before the middleware
r := gin.New()
r.GET("/orders", listOrders)
r.Use(otelgin.Middleware("orders-api"))

// GOOD
r := gin.New()
r.Use(otelgin.Middleware("orders-api"))
r.GET("/orders", listOrders)
```

## Java

- `-javaagent:<path to the agent jar>` must come before `-jar`: anything after `-jar app.jar` goes to the app, not the JVM.
- Add it everywhere the service starts: `Dockerfile` `ENTRYPOINT` or `CMD`, `Procfile`, and start scripts. Where a command can't be edited, append it to `JAVA_TOOL_OPTIONS`, keeping the value already there.
- Download the jar where the guide says (at image build time, for a `Dockerfile`), and never commit it. Add its local path to `.gitignore`.

```dockerfile
# BAD: the agent flag is passed to the app
ENTRYPOINT ["java", "-jar", "app.jar", "-javaagent:/otel/opentelemetry-javaagent.jar"]

# GOOD
ENTRYPOINT ["java", "-javaagent:/otel/opentelemetry-javaagent.jar", "-jar", "app.jar"]
```
