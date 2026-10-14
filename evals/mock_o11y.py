"""Mock o11y-one MCP server and OTLP/HTTP sink, one process, for the eval harness.

/mcp speaks MCP Streamable HTTP with plain JSON responses. A tool answers as the real server's onboarding tools
do: its payload under `result` in mcp_response_envelope.v1, both as structuredContent and as JSON text, and a
refusal as a JSON-RPC error whose code leads its message and is repeated in data.code. /v1/traces, /v1/logs and
/v1/metrics accept OTLP/HTTP protobuf or JSON, sized or chunked, carrying a key that create_ingestion_token.v1
returned. get_onboarding_status.v1 reports what the sink received, so the skill's verify loop runs for real.
get_instrumentation_guide.v1 answers as the real server's guides.rs does for the fixtures' stacks, with the
versions its versions.rs pins; it never looks a version up. Stdlib only.
"""
import gzip
import hashlib
import json
import secrets
import threading
import time
import uuid
from datetime import datetime, timezone
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
# A member is granted read tools only, so the key tool is unlisted. A demoted owner's grant still carries its write
# permission, so the call reaches the live role check and is refused there.
LISTED = {"owner": set(TOOLS), "busy": set(TOOLS), "blackhole": set(TOOLS), "member": set(TOOLS) - {CREATE},
          "demoted": set(TOOLS), "stale": set()}
MINTS_PER_HOUR = 5
TENANT = "00000000-0000-4000-8000-00000000e7a1"

# The real server's pins, from its versions.rs.
PINNED = {
    "@opentelemetry/sdk-node": "0.222.0",
    "@opentelemetry/api": "1.9.1",
    "@opentelemetry/exporter-trace-otlp-http": "0.222.0",
    "@opentelemetry/resources": "2.11.0",
    "@opentelemetry/auto-instrumentations-node": "0.80.0",
    "opentelemetry-api": "1.45.0",
    "opentelemetry-sdk": "1.45.0",
    "opentelemetry-exporter-otlp-proto-http": "1.45.0",
    "opentelemetry-instrumentation-fastapi": "0.66b0",
    "openinference-instrumentation-langchain": "0.1.79",
}
NODE_PACKAGES = ["@opentelemetry/sdk-node", "@opentelemetry/api", "@opentelemetry/exporter-trace-otlp-http", "@opentelemetry/resources",
                 "@opentelemetry/auto-instrumentations-node"]
PY_PACKAGES = ["opentelemetry-api", "opentelemetry-sdk", "opentelemetry-exporter-otlp-proto-http"]
TS_TRACING = """import { getNodeAutoInstrumentations } from '@opentelemetry/auto-instrumentations-node';
import { NodeSDK } from '@opentelemetry/sdk-node';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';
import { resourceFromAttributes } from '@opentelemetry/resources';

const sdk = new NodeSDK({
  resource: resourceFromAttributes({
    'service.name': '{{service_name}}',
    'service.namespace': '{{service_namespace}}',
    'service.version': process.env['GIT_SHA'],
    'deployment.environment.name': process.env['DEPLOYMENT_ENVIRONMENT'],
  }),
  traceExporter: new OTLPTraceExporter({ url: '{{otlp_endpoint}}/v1/traces' }),
  instrumentations: [getNodeAutoInstrumentations()],
});

sdk.start();
"""
PY_TELEMETRY = """import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

resource = Resource.create(
    {
        "service.name": "{{service_name}}",
        "service.namespace": "{{service_namespace}}",
        "service.version": os.environ.get("GIT_SHA", ""),
        "deployment.environment.name": os.environ.get("DEPLOYMENT_ENVIRONMENT", ""),
    }
)
provider = TracerProvider(resource=resource)
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint="{{otlp_endpoint}}/v1/traces")))
trace.set_tracer_provider(provider)
"""
FASTAPI_HOOK = "from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor\n\nFastAPIInstrumentor.instrument_app(app)\n"
LANGCHAIN_IMPORT = "from openinference.instrumentation.langchain import LangChainInstrumentor\n"
LANGCHAIN_CALL = "LangChainInstrumentor().instrument()\n"


def fill(template, values):
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def packages(manager, names):
    return [{"name": name, "version": PINNED[name], "manager_hint": manager} for name in names]


def file(path_hint, contents, load):
    return {"path_hint": path_hint, "contents": contents, "load": load}


