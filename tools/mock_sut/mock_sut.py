#!/usr/bin/env python3
"""Deterministic local HTTP stub for Gatling-AI smoke runs.

Behavior is fully declared by a JSON route config; there is no response
synthesis. Prints "READY <port>" to stdout once listening.
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


def load_routes(config_path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError(f"route config must be a JSON object, got {type(config).__name__}")
    base_dir = config_path.parent
    routes: dict[tuple[str, str], dict[str, Any]] = {}
    for route in config.get("routes", []):
        if not isinstance(route, dict) or "path" not in route:
            raise ValueError(f"invalid route entry: {route!r}")
        method = str(route.get("method", "GET")).upper()
        path = str(route["path"])
        if "body_file" in route:
            body = (base_dir / str(route["body_file"])).read_bytes()
        elif "body" in route:
            body = str(route["body"]).encode("utf-8")
        else:
            body = b""
        headers = {
            str(key): str(value) for key, value in (route.get("headers") or {}).items()
        }
        routes[(method, path)] = {
            "status": int(route.get("status", 200)),
            "headers": headers,
            "body": body,
        }
    return routes


def make_handler(routes: dict[tuple[str, str], dict[str, Any]]):
    class MockHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _drain_request_body(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)

        def _respond(self) -> None:
            self._drain_request_body()
            path = self.path.split("?", 1)[0]
            if path == "/__health":
                self._send(200, {"Content-Type": "text/plain"}, b"ok")
                return
            route = routes.get((self.command, path))
            if route is None:
                self._send(404, {"Content-Type": "text/plain"}, b"no such route")
                return
            self._send(route["status"], route["headers"], route["body"])

        def _send(self, status: int, headers: dict[str, str], body: bytes) -> None:
            self.send_response(status)
            skip = {"content-length", "transfer-encoding"}
            for key, value in headers.items():
                if key.lower() not in skip:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            self._respond()

        def do_POST(self) -> None:
            self._respond()

        def do_PUT(self) -> None:
            self._respond()

        def do_PATCH(self) -> None:
            self._respond()

        def do_DELETE(self) -> None:
            self._respond()

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            pass  # deterministic, quiet runs

    return MockHandler


def serve(routes_path: Path, host: str, port: int) -> ThreadingHTTPServer:
    routes = load_routes(routes_path)
    return ThreadingHTTPServer((host, port), make_handler(routes))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deterministic mock SUT for smoke runs")
    parser.add_argument("--routes", required=True, type=Path, help="JSON route config")
    parser.add_argument("--host", default="127.0.0.1", help="bind host")
    parser.add_argument("--port", default=0, type=int, help="bind port (0 = ephemeral)")
    args = parser.parse_args(argv)

    try:
        server = serve(args.routes, args.host, args.port)
    except Exception as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 1

    print(f"READY {server.server_address[1]}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
