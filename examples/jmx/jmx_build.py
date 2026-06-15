# examples/jmx/jmx_build.py
"""Builders for the golden migration .jmx fixtures.

Thin wrappers over tools/jmx_parser/fixtures.py primitives. The stringProp names
match what jmx_parser reads (see tools/jmx_parser/test_jmx_parser.py), so each
wrapper parses to a known kind. Later tasks add `build_*` composition functions
and a `__main__` writer for the two golden `.jmx`.
"""
from __future__ import annotations

import sys
from pathlib import Path
from xml.sax.saxutils import escape

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "jmx_parser"))

import fixtures  # noqa: E402
from fixtures import bool_prop, element, http_sampler, jmx, string_prop  # noqa: E402, F401


def ultimate_tg(name, *, users, delay, rampup, hold, shutdown, children="", enabled=True):
    props = (
        '  <collectionProp name="ultimatethreadgroupdata">\n'
        '    <collectionProp name="row">\n'
        f'      <stringProp name="c0">{str(users)}</stringProp>\n'
        f'      <stringProp name="c1">{str(delay)}</stringProp>\n'
        f'      <stringProp name="c2">{str(rampup)}</stringProp>\n'
        f'      <stringProp name="c3">{str(hold)}</stringProp>\n'
        f'      <stringProp name="c4">{str(shutdown)}</stringProp>\n'
        "    </collectionProp>\n"
        "  </collectionProp>"
    )
    return element("kg.apc.jmeter.threads.UltimateThreadGroup", name,
                   guiclass="UltimateThreadGroupGui", enabled=enabled,
                   props=props, children=children)


def concurrency_tg(name, *, target, rampup, steps, hold, unit="M", children="", enabled=True):
    props = "\n".join([
        string_prop("TargetLevel", str(target)),
        string_prop("RampUp", str(rampup)),
        string_prop("Steps", str(steps)),
        string_prop("Hold", str(hold)),
        string_prop("Unit", unit),
    ])
    return element("com.blazemeter.jmeter.threads.concurrency.ConcurrencyThreadGroup",
                   name, guiclass="ConcurrencyThreadGroupGui", enabled=enabled,
                   props=props, children=children)


def transaction(name, *, children="", enabled=True):
    return element("TransactionController", name, enabled=enabled,
                   props=bool_prop("TransactionController.parent", True),
                   children=children)


def http_defaults(name, *, domain, port, protocol="https"):
    props = "\n".join([
        string_prop("HTTPSampler.domain", domain),
        string_prop("HTTPSampler.port", str(port)),
        string_prop("HTTPSampler.protocol", protocol),
    ])
    return element("ConfigTestElement", name, guiclass="HttpDefaultsGui", props=props)


def header_manager(name, headers):
    rows = "\n".join(
        '    <elementProp name="" elementType="Header">\n'
        f'      <stringProp name="Header.name">{escape(k)}</stringProp>\n'
        f'      <stringProp name="Header.value">{escape(v)}</stringProp>\n'
        "    </elementProp>"
        for k, v in headers.items()
    )
    props = f'  <collectionProp name="HeaderManager.headers">\n{rows}\n  </collectionProp>'
    return element("HeaderManager", name, props=props)


def udv(name, values):
    rows = "\n".join(
        '    <elementProp name="" elementType="Argument">\n'
        f'      <stringProp name="Argument.name">{escape(k)}</stringProp>\n'
        f'      <stringProp name="Argument.value">{escape(v)}</stringProp>\n'
        "    </elementProp>"
        for k, v in values.items()
    )
    props = f'  <collectionProp name="Arguments.arguments">\n{rows}\n  </collectionProp>'
    return element("Arguments", name, guiclass="ArgumentsPanel", props=props)


def csv_data_set(name, *, filename, variable_names=None, share_mode="shareMode.all",
                 recycle=True, stop_thread=False, delimiter=","):
    props = [string_prop("filename", filename)]
    if variable_names is not None:
        props.append(string_prop("variableNames", variable_names))
    props += [
        string_prop("delimiter", delimiter),
        bool_prop("recycle", recycle),
        bool_prop("stopThread", stop_thread),
        string_prop("shareMode", share_mode),
    ]
    return element("CSVDataSet", name, props="\n".join(props))