def recipe(args, endpoint):
    """Node.js CommonJS with Express or no framework, and Python with FastAPI or LangChain or both. Anything else is unsupported."""
    language, agent = args.get("language"), args.get("agent_framework")
    framework = None if args.get("framework") in (None, "none") else args["framework"]
    module = args.get("module_type") or "commonjs"
    service = args.get("service_name", "")
    values = {"service_name": service, "service_namespace": args.get("service_namespace") or service, "otlp_endpoint": endpoint}
    env = [f"OTEL_EXPORTER_OTLP_ENDPOINT={endpoint}", f"OTEL_SERVICE_NAME={service}", f"OTEL_EXPORTER_OTLP_HEADERS={AUTH_HEADER}={PLACEHOLDER}",
           "GIT_SHA=<the deployed commit SHA>", "DEPLOYMENT_ENVIRONMENT=<the deployment environment, e.g. production>"]
    if language in ("typescript", "javascript") and framework in (None, "express") and module == "commonjs" and not agent:
        tracing = fill(TS_TRACING, values)
        answer = {"packages": packages("npm", NODE_PACKAGES)}
        if language == "typescript":
            answer["files"] = [file("tracing.ts, beside the entrypoint", tracing, "first_import"),
                               file("the entrypoint's first line, before any other import", "import './tracing';\n", "first_import")]
            verify = "npx tsc --noEmit"
        else:
            answer["files"] = [file("tracing.mjs, beside the entrypoint", tracing, "start_flag")]
            answer["start_command"] = {"before_hint": "node <entrypoint>.js, the start script in package.json",
                                       "after": "node --import ./tracing.mjs <entrypoint>.js"}
            verify = "node --check tracing.mjs"
        return {**answer, "env": env, "lockfile_refresh": ["pnpm install", "npm install", "yarn"], "verify": [verify]}
    if language == "python" and framework in (None, "fastapi") and agent in (None, "langchain"):
        names = PY_PACKAGES + (["opentelemetry-instrumentation-fastapi"] if framework else [])
        names += ["openinference-instrumentation-langchain"] if agent else []
        telemetry = fill(PY_TELEMETRY, values)
        if agent:
            telemetry = telemetry.replace("from opentelemetry", LANGCHAIN_IMPORT + "from opentelemetry", 1) + "\n" + LANGCHAIN_CALL
        files = [file("telemetry.py, beside the entrypoint", telemetry, "first_import"),
                 file("the entrypoint's first import", "import telemetry  # noqa: F401\n", "first_import")]
        if framework:
            files.append(file("right after `app = FastAPI(...)`", FASTAPI_HOOK, "framework_hook"))
        return {"packages": packages("pip", names), "files": files, "env": env,
                "lockfile_refresh": ["uv lock", "poetry lock"], "verify": ["python -m py_compile telemetry.py"]}
    reason = f"the eval mock has no guide for {language}/{framework or 'none'}/{agent or 'no agent framework'}/{module}"
    return {"packages": [], "files": [], "env": [], "lockfile_refresh": [], "verify": [], "unsupported": reason}


def rfc3339(nanos):
    """UTC with nanoseconds, as the real server writes ingested_at."""
    seconds, fraction = divmod(nanos, 10**9)
    return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + f".{fraction:09d}Z"


class Fault(Exception):
    """The real McpRpcFault. A refusal's slug leads the message, which is what a client shows the model, and is data.code."""

    def __init__(self, code, sentence, slug=None):
        super().__init__(f"{slug}: {sentence}" if slug else sentence)
        self.code, self.data = code, {"code": slug} if slug else {}


def audit(name, args, rejection, correlation_ids):
    return {
        "occurred_at": rfc3339(time.time_ns()), "invocation_id": str(uuid.uuid4()), "tool_name": name,
        "tenant_id": TENANT, "org_id": TENANT, "user_id": TENANT, "scope_summary": "context=null|baseline=null|comparison=null",
        "params_hash": hashlib.sha256(json.dumps({"arguments": args, "tool_name": name}, sort_keys=True).encode()).hexdigest(),
        "outcome": "rejected" if rejection else "success", "rejection_reason": rejection, "latency_ms": 1,
        "correlation_ids": sorted(set(correlation_ids)),
    }


def envelope(name, payload, record):
    """mcp_success_envelope, for a payload with no rows, warnings or cursor."""
    return {
        "result": payload,
        "meta": {"tool": name, "envelope_format": "mcp_response_envelope.v1", "result_format": "json_v1", "row_count": 0,
                 "truncated": False, "next_cursor": None},
        "execution": {"latency_ms": record["latency_ms"]}, "warnings": [], "audit": record,
        "correlation_ids": record["correlation_ids"], "suggested_next_calls": [],
    }


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


