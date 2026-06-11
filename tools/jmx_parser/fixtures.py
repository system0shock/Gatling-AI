#!/usr/bin/env python3
"""Builders for small JMX documents used by jmx_parser tests."""

from __future__ import annotations

from xml.sax.saxutils import escape


def jmx(*plan_children: str) -> str:
    """Wrap element snippets (already paired with their <hashTree/>) into a plan."""
    inner = "\n".join(plan_children)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<jmeterTestPlan version="1.2" properties="5.0" jmeter="5.6.3">\n'
        "  <hashTree>\n"
        '    <TestPlan guiclass="TestPlanGui" testclass="TestPlan" testname="Test Plan" enabled="true">\n'
        '      <stringProp name="TestPlan.comments">fixture plan</stringProp>\n'
        "    </TestPlan>\n"
        "    <hashTree>\n"
        f"{inner}\n"
        "    </hashTree>\n"
        "  </hashTree>\n"
        "</jmeterTestPlan>\n"
    )


def element(
    testclass: str,
    name: str,
    *,
    guiclass: str = "",
    enabled: bool = True,
    props: str = "",
    children: str = "",
) -> str:
    """A test element paired with its container hashTree (children go inside)."""
    gui = f' guiclass="{guiclass}"' if guiclass else ""
    flag = "true" if enabled else "false"
    return (
        f'<{testclass}{gui} testclass="{testclass}" testname="{escape(name)}" enabled="{flag}">\n'
        f"{props}\n"
        f"</{testclass}>\n"
        f"<hashTree>\n{children}\n</hashTree>"
    )


def string_prop(name: str, value: str) -> str:
    return f'  <stringProp name="{name}">{escape(value)}</stringProp>'


def bool_prop(name: str, value: bool) -> str:
    return f'  <boolProp name="{name}">{"true" if value else "false"}</boolProp>'


def thread_group(
    name: str = "TG",
    *,
    threads: int = 1,
    ramp: int = 0,
    duration: int = 0,
    delay: int = 0,
    enabled: bool = True,
    children: str = "",
) -> str:
    props = "\n".join(
        [
            string_prop("ThreadGroup.num_threads", str(threads)),
            string_prop("ThreadGroup.ramp_time", str(ramp)),
            string_prop("ThreadGroup.duration", str(duration)),
            string_prop("ThreadGroup.delay", str(delay)),
            bool_prop("ThreadGroup.scheduler", duration > 0 or delay > 0),
        ]
    )
    return element(
        "ThreadGroup", name, guiclass="ThreadGroupGui", enabled=enabled,
        props=props, children=children,
    )


def http_sampler(
    name: str = "request",
    *,
    method: str = "GET",
    path: str = "/",
    body: str | None = None,
    params: dict[str, str] | None = None,
    children: str = "",
) -> str:
    props = [
        string_prop("HTTPSampler.method", method),
        string_prop("HTTPSampler.path", path),
    ]
    if body is not None:
        props.append(bool_prop("HTTPSampler.postBodyRaw", True))
        props.append(
            '  <elementProp name="HTTPsampler.Arguments" elementType="Arguments">\n'
            '    <collectionProp name="Arguments.arguments">\n'
            '      <elementProp name="" elementType="HTTPArgument">\n'
            f'        <stringProp name="Argument.value">{escape(body)}</stringProp>\n'
            "      </elementProp>\n"
            "    </collectionProp>\n"
            "  </elementProp>"
        )
    elif params:
        rows = "\n".join(
            '      <elementProp name="" elementType="HTTPArgument">\n'
            f'        <stringProp name="Argument.name">{escape(key)}</stringProp>\n'
            f'        <stringProp name="Argument.value">{escape(value)}</stringProp>\n'
            "      </elementProp>"
            for key, value in params.items()
        )
        props.append(
            '  <elementProp name="HTTPsampler.Arguments" elementType="Arguments">\n'
            '    <collectionProp name="Arguments.arguments">\n'
            f"{rows}\n"
            "    </collectionProp>\n"
            "  </elementProp>"
        )
    return element(
        "HTTPSamplerProxy", name, guiclass="HttpTestSampleGui",
        props="\n".join(props), children=children,
    )
