---
title: Python
impact: HIGH
tags: [python, fastapi, flask, django, pip, uv, poetry, opentelemetry-instrument]
---

# Python

## Guide arguments

- `language`: `python`.
- `framework`: `fastapi`, `django`, `flask` or `none`.
- `agent_framework`: when [detect](detect.md) found one.
- `service_name` and `service_namespace`: from [service-identity](service-identity.md).

## Install

Use the environment the project already uses. uv, poetry and pipenv manage their own.
pip installs into the project's virtualenv: the one `VIRTUAL_ENV` names, else `.venv/` or `venv/` in the service directory, else at the repo root.
Never install into the system Python, with `--user`, or with `--break-system-packages`.

| Manager | Command |
| --- | --- |
| uv | `uv add <name>==<version>` |
| poetry | `poetry add <name>==<version>` |
| pipenv | `pipenv install <name>==<version>` |
| pip, with `requirements*.txt` | Add `<name>==<version>` lines to the file the `Dockerfile`, CI or `Makefile` passes to `pip install -r`, else `requirements.txt`. Then run `python -m pip install -r <that file>` with the virtualenv's `python` |
| pip, with only `pyproject.toml` | Add `"<name>==<version>"` to `[project] dependencies`, then run `python -m pip install <name>==<version>` with the virtualenv's `python` |

If pip has no virtualenv to install into:

1. Creating one is outside the setup edits, so ask the user first.
2. With their yes, run `python3 -m venv .venv` in the service directory, add `.venv/` to `.gitignore` unless git already ignores it, and list both in the report.
3. With a no, still change the manifest and make the setup edits. Skip the install, the guide's `verify` commands and the first-trace check, and tell the user the commands to run in their own environment.

Don't run `opentelemetry-bootstrap -a install`. It guesses packages from whatever is installed and bypasses the lockfile, and OpenTelemetry's docs warn that it can fail under uv. Install only the guide's packages.

## Where the setup goes

Follow the guide's `load` value for each file. The shapes are:

| Framework | Setup |
| --- | --- |
| Any | The guide's setup module (`telemetry.py`) is the entrypoint's first import. When the guide's `start_command` says so, `opentelemetry-instrument` wraps the start command instead. |
| FastAPI | `FastAPIInstrumentor.instrument_app(app)` right after `app = FastAPI()`, in the module that creates the app |
| Flask | `FlaskInstrumentor().instrument_app(app)` right after `app = Flask(__name__)`, or inside the app factory before it returns `app` |
| Django | `DjangoInstrumentor().instrument()` after `DJANGO_SETTINGS_MODULE` is set, and before `get_wsgi_application()` in `wsgi.py`, `get_asgi_application()` in `asgi.py`, and `execute_from_command_line()` in `manage.py` |

These calls go where the app object is created, not as a global `instrument()` in `telemetry.py`; see [load-order](load-order.md#python).
They are part of the setup the guide prescribes; list each one in the report.

## Forking servers

Two setups start the SDK before the workers fork: gunicorn with `--preload`, and `opentelemetry-instrument` around a server with several workers.
Export from the workers can then break, and OpenTelemetry's docs recommend starting the SDK after the fork.
Take the first fix that applies:

1. Without `--preload`, use the guide's `first_import` setup, so each worker starts its own SDK.
2. With `--preload`, import the setup module in a `post_fork(server, worker)` hook in `gunicorn.conf.py`, instead of as the entrypoint's first import.
3. For an ASGI app with several workers, run gunicorn with a Uvicorn worker class plus that hook.

Fixes 2 and 3 are outside the setup edits, so ask the user first, and list them in the report.
For verify, run one worker: `uvicorn main:app` without `--workers`, or `gunicorn -w 1`.
[load-order](load-order.md#python) has the hook's code.

## Run it for verify

- Use the project's interpreter: `uv run`, `poetry run`, `pipenv run`, or the virtualenv's `python`.
- Export `.env` in the shell first, even when the project calls `load_dotenv()`: that call can run after the setup module's import.
- If the entrypoint calls `load_dotenv()` after the setup module's import, the user's own runs start the SDK without its config. Say so in the report, and offer to move the call above that import; don't move it yourself.
- Run without a reloader: no `--reload` for uvicorn, `--no-reload` for `flask run`, and `--noreload` for `manage.py runserver`.
- A script or agent that exits right away still sends its spans, because the SDK flushes on exit. Don't end it with `os._exit`.

When the start command uses `opentelemetry-instrument`, debug a silent run with `OTEL_TRACES_EXPORTER=otlp,console`.