def parse_json_traces(body):
    """OTLP/JSON, which the guide's Node exporter sends and the real ingest accepts -> what parse_traces returns."""
    batches = []
    for resource_spans in json.loads(body).get("resourceSpans", []):
        attributes = {a.get("key"): a["value"]["stringValue"] for a in resource_spans.get("resource", {}).get("attributes", [])
                      if "stringValue" in a.get("value", {})}
        spans = [{"trace_id": span.get("traceId", ""), "parent": span.get("parentSpanId") or b"", "name": span.get("name", ""),
                  "start": int(span.get("startTimeUnixNano") or 0), "end": int(span.get("endTimeUnixNano") or 0)}
                 for scope in resource_spans.get("scopeSpans", []) for span in scope.get("spans", [])]
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
            try:
                payload, correlation_ids = self.tool(name, args)
            except Fault as fault:
                data = {**fault.data, "audit": audit(name, args, str(fault), [])}
                return {"jsonrpc": "2.0", "id": message["id"], "error": {"code": fault.code, "message": str(fault), "data": data}}
            answer = envelope(name, payload, audit(name, args, None, correlation_ids))
            result = {"content": [{"type": "text", "text": json.dumps(answer, separators=(",", ":"))}],
                      "structuredContent": answer, "isError": False}
        else:
            return {"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": f"method not found: {method}"}}
        return {"jsonrpc": "2.0", "id": message["id"], "result": result}

    def tool(self, name, args):
        """The payload and its correlation ids, or a Fault."""
        if name == INGEST:
            return {
                "otlp_http_endpoint": self.base, "otlp_grpc_endpoint": self.base,
                "default_protocol": "http/protobuf", "auth_header": AUTH_HEADER,
                "env": {
                    "OTEL_EXPORTER_OTLP_ENDPOINT": self.base,
                    "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
                    "OTEL_EXPORTER_OTLP_HEADERS": f"{AUTH_HEADER}={PLACEHOLDER}",
                },
            }, []
        if name == GUIDE:
            with self.lock:
                self.guided.append(args.get("service_name", ""))
            return recipe(args, self.base), []
        if name == CREATE:
            # CreateIngestionTokenV1Args: serde's deny_unknown_fields over one required string, `name`.
            extra = sorted(set(args) - {"name"})
            if extra or not isinstance(args.get("name"), str):
                detail = (f"unknown field `{extra[0]}`, expected `name`" if extra else "missing field `name`" if "name" not in args
                          else f"invalid type: `{json.dumps(args['name'])}`, expected a string")
                raise Fault(-32602, f"invalid {CREATE} args: {detail}")
            return self.mint(args["name"].strip())
        return self.status(args.get("service_name"))

    def mint(self, name):
        if not 1 <= len(name) <= 100:
            raise Fault(-32602, f"{CREATE} name must be 1 to 100 characters")
        if self.mode == "demoted":
            raise Fault(-32003, "only an organization's owners and admins create ingestion keys; ask one, or paste a key you were given",
                        "not_owner_or_admin")
        with self.lock:
            if len(self.tokens) >= MINTS_PER_HOUR:
                raise Fault(-32004, "five keys an hour per person have been created over MCP; reuse one, or try again later",
                            "hourly_limit_reached")
            token = "TEST-" + secrets.token_hex(16)
            self.tokens.append(token)
            token_id = f"TEST-token-{len(self.tokens)}"
        return {"token": token, "token_id": token_id, "expires_at": rfc3339(time.time_ns() + 365 * 86400 * 10**9),
                "env_line": f"OTEL_EXPORTER_OTLP_HEADERS={AUTH_HEADER}={token}"}, [token_id]

    def status(self, service=None):
        if service is not None and not str(service).strip():
            raise Fault(-32602, f"invalid {STATUS} args: service_name must not be blank")
        with self.lock:
            if self.mode == "blackhole":
                old = {"trace_id": "0" * 32, "service_name": service or (self.guided or ["eval-node-api"])[0], "root_span_name": "GET /",
                       "duration_ms": 12.0, "ingested_at": rfc3339(time.time_ns() - 3 * 86400 * 10**9)}
                return {"has_sent_traces": True, "has_sent_logs": True, "has_sent_metrics": True, "latest_trace": old}, [old["trace_id"]]
            if self.mode == "busy":
                self.received["traces"] = True
                self.traces.append({"service_name": "eval-other-service", "namespace": "eval-other", "trace_id": "f" * 32,
                                    "root_span_name": "GET /other", "duration_ms": 5.0, "ingested_at": time.time_ns()})
            status = {f"has_sent_{signal}": seen for signal, seen in self.received.items()}
            matching = [trace for trace in self.traces if service is None or trace["service_name"] == service]
            if matching:
                latest_trace = {k: matching[-1][k] for k in ("trace_id", "service_name", "root_span_name", "duration_ms")}
                latest_trace["ingested_at"] = rfc3339(matching[-1]["ingested_at"])
                status["latest_trace"] = latest_trace
                return status, [latest_trace["trace_id"]]
            if service is not None:
                status["latest_trace"] = None
            return status, []

    def otlp(self, signal, headers, body):
        if headers.get(AUTH_HEADER) not in self.tokens:
            with self.lock:
                self.rejected += 1
            return 401
        content_type = headers.get("Content-Type") or ""
        if content_type.startswith("application/json"):
            parse = parse_json_traces
        elif "protobuf" in content_type:
            parse = parse_traces
        else:
            return 415
        if headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
        batches = parse(body) if signal == "traces" else []
        now = time.time_ns()
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
            signal = self.path.rsplit("/", 1)[-1]
            try:
                body = self.body()
                if self.path == "/mcp":
                    message = json.loads(body or b"{}")
                elif self.path.startswith("/v1/") and signal in mock.received:
                    return self.reply(mock.otlp(signal, self.headers, body))
                else:
                    return self.reply(404)
            except (ValueError, IndexError, TypeError, AttributeError, UnicodeDecodeError, OSError):  # OSError covers a bad gzip body
                return self.reply(400)
            answer = mock.rpc(message)
            if answer is None:
                return self.reply(202)
            self.reply(200, json.dumps(answer).encode(), "application/json")

        def reply(self, code, data=b"", content_type="application/x-protobuf"):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler
