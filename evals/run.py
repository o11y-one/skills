#!/usr/bin/env python3
"""Run o11y-one-setup headless against fixture apps, and check what actually happened.

Each scenario copies a fixture into a temp git repo, starts the mock (MCP server and OTLP sink in one
process), and runs Claude Code with only this plugin and only the mock server. It then checks the
sink, the mock's call log, the repo on disk and the agent's own words. No model judges the result.

Needs claude, node, npm, python3 (3.10 or later, with venv), git, lsof, ANTHROPIC_API_KEY, and
network access to npm and PyPI. The agent runs with permissions bypassed, so run this in CI or a
throwaway VM.

    python3 evals/run.py                     # every scenario
    python3 evals/run.py node-express member
"""
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

import mock_o11y

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "evals" / "fixtures"
PROMPT = "Set up o11y.one in this repo."
SKILL = "o11y-one:o11y-one-setup"
NEEDS = ("claude", "git", "lsof", "node", "npm", "python3")
MAX_BUDGET_USD = os.environ.get("EVAL_MAX_BUDGET_USD", "5")
TIMEOUT_S = 20 * 60
FILE_TOOLS = {"Write", "Edit"}
FIXTURE_GIT = ["-c", "user.name=eval", "-c", "user.email=eval@example.test", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]
SKIP = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist"}
SERVED = [("key_only_in_ignored_env",), ("key_not_shown",), ("keys_minted", 1)]

# name: (fixture, mock mode, ports the app listens on, checks)
SCENARIOS = {
    "node-express": ("node-express", "owner", [3000], [("trace_from", "eval-node-api")] + SERVED),
    "busy-org": ("node-express", "busy", [3000], [("trace_from", "eval-node-api"), ("status_filtered", "eval-node-api")] + SERVED),
    "node-ts": ("node-ts", "owner", [3001], [("trace_from", "eval-ts-api")] + SERVED),
    "python-fastapi": ("python-fastapi", "owner", [8000], [("trace_from", "eval-py-api")] + SERVED),
    "langchain-agent": ("langchain-agent", "owner", [], [("trace_from", "eval-lc-agent")] + SERVED),
    "already-instrumented": ("node-otel", "owner", [3002], [("trace_from", "eval-node-otel"), ("one_node_sdk",)] + SERVED),
    "member": ("node-express", "member", [3000], [("otel_installed",), ("placeholder_in_env",), ("says", r"(?i)\b(owner|admin)s?\b")]),
    "monorepo-3": ("monorepo", "owner", [3101, 3102, 3103], [
        ("trace_from", "eval-orders"), ("trace_from", "eval-billing"), ("trace_from", "eval-notify"),
        ("namespace", "eval-mono")] + SERVED),
    "stale-mcp": ("node-express", "stale", [3000], [("no_edits",), ("says", r"(?<![\w.])/mcp\b")]),
    "no-trace": ("node-express", "blackhole", [3000], [("bounded_polling",), ("key_not_shown",)]),
}


def git(work, *args):
    return subprocess.run(["git", *args], cwd=work, capture_output=True, text=True)


def files(work):
    for path in work.rglob("*"):
        if path.is_file() and not SKIP & set(path.relative_to(work).parts):
            yield path


def read(path):
    try:
        return path.read_text()
    except (UnicodeDecodeError, OSError):
        return ""


def events(transcript):
    for line in transcript.splitlines():
        try:
            yield json.loads(line)
        except ValueError:
            continue


def assistant_text(transcript):
    texts = []
    for event in events(transcript):
        if event.get("type") == "assistant":
            texts += [block.get("text", "") for block in event.get("message", {}).get("content", []) if block.get("type") == "text"]
        elif event.get("type") == "result":
            texts.append(event.get("result") or "")
    return "\n".join(texts)


def tool_calls(transcript):
    for event in events(transcript):
        if event.get("type") == "assistant":
            yield from (block for block in event.get("message", {}).get("content", []) if block.get("type") == "tool_use")


