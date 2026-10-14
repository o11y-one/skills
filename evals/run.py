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
TIMEOUT_S = 20 * 60
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


def called_skill(transcript):
    blocks = [block for event in events(transcript) if event.get("type") == "assistant" for block in event.get("message", {}).get("content", [])]
    return any(block.get("type") == "tool_use" and block.get("name") == "Skill" and block.get("input", {}).get("skill") == SKILL for block in blocks)


def check(kind, arg, work, mock, said):
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
        return not any(token in said for token in mock.tokens), "the agent printed the key"
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


def stop_leftovers(pgid, ports):
    # ponytail: kills the agent's process group and whatever listens on the fixture's ports; an app the agent detached on another port outlives the run
    pids = []
    for port in ports:
        pids += subprocess.run(["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"], capture_output=True, text=True).stdout.split()
    for kill, target in [(os.killpg, pgid)] + [(os.kill, int(pid)) for pid in pids]:
        try:
            kill(target, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def run(name):
    fixture, mode, ports, checks = SCENARIOS[name]
    work = Path(tempfile.mkdtemp(prefix=f"o11y-eval-{name}-"))
    shutil.copytree(FIXTURES / fixture, work, dirs_exist_ok=True)
    for args in (["init", "-q"], ["add", "-A"], ["-c", "user.name=eval", "-c", "user.email=eval@example.test", "commit", "-qm", "fixture"]):
        git(work, *args)
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
        "--output-format", "stream-json", "--verbose", "--no-session-persistence",
    ]
    failures = []
    agent = subprocess.Popen(command, cwd=work, env={**os.environ, "CLAUDE_CONFIG_DIR": str(claude_dir)}, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    try:
        transcript, _ = agent.communicate(timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        os.killpg(agent.pid, signal.SIGKILL)
        transcript, _ = agent.communicate()
        failures.append(f"timed out after {TIMEOUT_S}s")
    finally:
        stop_leftovers(agent.pid, ports)
        mock.close()
    log = work.with_name(work.name + "-transcript.jsonl")
    log.write_text(transcript)
    said = assistant_text(transcript)
    if not called_skill(transcript):
        failures.append(f"the agent never called the Skill tool for {SKILL}, so the skill did not load")
    for kind, *arg in checks:
        ok, why = check(kind, arg[0] if arg else None, work, mock, said)
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
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set; the agent runs with an empty config dir, so it has no other login")
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
