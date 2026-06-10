# mock_sut

Deterministic local HTTP stub used as the SUT for smoke runs. All behavior
comes from a JSON route config — no response synthesis, no state.

## Usage

    python tools/mock_sut/mock_sut.py --routes examples/mock/checkout-mix.routes.json --port 0

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