def called_skill(transcript):
    return any(call.get("name") == "Skill" and call.get("input", {}).get("skill") == SKILL for call in tool_calls(transcript))


def writes_env(call):
    return call.get("name") in FILE_TOOLS and Path(str(call.get("input", {}).get("file_path", ""))).name.startswith(".env")


def tool_inputs(transcript):
    """Every tool call's input, except a file tool writing a .env file, which is where the key belongs."""
    return "\n".join(json.dumps(call.get("input")) for call in tool_calls(transcript) if not writes_env(call))


def check(kind, arg, work, mock, said, inputs):
    names = sorted({t["service_name"] for t in mock.traces})
    if kind == "trace_from":
        return arg in names, f"no trace from {arg}; the sink saw {names or 'nothing'} and refused {mock.rejected} requests"
    if kind == "namespace":
        return any(t["namespace"] == arg for t in mock.traces), f"no trace with service.namespace={arg}"
    if kind == "keys_minted":
        return len(mock.tokens) == arg, f"{len(mock.tokens)} keys created, expected {arg}"
    if kind == "key_only_in_ignored_env":
        holders = [p for p in files(work) if any(token in read(p) for token in mock.tokens)]
        bad = [p for p in holders if not p.name.startswith(".env") or git(work, "check-ignore", "-q", str(p)).returncode != 0]
        shown = [str(p.relative_to(work)) for p in holders]
        return bool(holders) and not bad, f"key found in {shown}; must be only in gitignored .env files"
    if kind == "key_not_shown":
        leaked = any(token in said or token in inputs for token in mock.tokens)
        return not leaked, "the agent printed the key, or put it in a tool call other than a .env write"
    if kind == "placeholder_in_env":
        found = any(p.name.startswith(".env") and mock_o11y.PLACEHOLDER in read(p) for p in files(work))
        return found, "no .env holds the <ingestion key> placeholder"
    if kind == "otel_installed":
        return "@opentelemetry/" in read(work / "package.json"), "package.json has no OpenTelemetry package"
    if kind == "one_node_sdk":
        hits = [str(p.relative_to(work)) for p in files(work) if p.suffix in {".js", ".mjs", ".cjs", ".ts"} and "new NodeSDK(" in read(p)]
        return len(hits) == 1, f"NodeSDK is started in {hits}"
    if kind == "status_filtered":
        asked = sorted({str(args.get("service_name")) for name, args, _ in mock.calls if name == mock_o11y.STATUS})
        return arg in asked, f"get_onboarding_status.v1 was never called with service_name={arg}; it got {asked}"
    if kind == "no_edits":
        changed = [line for line in git(work, "status", "--porcelain").stdout.splitlines() if ".claude/" not in line]
        return not changed, f"files changed: {changed}"
    if kind == "says":
        return re.search(arg, said) is not None, f"the agent never said {arg!r}"
    if kind == "bounded_polling":
        times = [t for name, _, t in mock.calls if name == mock_o11y.STATUS]
        span = times[-1] - times[0] if times else 0
        return 1 <= len(times) <= 60 and 100 <= span <= 600, f"{len(times)} status calls over {span:.0f}s; expected at most 60, over 100 to 600s"
    raise ValueError(f"unknown check {kind}")


def listeners(address):
    return sorted(set(subprocess.run(["lsof", "-ti", address, "-sTCP:LISTEN"], capture_output=True, text=True).stdout.split()), key=int)


def cwd_of(pid):
    out = subprocess.run(["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"], capture_output=True, text=True).stdout
    return next((Path(line[1:]) for line in out.splitlines() if line.startswith("n")), None)


