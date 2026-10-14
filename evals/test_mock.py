#!/usr/bin/env python3
"""Self-check for mock_o11y.py: MCP replies in the real envelope, refusals in data.code, modes, key handling, OTLP decoding of protobuf, JSON, sized and chunked bodies, status with and without service_name, and the guides' shape. No agent, no network."""
import calendar
import gzip
import http.client
import json
import re
import time
import urllib.error
import urllib.request

from mock_o11y import AUTH_HEADER, CREATE, GUIDE, INGEST, STATUS, TOOLS, Mock


def varint(value):
    out = bytearray()
    while True:
        byte, value = value & 0x7F, value >> 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def field(number, payload):
    return varint(number << 3 | 2) + varint(len(payload)) + payload


def fixed64(number, value):
    return varint(number << 3 | 1) + value.to_bytes(8, "little")


def export_request(service, namespace, span_name):
    attributes = b"".join(
        field(1, field(1, key.encode()) + field(2, field(1, value.encode())))
        for key, value in (("service.name", service), ("service.namespace", namespace))
    )
    span = field(1, bytes(range(16))) + field(2, bytes(range(8))) + field(5, span_name.encode())
    span += fixed64(7, 1_000_000_000) + fixed64(8, 1_250_000_000)
    return field(1, field(1, attributes) + field(2, field(2, span)))


def json_request(service, span_name):
    resource = {"attributes": [{"key": "service.name", "value": {"stringValue": service}}]}
    span = {"traceId": "ab" * 16, "spanId": "cd" * 8, "name": span_name, "startTimeUnixNano": "1000000000", "endTimeUnixNano": 1_250_000_000}
    return json.dumps({"resourceSpans": [{"resource": resource, "scopeSpans": [{"spans": [span]}]}]}).encode()


def post(url, body, headers):
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def malformed_chunk(mock):
    connection = http.client.HTTPConnection("127.0.0.1", mock.server.server_address[1], timeout=10)
    try:
        connection.request("POST", "/v1/traces", b"zz\r\nnot a chunk\r\n0\r\n\r\n", {"Transfer-Encoding": "chunked"})
        return connection.getresponse().status
    finally:
        connection.close()


def rpc(mock, method, params=None):
    message = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    status, body = post(f"{mock.base}/mcp", json.dumps(message).encode(), {"Content-Type": "application/json"})
    assert status == 200, status
    return json.loads(body)


def call(mock, tool, arguments=None):
    """The tool's payload, read from under `result` as a client would, or the JSON-RPC error."""
    reply = rpc(mock, "tools/call", {"name": tool, "arguments": arguments or {}})
    if "error" in reply:
        return reply["error"]
    answer = reply["result"]
    envelope = answer["structuredContent"]
    assert answer["isError"] is False and json.loads(answer["content"][0]["text"]) == envelope
    assert envelope["meta"]["tool"] == tool and envelope["meta"]["envelope_format"] == "mcp_response_envelope.v1"
    assert envelope["correlation_ids"] == envelope["audit"]["correlation_ids"] and envelope["audit"]["outcome"] == "success"
    return envelope["result"]


def refused(error, code, slug):
    assert (error["code"], error["data"]["code"]) == (code, slug), error
    assert error["message"].startswith(f"{slug}: ") and error["data"]["audit"]["rejection_reason"] == error["message"]


def listed(mock):
    return {tool["name"] for tool in rpc(mock, "tools/list")["result"]["tools"]}


def guides(mock):
    def guide(**args):
        return call(mock, GUIDE, {"service_name": "eval-svc", **args})

    ts = guide(language="typescript", framework="express")
    assert [f["load"] for f in ts["files"]] == ["first_import", "first_import"] and "start_command" not in ts
    assert ts["files"][1]["contents"] == "import './tracing';\n" and ts["verify"] == ["npx tsc --noEmit"]
    assert f"url: '{mock.base}/v1/traces'" in ts["files"][0]["contents"]
    js = guide(language="javascript", framework="none", service_namespace="eval-ns")
    assert js["start_command"]["after"] == "node --import ./tracing.mjs <entrypoint>.js" and js["verify"] == ["node --check tracing.mjs"]
    assert "'service.namespace': 'eval-ns'" in js["files"][0]["contents"]
    py = guide(language="python", framework="fastapi")
    assert [f["load"] for f in py["files"]] == ["first_import", "first_import", "framework_hook"]
    lc = guide(language="python", agent_framework="langchain")["files"][0]["contents"]
    assert lc.index(" import LangChainInstrumentor\n") < lc.index("from opentelemetry import trace")
    assert lc.endswith("\nLangChainInstrumentor().instrument()\n")
    for answer in (ts, js, py):
        assert f"OTEL_EXPORTER_OTLP_HEADERS={AUTH_HEADER}=<ingestion key>" in answer["env"]
        assert not any(line.startswith("OTEL_RESOURCE_ATTRIBUTES=") for line in answer["env"])
        assert all(package["version"][0].isdigit() for package in answer["packages"])
    assert "unsupported" in guide(language="java")


def owner():
    mock = Mock("owner")
    try:
        assert rpc(mock, "initialize", {"protocolVersion": "2025-06-18"})["result"]["protocolVersion"] == "2025-06-18"
        notification = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode()
        assert post(f"{mock.base}/mcp", notification, {"Content-Type": "application/json"})[0] == 202
        assert listed(mock) == set(TOOLS)
        config = call(mock, INGEST)
        assert config["auth_header"] == AUTH_HEADER and config["env"]["OTEL_EXPORTER_OTLP_ENDPOINT"] == mock.base
        guides(mock)
        assert "latest_trace" not in call(mock, STATUS)
        assert call(mock, STATUS, {"service_name": "eval-svc"})["latest_trace"] is None
        blank = call(mock, STATUS, {"service_name": " "})
        assert blank["code"] == -32602 and "code" not in blank["data"], blank
        body = export_request("eval-svc", "eval-ns", "GET /")
        protobuf = {"Content-Type": "application/x-protobuf"}
        assert post(f"{mock.base}/v1/traces", body, protobuf)[0] == 401
        name_rule = f"{CREATE} name must be 1 to 100 characters"
        for arguments, message in (({"name": " "}, name_rule), ({"name": "x" * 101}, name_rule),
                                   ({}, f"invalid {CREATE} args: missing field `name`"),
                                   ({"name": 5}, f"invalid {CREATE} args: invalid type"),
                                   ({"name": "eval", "ttl": 1}, f"invalid {CREATE} args: unknown field `ttl`")):
            error = call(mock, CREATE, arguments)
            assert error["code"] == -32602 and error["message"].startswith(message) and "code" not in error["data"], (arguments, error)
        assert not mock.tokens
        token = call(mock, CREATE, {"name": "eval"})["token"]
        assert token.startswith("TEST-")
        assert post(f"{mock.base}/v1/traces", body, {AUTH_HEADER: token, "Content-Type": "application/grpc"})[0] == 415
        gzipped = {**protobuf, AUTH_HEADER: token, "Content-Encoding": "gzip"}
        assert post(f"{mock.base}/v1/traces", gzip.compress(body), gzipped)[0] == 200
        status = call(mock, STATUS, {"service_name": "eval-svc"})
        latest = status["latest_trace"]
        assert status["has_sent_traces"] and not status["has_sent_logs"]
        assert (latest["service_name"], latest["root_span_name"], latest["duration_ms"]) == ("eval-svc", "GET /", 250.0)
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{9}Z", latest["ingested_at"]), latest["ingested_at"]
        assert mock.traces[0]["namespace"] == "eval-ns"
        assert call(mock, STATUS, {"service_name": "eval-other"})["latest_trace"] is None
        chunked = export_request("eval-chunked", "eval-ns", "GET /chunked")
        assert post(f"{mock.base}/v1/traces", iter([chunked[:9], chunked[9:]]), {**protobuf, AUTH_HEADER: token})[0] == 200
        assert call(mock, STATUS, {"service_name": "eval-chunked"})["latest_trace"]["root_span_name"] == "GET /chunked"
        assert post(f"{mock.base}/v1/traces", json_request("eval-json", "GET /json"), {AUTH_HEADER: token, "Content-Type": "application/json"})[0] == 200
        assert call(mock, STATUS, {"service_name": "eval-json"})["latest_trace"]["duration_ms"] == 250.0
        assert malformed_chunk(mock) == 400
        assert post(f"{mock.base}/mcp", b"{not json", {"Content-Type": "application/json"})[0] == 400
        for _ in range(4):
            assert call(mock, CREATE, {"name": "eval"})["token"].startswith("TEST-")
        refused(call(mock, CREATE, {"name": "eval"}), -32004, "hourly_limit_reached")
        assert len(mock.tokens) == 5
    finally:
        mock.close()


def member():
    """A member's grant has no write permission: the key tool is unlisted, and a call to it is the permission error, with no data."""
    mock = Mock("member")
    try:
        assert listed(mock) == set(TOOLS) - {CREATE}
        error = call(mock, CREATE, {"name": "eval"})
        assert error == {"code": -32003, "message": f"oauth token does not grant permission for tool `{CREATE}`"}, error
        assert not mock.tokens
        assert call(mock, INGEST)["auth_header"] == AUTH_HEADER
    finally:
        mock.close()


def demoted():
    """A grant that still carries the write permission is refused by the live role check, its code in data.code, and mints nothing."""
    mock = Mock("demoted")
    try:
        assert listed(mock) == set(TOOLS)
        refused(call(mock, CREATE, {"name": "eval"}), -32003, "not_owner_or_admin")
        assert not mock.tokens
        assert call(mock, INGEST)["auth_header"] == AUTH_HEADER
    finally:
        mock.close()


def other_modes():
    for mode, tools in (("stale", set()), ("blackhole", set(TOOLS)), ("busy", set(TOOLS))):
        mock = Mock(mode)
        try:
            assert listed(mock) == tools, mode
            if mode == "stale":
                error = call(mock, STATUS)
                assert error["code"] == -32003 and "data" not in error and "does not grant permission" in error["message"]
            if mode == "blackhole":
                ingested = call(mock, STATUS)["latest_trace"]["ingested_at"]
                assert time.time() - calendar.timegm(time.strptime(ingested[:19], "%Y-%m-%dT%H:%M:%S")) > 86400
            if mode == "busy":
                assert call(mock, STATUS)["latest_trace"]["service_name"] == "eval-other-service"
                assert call(mock, STATUS, {"service_name": "eval-svc"})["latest_trace"] is None
        finally:
            mock.close()


if __name__ == "__main__":
    owner()
    member()
    demoted()
    other_modes()
    print("mock ok")
