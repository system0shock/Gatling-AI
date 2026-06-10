#!/usr/bin/env python3
"""Unit tests for the mock SUT server."""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import mock_sut


class MockSutTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        (base / "login.html").write_text(
            '<input name="csrf" value="token-1">', encoding="utf-8"
        )
        config = {
            "routes": [
                {"method": "GET", "path": "/login", "status": 200,
                 "body_file": "login.html",
                 "headers": {"Content-Type": "text/html"}},
                {"method": "POST", "path": "/login", "status": 302,
                 "headers": {"Location": "/home"}},
                {"method": "POST", "path": "/graphql", "status": 200,
                 "body": "{\"data\":{\"search\":[{\"id\":\"p1\"}]}}",
                 "headers": {"Content-Type": "application/json"}},
            ]
        }
        routes_path = base / "routes.json"
        routes_path.write_text(json.dumps(config), encoding="utf-8")
        self.server = mock_sut.serve(routes_path, "127.0.0.1", 0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.tmp.cleanup()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def test_health(self) -> None:
        with urllib.request.urlopen(self.url("/__health")) as response:
            self.assertEqual(response.status, 200)

    def test_get_route_serves_body_file(self) -> None:
        with urllib.request.urlopen(self.url("/login")) as response:
            self.assertEqual(response.status, 200)
            self.assertIn(b'name="csrf"', response.read())

    def test_post_redirect_is_not_followed_blindly(self) -> None:
        request = urllib.request.Request(
            self.url("/login"), data=b"user=a", method="POST"
        )
        opener = urllib.request.build_opener(NoRedirect)
        # Python 3.14+ raises HTTPError(302) when redirect_request returns None;
        # older Pythons return the response object directly. Accept both.
        try:
            with opener.open(request) as response:
                self.assertEqual(response.status, 302)
                self.assertEqual(response.headers["Location"], "/home")
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, 302)
            self.assertEqual(error.headers["Location"], "/home")

    def test_unknown_route_returns_404(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(self.url("/missing"))
        self.assertEqual(raised.exception.code, 404)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


if __name__ == "__main__":
    sys.exit(unittest.main())