def stop_leftovers(pgid, work):
    # ponytail: kills the agent's process group and every TCP listener running from the work dir; a detached process with another cwd outlives the run
    root = work.resolve()
    ours = [pid for pid in listeners("tcp") if (where := cwd_of(pid)) and where.resolve().is_relative_to(root)]
    for kill, target in [(os.killpg, pgid)] + [(os.kill, int(pid)) for pid in ours]:
        try:
            kill(target, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def run(name):
    fixture, mode, ports, checks = SCENARIOS[name]
    busy = [f"port {port} is in use by pid {', '.join(pids)}; free it and rerun" for port in ports if (pids := listeners(f"tcp:{port}"))]
    if busy:
        return busy
    work = Path(tempfile.mkdtemp(prefix=f"o11y-eval-{name}-"))
    shutil.copytree(FIXTURES / fixture, work, dirs_exist_ok=True)
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "fixture"]):
        result = git(work, *FIXTURE_GIT, *args)
        if result.returncode:
            return [f"git {' '.join(args)} failed in {work}: {result.stderr.strip()}"]
    mock = mock_o11y.Mock(mode)
    config = work.with_name(work.name + "-mcp.json")
    config.write_text(json.dumps({"mcpServers": {"o11y-one": {"type": "http", "url": f"{mock.base}/mcp"}}}))
    # An empty config dir keeps the user's settings, plugins, hooks, memory and login out of the run.
    # --bare would too, but in Claude Code 2.1.296 it also drops the Skill tool, so PROMPT could never load the skill.
    claude_dir = work.with_name(work.name + "-claude")
    claude_dir.mkdir()
    command = [
        "claude", "-p", PROMPT, "--plugin-dir", str(ROOT),
        "--mcp-config", str(config), "--strict-mcp-config", "--dangerously-skip-permissions",
        "--output-format", "stream-json", "--verbose", "--no-session-persistence", "--max-budget-usd", MAX_BUDGET_USD,
    ]
    env = {key: value for key, value in os.environ.items() if not key.startswith("OTEL_")}
    env["CLAUDE_CONFIG_DIR"] = str(claude_dir)
    failures = []
    agent = subprocess.Popen(command, cwd=work, env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    try:
        transcript, _ = agent.communicate(timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        os.killpg(agent.pid, signal.SIGKILL)
        transcript, _ = agent.communicate()
        failures.append(f"timed out after {TIMEOUT_S}s")
    finally:
        stop_leftovers(agent.pid, work)
        mock.close()
    log = work.with_name(work.name + "-transcript.jsonl")
    log.write_text(transcript)
    said, inputs = assistant_text(transcript), tool_inputs(transcript)
    if not called_skill(transcript):
        failures.append(f"the agent never called the Skill tool for {SKILL}, so the skill did not load")
    for result in (event for event in events(transcript) if event.get("type") == "result" and event.get("is_error")):
        failures.append(f"the agent stopped with {result.get('subtype')}: {'; '.join(result.get('errors') or [str(result.get('result'))])}")
    for kind, *arg in checks:
        ok, why = check(kind, arg[0] if arg else None, work, mock, said, inputs)
        if not ok:
            failures.append(why)
    if failures:
        failures.append(f"kept {work}, {claude_dir} and {log}")
    else:
        shutil.rmtree(work)
        shutil.rmtree(claude_dir)
        config.unlink()
        log.unlink()
    return failures


def main(names):
    unknown = sorted(set(names) - set(SCENARIOS))
    if unknown:
        sys.exit(f"unknown scenarios: {unknown}; known: {sorted(SCENARIOS)}")
    missing = [tool for tool in NEEDS if not shutil.which(tool)]
    if missing:
        sys.exit(f"not on PATH: {', '.join(missing)}; the runner needs {', '.join(NEEDS)}")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set; the agent runs with an empty config dir and signs in with that key")
    selected = names or list(SCENARIOS)
    failed = 0
    for name in selected:
        failures = run(name)
        print(("FAIL " if failures else "PASS ") + name, flush=True)
        for failure in failures:
            print("  - " + failure)
        failed += bool(failures)
    print(f"{len(selected) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