def regex_extractor(name, *, refname, regex, template="$1$", match_number="1", default="NOT_FOUND"):
    props = "\n".join([
        string_prop("RegexExtractor.refname", refname),
        string_prop("RegexExtractor.regex", regex),
        string_prop("RegexExtractor.template", template),
        string_prop("RegexExtractor.match_number", match_number),
        string_prop("RegexExtractor.default", default),
    ])
    return element("RegexExtractor", name, props=props)


def jsonpath_extractor(name, *, refs, exprs, match_numbers, defaults):
    props = "\n".join([
        string_prop("JSONPostProcessor.referenceNames", ";".join(refs)),
        string_prop("JSONPostProcessor.jsonPathExprs", ";".join(exprs)),
        string_prop("JSONPostProcessor.match_numbers", ";".join(match_numbers)),
        string_prop("JSONPostProcessor.defaultValues", ";".join(defaults)),
    ])
    return element("JSONPostProcessor", name, props=props)


def response_assertion(name, *, code="200"):
    props = (
        '  <collectionProp name="Asserion.test_strings">\n'
        + string_prop("s0", code) + "\n"
        "  </collectionProp>\n"
        + string_prop("Assertion.test_field", "Assertion.response_code") + "\n"
        + '  <intProp name="Assertion.test_type">8</intProp>'
    )
    return element("ResponseAssertion", name, props=props)


def jsr223(testclass, name, script, language="groovy"):
    props = "\n".join([string_prop("script", script), string_prop("scriptLanguage", language)])
    return element(testclass, name, props=props)


def constant_timer(name, *, delay_ms):
    return element("ConstantTimer", name, props=string_prop("ConstantTimer.delay", str(delay_ms)))


def jdbc_sampler(name, *, query):
    return element("JDBCSampler", name, props=string_prop("query", query))


# A body > 1024 bytes so the parser externalizes it to bodies/ (exercises body_file).
_CHECKOUT_BODY = (
    '{"orderId":"${requestId}","productId":"${productId}","note":"'
    + "padding-" * 200  # ~1600 bytes
    + '"}'
)


def build_simple_backend() -> str:
    catalog = transaction("catalog list", children="\n".join([
        http_sampler("get catalog", method="GET", path="/catalog",
                     children="\n".join([
                         jsonpath_extractor("ids", refs=["productId", "price"],
                                            exprs=["$.items[0].id", "$.items[0].price"],
                                            match_numbers=["1", "1"], defaults=["MISSING", "0"]),
                         response_assertion("status 200"),
                     ])),
    ]))
    search = transaction("catalog search", children="\n".join([
        http_sampler("search", method="GET", path="/search?q=${term}",
                     children="\n".join([
                         regex_extractor("get csrf", refname="csrf",
                                         regex='name="csrf" value="(.+?)"'),
                         response_assertion("status 200"),
                     ])),
        constant_timer("think", delay_ms=1000),
    ]))
    checkout = transaction("checkout submit", children="\n".join([
        http_sampler("post checkout", method="POST", path="/checkout",
                     body=_CHECKOUT_BODY,
                     children="\n".join([
                         jsr223("JSR223PreProcessor", "make request id",
                                'def rid = UUID.randomUUID().toString()\nvars.put("requestId", rid)'),
                         response_assertion("status 200"),
                     ])),
    ]))
    tg = ultimate_tg("Backend load", users=50, delay=0, rampup=120, hold=600, shutdown=60,
                     children="\n".join([
                         http_defaults("Defaults", domain="${host}", port="${port}"),
                         header_manager("Headers", {"Content-Type": "application/json"}),
                         catalog, search, checkout,
                     ]))
    return jmx(
        tg,
        udv("Env", {"BASE_URL": "http://shop.local:8080", "host": "shop.local", "port": "8080"}),
        csv_data_set("search terms", filename="search-terms.csv", variable_names="term"),
    )


def build_staged_pipeline() -> str:  # filled in a later task
    raise NotImplementedError


def _write(path: Path, document: str) -> None:
    path.write_text(document, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    _write(here / "simple-backend.jmx", build_simple_backend())
    try:
        _write(here / "staged-pipeline.jmx", build_staged_pipeline())
    except NotImplementedError:
        pass
    print("wrote golden .jmx to", here)
