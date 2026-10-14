"""Mock o11y-one MCP server and OTLP/HTTP sink, one process, for the eval harness.

/mcp speaks MCP Streamable HTTP with plain JSON responses. /v1/traces, /v1/logs and /v1/metrics accept
OTLP/HTTP protobuf, sized or chunked, carrying a key that create_ingestion_token.v1 returned.
get_onboarding_status.v1 reports what the sink received, so the skill's verify loop runs for real. Stdlib only.
"""
import gzip
import json
import secrets
import subprocess
import threading
import time
import urllib.request
from datetime import datetime, timezone
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

AUTH_HEADER = "x-o11y-key"
PLACEHOLDER = "<ingestion key>"
INGEST = "get_ingest_config.v1"
GUIDE = "get_instrumentation_guide.v1"
CREATE = "create_ingestion_token.v1"
STATUS = "get_onboarding_status.v1"
NO_ARGS = {"type": "object", "properties": {}}
TOOLS = {
    INGEST: ("OTLP endpoints, protocol, auth header and env lines for this org.", NO_ARGS),
    GUIDE: (
        "Packages, setup files, load hints, env, lockfile and verify commands for one service.",
        {
            "type": "object",
            "properties": {
                "language": {"type": "string", "enum": ["typescript", "javascript", "python", "go", "java"]},
                "framework": {
                    "type": "string",
                    "enum": ["express", "fastify", "nextjs", "fastapi", "django", "flask", "net_http", "gin", "echo", "spring", "none"],
                },
                "agent_framework": {"type": "string", "enum": ["langchain", "openai_agents", "vercel_ai", "crewai", "llamaindex"]},
                "service_name": {"type": "string"},
                "service_namespace": {"type": "string"},
                "module_type": {"type": "string", "enum": ["commonjs", "esm"]},
            },
            "required": ["language", "service_name"],
        },
    ),
    CREATE: (
        "Create an ingestion key. Owners and admins only.",
        {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    ),
    STATUS: (
        "Which signals this org has sent, and its latest trace, or the latest trace of one service.",
        {"type": "object", "properties": {"service_name": {"type": "string"}}},
    ),
}
LISTED = {"owner": set(TOOLS), "busy": set(TOOLS), "blackhole": set(TOOLS), "member": set(TOOLS) - {CREATE}, "stale": set()}

NODE_SETUP = """import { NodeSDK } from '@opentelemetry/sdk-node';
import { getNodeAutoInstrumentations } from '@opentelemetry/auto-instrumentations-node';

const sdk = new NodeSDK({ instrumentations: [getNodeAutoInstrumentations()] });
sdk.start();
"""
PY_SETUP = """from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

provider = TracerProvider(resource=Resource.create())
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
trace.set_tracer_provider(provider)
"""
PY_LANGCHAIN = PY_SETUP + """
from openinference.instrumentation.langchain import LangChainInstrumentor

LangChainInstrumentor().instrument(tracer_provider=provider)
"""
FASTAPI_HOOK = """from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

FastAPIInstrumentor.instrument_app(app)
"""


@lru_cache(maxsize=None)
def latest(manager, name):
    if manager == "npm":
        return subprocess.run(["npm", "view", name, "version"], capture_output=True, text=True, check=True).stdout.strip()
    with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/json", timeout=30) as response:
        return json.load(response)["info"]["version"]


def packages(manager, *names):
    return [{"name": name, "version": latest(manager, name), "manager_hint": manager} for name in names]


def recipe(args):
    language, framework = args.get("language"), args.get("framework", "none")
    agent, module = args.get("agent_framework"), args.get("module_type", "commonjs")
    service = args.get("service_name", "")
    env = [f"OTEL_SERVICE_NAME={service}", f"OTEL_RESOURCE_ATTRIBUTES=service.namespace={args.get('service_namespace') or service}"]
    node = ("npm", "@opentelemetry/sdk-node", "@opentelemetry/auto-instrumentations-node")
    if language == "javascript" and framework in ("express", "none") and not agent:
        return {
            "packages": packages(*node),
            "files": [{"path_hint": "tracing.mjs", "contents": NODE_SETUP, "load": "start_flag"}],
            "start_command": {"before_hint": "node <entrypoint>", "after": "node --import ./tracing.mjs <entrypoint>"},
            "env": env, "lockfile_refresh": ["npm install"], "verify": ["node --check tracing.mjs"],
        }
    if language == "typescript" and framework in ("express", "none") and module == "commonjs" and not agent:
        return {
            "packages": packages(*node),
            "files": [{"path_hint": "src/tracing.ts", "contents": NODE_SETUP, "load": "first_import"}],
            "env": env, "lockfile_refresh": ["npm install"], "verify": ["npm run build"],
        }
    if language == "python" and framework == "fastapi" and not agent:
        return {
            "packages": packages("pip", "opentelemetry-sdk", "opentelemetry-exporter-otlp-proto-http", "opentelemetry-instrumentation-fastapi"),
            "files": [
                {"path_hint": "telemetry.py", "contents": PY_SETUP, "load": "first_import"},
                {"path_hint": "<module that creates the FastAPI app>", "contents": FASTAPI_HOOK, "load": "framework_hook"},
            ],
            "env": env, "lockfile_refresh": [], "verify": ['python -c "import telemetry"'],
        }
    if language == "python" and framework == "none" and agent == "langchain":
        return {
            "packages": packages("pip", "opentelemetry-sdk", "opentelemetry-exporter-otlp-proto-http", "openinference-instrumentation-langchain"),
            "files": [{"path_hint": "telemetry.py", "contents": PY_LANGCHAIN, "load": "first_import"}],
            "env": env, "lockfile_refresh": [], "verify": ['python -c "import telemetry"'],
        }
    reason = f"the eval mock has no recipe for {language}/{framework}/{agent or 'no agent framework'}/{module}"
    return {"packages": [], "files": [], "env": [], "lockfile_refresh": [], "verify": [], "unsupported": reason}


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def varint(buf, i):
    shift = value = 0
    while True:
        byte = buf[i]
        i += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, i
        shift += 7


def fields(buf):
    i = 0
    while i < len(buf):
        key, i = varint(buf, i)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, i = varint(buf, i)
        elif wire == 1:
            value, i = buf[i:i + 8], i + 8
        elif wire == 2:
            size, i = varint(buf, i)
            value, i = buf[i:i + size], i + size
        elif wire == 5:
            value, i = buf[i:i + 4], i + 4
        else:
            raise ValueError(f"unsupported wire type {wire}")
        yield number, value


def parse_traces(body):
    """ExportTraceServiceRequest -> [(resource string attributes, [span])]."""
    batches = []
    for number, resource_spans in fields(body):
        if number != 1:
            continue
        attributes, spans = {}, []
        for field_number, value in fields(resource_spans):
            if field_number == 1:
                for kv_number, kv in fields(value):
                    if kv_number != 1:
                        continue
                    key = text = None
                    for part, data in fields(kv):
                        if part == 1:
                            key = data.decode()
                        elif part == 2:
                            text = next((v.decode() for n, v in fields(data) if n == 1), None)
                    if key is not None and text is not None:
                        attributes[key] = text
            elif field_number == 2:
                for scope_number, span_bytes in fields(value):
                    if scope_number != 2:
                        continue
                    span = {"trace_id": "", "parent": b"", "name": "", "start": 0, "end": 0}
                    for part, data in fields(span_bytes):
                        if part == 1:
                            span["trace_id"] = data.hex()
                        elif part == 4:
                            span["parent"] = data
                        elif part == 5:
                            span["name"] = data.decode()
                        elif part in (7, 8):
                            span["start" if part == 7 else "end"] = int.from_bytes(data, "little")
                    spans.append(span)
        batches.append((attributes, spans))
    return batches


class Mock:
    def __init__(self, mode):
        self.mode = mode
        self.lock = threading.Lock()
        self.tokens, self.calls, self.traces, self.guided = [], [], [], []
        self.rejected = 0
        self.received = {"traces": False, "logs": False, "metrics": False}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler(self))
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def rpc(self, message):
        if "id" not in message:
            return None
        method, params = message.get("method"), message.get("params") or {}
        if method == "initialize":
            result = {
                "protocolVersion": params.get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "o11y-one-mock", "version": "0"},
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": [{"name": n, "description": TOOLS[n][0], "inputSchema": TOOLS[n][1]} for n in sorted(LISTED[self.mode])]}
        elif method == "tools/call":
            name, args = params.get("name"), params.get("arguments") or {}
            with self.lock:
                self.calls.append((name, args, time.monotonic()))
            if name not in LISTED[self.mode]:
                error = {"code": -32003, "message": f"oauth token does not grant permission for tool `{name}`"}
                return {"jsonrpc": "2.0", "id": message["id"], "error": error}
            result = {"content": [{"type": "text", "text": json.dumps(self.tool(name, args))}], "isError": False}
        else:
            return {"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": f"method not found: {method}"}}
        return {"jsonrpc": "2.0", "id": message["id"], "result": result}

    def tool(self, name, args):
        if name == INGEST:
            return {
                "otlp_http_endpoint": self.base, "otlp_grpc_endpoint": self.base,
                "default_protocol": "http/protobuf", "auth_header": AUTH_HEADER,
                "env": {
                    "OTEL_EXPORTER_OTLP_ENDPOINT": self.base,
                    "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
                    "OTEL_EXPORTER_OTLP_HEADERS": f"{AUTH_HEADER}={PLACEHOLDER}",
                },
            }
        if name == GUIDE:
            with self.lock:
                self.guided.append(args.get("service_name", ""))
            return recipe(args)
        if name == CREATE:
            with self.lock:
                token = "TEST-" + secrets.token_hex(16)
                self.tokens.append(token)
                count = len(self.tokens)
            return {"token": token, "token_id": f"TEST-token-{count}", "expires_at": iso(time.time() + 365 * 86400),
                    "env_line": f"OTEL_EXPORTER_OTLP_HEADERS={AUTH_HEADER}={token}"}
        return self.status(args.get("service_name"))

    def status(self, service=None):
        with self.lock:
            if self.mode == "blackhole":
                old = {"trace_id": "0" * 32, "service_name": service or (self.guided or ["eval-node-api"])[0], "root_span_name": "GET /",
                       "duration_ms": 12.0, "ingested_at": iso(time.time() - 3 * 86400)}
                return {"has_sent_traces": True, "has_sent_logs": True, "has_sent_metrics": True, "latest_trace": old}
            if self.mode == "busy":
                self.received["traces"] = True
                self.traces.append({"service_name": "eval-other-service", "namespace": "eval-other", "trace_id": "f" * 32,
                                    "root_span_name": "GET /other", "duration_ms": 5.0, "ingested_at": time.time()})
            status = {f"has_sent_{signal}": seen for signal, seen in self.received.items()}
            matching = [trace for trace in self.traces if service is None or trace["service_name"] == service]
            if matching:
                latest_trace = {k: matching[-1][k] for k in ("trace_id", "service_name", "root_span_name", "duration_ms")}
                latest_trace["ingested_at"] = iso(matching[-1]["ingested_at"])
                status["latest_trace"] = latest_trace
            elif service is not None:
                status["latest_trace"] = None
            return status

    def otlp(self, signal, headers, body):
        if headers.get(AUTH_HEADER) not in self.tokens:
            with self.lock:
                self.rejected += 1
            return 401
        if "protobuf" not in (headers.get("Content-Type") or ""):
            return 415
        if headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
        batches = parse_traces(body) if signal == "traces" else []
        now = time.time()
        with self.lock:
            self.received[signal] = True
            for attributes, spans in batches:
                for span in [s for s in spans if not s["parent"]] or spans[:1]:
                    self.traces.append({
                        "service_name": attributes.get("service.name", ""),
                        "namespace": attributes.get("service.namespace", ""),
                        "trace_id": span["trace_id"], "root_span_name": span["name"],
                        "duration_ms": (span["end"] - span["start"]) / 1e6, "ingested_at": now,
                    })
        return 200


def handler(mock):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.reply(405)

        do_DELETE = do_GET

        def body(self):
            if "chunked" not in (self.headers.get("Transfer-Encoding") or "").lower():
                return self.rfile.read(int(self.headers.get("Content-Length") or 0))
            chunks = []
            while size := int(self.rfile.readline().split(b";")[0], 16):
                chunks.append(self.rfile.read(size))
                self.rfile.readline()
            while self.rfile.readline().strip():  # trailer fields, up to the blank line
                pass
            return b"".join(chunks)

        def do_POST(self):
            body = self.body()
            if self.path == "/mcp":
                answer = mock.rpc(json.loads(body or b"{}"))
                if answer is None:
                    return self.reply(202)
                return self.reply(200, json.dumps(answer).encode(), "application/json")
            signal = self.path.rsplit("/", 1)[-1]
            if self.path.startswith("/v1/") and signal in mock.received:
                try:
                    return self.reply(mock.otlp(signal, self.headers, body))
                except (ValueError, IndexError, UnicodeDecodeError, OSError):  # OSError covers a bad gzip body
                    return self.reply(400)
            self.reply(404)

        def reply(self, code, data=b"", content_type="application/x-protobuf"):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler
