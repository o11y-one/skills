#!/usr/bin/env python3
"""Self-check for mock_o11y.py: MCP replies, modes, key handling, OTLP decoding of sized and chunked bodies, and status with and without service_name. No agent, no network."""
import calendar
import gzip
import http.client
import json
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
    reply = rpc(mock, "tools/call", {"name": tool, "arguments": arguments or {}})
    return reply["error"] if "error" in reply else json.loads(reply["result"]["content"][0]["text"])


def listed(mock):
    return {tool["name"] for tool in rpc(mock, "tools/list")["result"]["tools"]}


def owner():
    mock = Mock("owner")
    try:
        assert rpc(mock, "initialize", {"protocolVersion": "2025-06-18"})["result"]["protocolVersion"] == "2025-06-18"
        notification = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode()
        assert post(f"{mock.base}/mcp", notification, {"Content-Type": "application/json"})[0] == 202
        assert listed(mock) == set(TOOLS)
        config = call(mock, INGEST)
        assert config["auth_header"] == AUTH_HEADER and config["env"]["OTEL_EXPORTER_OTLP_ENDPOINT"] == mock.base
        assert "unsupported" in call(mock, GUIDE, {"language": "java", "service_name": "eval-java"})
        assert "latest_trace" not in call(mock, STATUS)
        assert call(mock, STATUS, {"service_name": "eval-svc"})["latest_trace"] is None
        body = export_request("eval-svc", "eval-ns", "GET /")
        protobuf = {"Content-Type": "application/x-protobuf"}
        assert post(f"{mock.base}/v1/traces", body, protobuf)[0] == 401
        token = call(mock, CREATE, {"name": "eval"})["token"]
        assert token.startswith("TEST-")
        assert post(f"{mock.base}/v1/traces", body, {AUTH_HEADER: token, "Content-Type": "application/json"})[0] == 415
        gzipped = {**protobuf, AUTH_HEADER: token, "Content-Encoding": "gzip"}
        assert post(f"{mock.base}/v1/traces", gzip.compress(body), gzipped)[0] == 200
        status = call(mock, STATUS, {"service_name": "eval-svc"})
        latest = status["latest_trace"]
        assert status["has_sent_traces"] and not status["has_sent_logs"]
        assert (latest["service_name"], latest["root_span_name"], latest["duration_ms"]) == ("eval-svc", "GET /", 250.0)
        assert mock.traces[0]["namespace"] == "eval-ns"
        assert call(mock, STATUS, {"service_name": "eval-other"})["latest_trace"] is None
        chunked = export_request("eval-chunked", "eval-ns", "GET /chunked")
        assert post(f"{mock.base}/v1/traces", iter([chunked[:9], chunked[9:]]), {**protobuf, AUTH_HEADER: token})[0] == 200
        assert call(mock, STATUS, {"service_name": "eval-chunked"})["latest_trace"]["root_span_name"] == "GET /chunked"
        assert malformed_chunk(mock) == 400
        assert post(f"{mock.base}/mcp", b"{not json", {"Content-Type": "application/json"})[0] == 400
    finally:
        mock.close()


def other_modes():
    for mode, tools in (("member", set(TOOLS) - {CREATE}), ("stale", set()), ("blackhole", set(TOOLS)), ("busy", set(TOOLS))):
        mock = Mock(mode)
        try:
            assert listed(mock) == tools, mode
            if mode == "member":
                assert call(mock, CREATE, {"name": "eval"})["code"] == -32003
            if mode == "blackhole":
                ingested = call(mock, STATUS)["latest_trace"]["ingested_at"]
                assert time.time() - calendar.timegm(time.strptime(ingested, "%Y-%m-%dT%H:%M:%SZ")) > 86400
            if mode == "busy":
                assert call(mock, STATUS)["latest_trace"]["service_name"] == "eval-other-service"
                assert call(mock, STATUS, {"service_name": "eval-svc"})["latest_trace"] is None
        finally:
            mock.close()


if __name__ == "__main__":
    owner()
    other_modes()
    print("mock ok")
