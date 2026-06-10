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
                {"method": "GET", "path": "/cl-override", "status": 200,
                 "body": "hello",
                 "headers": {"Content-Type": "text/plain",
                             "Content-Length": "9999"}},
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
            with error:
                self.assertEqual(error.code, 302)
                self.assertEqual(error.headers["Location"], "/home")

    def test_unknown_route_returns_404(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(self.url("/missing"))
        raised.exception.close()
        self.assertEqual(raised.exception.code, 404)

    def test_route_config_content_length_not_duplicated(self) -> None:
        with urllib.request.urlopen(self.url("/cl-override")) as response:
            body = response.read()
            cl_values = response.headers.get_all("Content-Length")
            self.assertEqual(cl_values, [str(len(body))])


class LoadRoutesTest(unittest.TestCase):
    def test_non_dict_config_raises_value_error(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            f.write("[]")
            tmp_path = Path(f.name)
        try:
            with self.assertRaises(ValueError):
                mock_sut.load_routes(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

    def _write_routes(self, base: Path, body_file_value: str) -> Path:
        routes_path = base / "routes.json"
        routes_path.write_text(
            json.dumps({"routes": [{"method": "GET", "path": "/x", "body_file": body_file_value}]}),
            encoding="utf-8",
        )
        return routes_path

    def test_body_file_path_traversal_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            # create a file outside the config dir so the path would resolve
            outside = base.parent / "outside.html"
            try:
                outside.write_bytes(b"evil")
                routes = self._write_routes(base, "../outside.html")
                with self.assertRaisesRegex(ValueError, "escapes the config directory"):
                    mock_sut.load_routes(routes)
            finally:
                outside.unlink(missing_ok=True)

    def test_body_file_absolute_path_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            base = Path(tmp1)
            # write the target file outside the config directory
            outside = Path(tmp2) / "outside.html"
            outside.write_bytes(b"data")
            routes = self._write_routes(base, str(outside.resolve()))
            with self.assertRaisesRegex(ValueError, "escapes the config directory"):
                mock_sut.load_routes(routes)

    def test_body_file_legitimate_relative_path_works(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            bodies = base / "bodies"
            bodies.mkdir()
            (bodies / "x.json").write_bytes(b'{"ok":true}')
            routes = self._write_routes(base, "bodies/x.json")
            result = mock_sut.load_routes(routes)
            self.assertIn(("GET", "/x"), result)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


if __name__ == "__main__":
    sys.exit(unittest.main())
