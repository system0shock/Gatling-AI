# mock_sut

Deterministic local HTTP stub used as the SUT for smoke runs. All behavior
comes from a JSON route config — no response synthesis, no state.

## Usage

    python tools/mock_sut/mock_sut.py --routes examples/scenarios/SHOP/checkout-mix-001/mock.routes.json --port 0

Prints `READY <port>` once listening (`--port 0` picks a free port).
`GET /__health` always answers 200. Unknown method/path pairs answer 404.

## Route config

    {
      "routes": [
        { "method": "GET", "path": "/login", "status": 200,
          "body_file": "bodies/login.html",
          "headers": { "Content-Type": "text/html" } }
      ]
    }

`body_file` paths are relative to the config file. `body` (inline string) is
the alternative. Query strings are ignored when matching.

## Known limitations

- **Chunked request bodies are not supported.** `_drain_request_body` only
  drains `Content-Length`-framed request bodies. Sending a request with
  `Transfer-Encoding: chunked` will not be drained correctly and may corrupt
  keep-alive connections. Gatling sends `Content-Length` by default, so this
  is not an issue for normal smoke-run use.
