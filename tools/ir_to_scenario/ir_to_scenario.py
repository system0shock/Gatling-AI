#!/usr/bin/env python3
"""Convert a JMeter IR (jmx_parser output) into a Phase-2b scenario.yaml + report.

Element-mapping rules for HTTP functions, extractors, redirects, and CSV
shareMode are adapted from Gatling's Apache-2.0 `gatling-convert-from-jmeter`
skill (github.com/gatling/gatling-ai-extensions). The contract-first pipeline
(IR -> scenario.yaml -> generator) and the disposition reconciliation are ours.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _shared.common import Finding  # noqa: E402

CONVERTED = "converted"
PARTIAL = "partial"
TODO = "todo"
SKIPPED = "skipped-disabled"


@dataclass
class Conversion:
    scenario: dict[str, Any]
    report_rows: list[dict[str, str]] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    _populations: list = field(default_factory=list)

    def record(self, element: dict[str, Any], status: str, note: str = "") -> None:
        self.report_rows.append(
            {"id": element.get("id", "?"), "kind": element.get("kind", "?"),
             "name": element.get("name", ""), "status": status, "note": note}
        )

    def disposition_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.report_rows:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        return counts


SAMPLER_KINDS = {"http_sampler", "jdbc_sampler", "jsr223_sampler"}
TRANSPARENT = {"transaction", "simple", "fragment"}
UNREPRESENTABLE = {"if", "loop", "once_only", "throughput", "module"}

# Config kinds consumed by build_data_and_env (CSV, UDV) or collect_context
# (header_manager, http_defaults, cookie_manager).  walk_steps must SKIP these
# entirely — they are recorded by their respective owners.
# - csv_data_set / user_defined_variables → build_data_and_env
# - header_manager / http_defaults / cookie_manager → walk_steps explicit branch
CONFIG_KINDS_BUILD_DATA = {"csv_data_set", "user_defined_variables"}
CONFIG_KINDS_CONTEXT = {"header_manager", "http_defaults", "cookie_manager"}


def kebab(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "flow"


def kebab_seg(name: str) -> str:
    """Like kebab(), but falls back to 'step' (not 'flow') and guarantees a
    letter-leading result — satisfying TRANSACTION_RE domain/action segments."""
    seg = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    if not seg:
        return "step"
    # If it starts with a digit, prepend 'txn-' so it starts with a letter.
    if seg[0].isdigit():
        seg = "txn-" + seg
    return seg


def load_from_normalized(normalized: dict[str, Any]) -> dict[str, Any]:
    model = normalized["model"]
    return {"model": model, "profile": "stages", "stages": normalized["stages"]}


def thread_groups(children: list[Any]) -> list[dict[str, Any]]:
    return [n for n in children if isinstance(n, dict) and n.get("kind") == "thread_group" and n.get("enabled", True)]


def add_finding(conv: Conversion, rule: str, message: str, element_id: str) -> None:
    conv.findings.append(Finding(rule=rule, message=message, severity="blocking", path=element_id))


def convert(ir: dict[str, Any], *, system: str, scenario_id: str, number: int) -> Conversion:
    scenario: dict[str, Any] = {
        "id": scenario_id,
        "system": system,
        "number": number,
        "title": ir.get("test_plan", {}).get("name") or scenario_id,
        "source": {"type": "jmeter", "ref": ir.get("source", {}).get("file", "")},
        "sut": {"base_url": "${BASE_URL}"},
    }
    conv = Conversion(scenario={"scenario": scenario})

    groups = thread_groups(ir.get("children", []))
    populations: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for tg in groups:
        normalized = (tg.get("load") or {}).get("normalized")
        if normalized is None:
            note = (tg.get("load") or {}).get("note") or "load could not be normalized"
            add_finding(conv, "convert.load-not-normalized",
                        f"thread group '{tg.get('name')}' load not normalized: {note}", tg["id"])
            conv.record(tg, PARTIAL, note)
            load = {"model": "closed", "profile": "stages", "stages": [{"users": 1, "ramp_seconds": 0, "hold_seconds": 1}]}
        else:
            conv.record(tg, CONVERTED)
            load = load_from_normalized(normalized)
        population = {"name": kebab(tg.get("name", "flow")), "load": load, "steps": []}
        start_after = (normalized or {}).get("start_after_seconds") or 0
        if start_after > 0:
            population["start_after_seconds"] = start_after
        populations.append((tg, population))

    if len(populations) == 1:
        _, only = populations[0]
        scenario["steps"] = only["steps"]
        scenario["load"] = only["load"]
        if "start_after_seconds" in only:
            add_finding(conv, "convert.single-flow-start-after-dropped",
                        "single thread group has an initial delay; not representable in single-flow form", groups[0]["id"])
    elif populations:
        scenario["populations"] = [p for _tg, p in populations]
    conv._populations = populations

    # Per-population structure walk: fills each population's steps list.
    # Thread groups themselves are already recorded above (CONVERTED or PARTIAL).
    # domain = kebab of scenario_id (keeps scenario identity in every transaction
    # name); txn_action seeds from a transaction-controller name, else the sampler
    # name. Do NOT revert domain to the TG name — test_transaction_controller_seeds_step_names
    # pins this scheme; the spec NOTE suggesting TG-name domain was aspirational.
    top_domain = kebab_seg(scenario_id)
    enabled_tg_ids = {tg["id"] for tg in groups}
    for tg, population in populations:
        walk_steps(tg.get("children", []), conv, population["steps"],
                   top_domain, txn_action=None, counter=[0])

    # Handle disabled thread groups and any non-thread-group top-level children.
    for child in ir.get("children", []):
        if not isinstance(child, dict):
            continue
        if child.get("kind") == "thread_group" and child.get("id") not in enabled_tg_ids:
            # Disabled TG: already NOT in `groups`; record it and its children as skipped.
            conv.record(child, SKIPPED)
            _walk_skipped(child.get("children", []), conv)
        elif child.get("kind") != "thread_group":
            # Non-thread-group top-level element (e.g. test-plan-wide config)
            walk_children([child], conv)

    # Pre-pass: map CSV feeders and UDV environment.  Must run AFTER the step
    # walk so that all other elements are already recorded; build_data_and_env
    # records csv_data_set and user_defined_variables (walk_steps skips them).
    build_data_and_env(ir, scenario, conv)

    return conv


def walk_children(children: list[Any], conv: Conversion) -> None:
    """Fallback: record every element as todo (used for non-TG top-level children).

    csv_data_set and user_defined_variables are skipped here — build_data_and_env
    records them via iter_all and owns their disposition.
    """
    for node in children:
        if not isinstance(node, dict):
            continue
        kind = node.get("kind")
        # Skip CONFIG_KINDS_BUILD_DATA: build_data_and_env owns their disposition.
        if kind in CONFIG_KINDS_BUILD_DATA:
            continue
        if not node.get("enabled", True):
            conv.record(node, SKIPPED)
        else:
            conv.record(node, TODO, "not yet mapped")
        walk_children(node.get("children", []), conv)


def _walk_skipped(children: list[Any], conv: Conversion) -> None:
    """Record all descendants of a disabled parent as skipped-disabled."""
    for node in children:
        if not isinstance(node, dict):
            continue
        conv.record(node, SKIPPED)
        _walk_skipped(node.get("children", []), conv)


def walk_steps(nodes: list[Any], conv: Conversion, steps: list[dict[str, Any]],
               domain: str, txn_action: str | None, counter: list[int],
               ctx: dict[str, Any] | None = None) -> None:
    """Walk the children of a thread group (or controller), filling `steps` with
    converted sampler steps. Each element is recorded exactly once here.

    Transaction mask format: ``NN domain.action - Title``
    - ``domain``     = scenario_id (kebab), constant throughout the walk.
    - ``txn_action`` = transaction controller name (kebab) when inside a
                       transaction; None at top level so each sampler uses its
                       own kebab name as the action segment.
    - ``ctx``        = inherited header/defaults context from parent containers.
    """
    if ctx is None:
        ctx = {"headers": {}, "defaults": {}}
    # Collect context (header_manager, http_defaults) from this node list.
    local_ctx = collect_context(nodes, ctx)
    for node in nodes:
        if not isinstance(node, dict):
            continue
        kind = node.get("kind")
        if not node.get("enabled", True):
            # csv_data_set and user_defined_variables are owned by build_data_and_env
            # even when disabled — skip here to avoid double-recording.
            if kind in CONFIG_KINDS_BUILD_DATA:
                continue
            conv.record(node, SKIPPED)
            # Do NOT descend into disabled nodes — their children are also skipped.
            _walk_skipped(node.get("children", []), conv)
            continue
        if kind in SAMPLER_KINDS:
            counter[0] += 1
            step = build_step(node, conv, domain, txn_action, counter[0], local_ctx)
            if step is not None:
                steps.append(step)
            # Samplers are leaves for the structure walk.  Their children
            # (extractors, assertions, jsr223-processors) are consumed by
            # checks_from_children (called inside fill_http / build_step) and
            # are recorded there.  Do NOT call record_non_step_element here or
            # the children would be double-counted.
            continue
        if kind in TRANSPARENT:
            conv.record(node, CONVERTED)
            # Transaction controller name becomes the action segment for its children.
            child_txn = kebab_seg(node.get("name", "")) if kind == "transaction" else txn_action
            walk_steps(node.get("children", []), conv, steps, domain, child_txn, counter, local_ctx)
            continue
        if kind in UNREPRESENTABLE:
            conv.record(node, PARTIAL,
                        f"{kind} controller flattened; semantics not represented in the flat contract")
            walk_steps(node.get("children", []), conv, steps, domain, txn_action, counter, local_ctx)
            continue
        # csv_data_set and user_defined_variables are owned by build_data_and_env
        # (called from convert after the step walk).  Skip them here — they are
        # recorded there.  Doing nothing here is correct: no record() call.
        if kind in CONFIG_KINDS_BUILD_DATA:
            continue
        # header_manager, http_defaults, cookie_manager are consumed by
        # collect_context above; record them as converted so counts reconcile.
        if kind in CONFIG_KINDS_CONTEXT:
            conv.record(node, CONVERTED)
            continue
        # Config/extractor/assertion/timer/jsr223-processor elements that appear
        # directly under a TG or controller: record as todo for now (Tasks 7-8 refine).
        record_non_step_element(node, conv)


def build_step(node: dict[str, Any], conv: Conversion, domain: str,
               txn_action: str | None, index: int,
               ctx: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Build a scenario step dict for a sampler node. Records the element.
    Returns None if the sampler cannot be expressed as a step (e.g. standalone jsr223).

    Transaction mask: ``NN domain.action - Title``
    - action = txn_action (from enclosing transaction controller) if set,
               otherwise kebab of the sampler's own name.
    """
    if ctx is None:
        ctx = {"headers": {}, "defaults": {}}
    raw_name = node.get("name") or f"step-{index}"
    name = kebab_seg(raw_name)
    action = txn_action if txn_action is not None else name
    transaction = f"{index:02d} {domain}.{action} - {raw_name}"
    step: dict[str, Any] = {"name": name, "title": raw_name, "transaction": transaction}
    kind = node.get("kind")
    if kind == "http_sampler":
        fill_http(node, step, conv, ctx)
    else:
        # jdbc_sampler and jsr223_sampler: stubbed until Tasks 7/8
        step["protocol"] = "http"
        step["request"] = {"method": "GET", "path": "/"}
        step["checks"] = []
        conv.record(node, CONVERTED)
    return step


def record_non_step_element(node: dict[str, Any], conv: Conversion) -> None:
    """Record a config/extractor/assertion/timer element as todo so counts reconcile.
    Tasks 5-8 will change the status when they consume the element."""
    if not node.get("enabled", True):
        conv.record(node, SKIPPED)
        _walk_skipped(node.get("children", []), conv)
    else:
        conv.record(node, TODO, "pending attach to step")
        for child in node.get("children", []):
            if isinstance(child, dict):
                record_non_step_element(child, conv)


def collect_context(nodes: list[Any], parent_ctx: dict[str, Any]) -> dict[str, Any]:
    """Collect header_manager headers and http_defaults url from the nodes list,
    inheriting from parent_ctx. Returns a new context dict."""
    ctx = {"headers": dict(parent_ctx.get("headers", {})), "defaults": dict(parent_ctx.get("defaults", {}))}
    for node in nodes:
        if not isinstance(node, dict) or not node.get("enabled", True):
            continue
        if node.get("kind") == "header_manager":
            ctx["headers"].update(node.get("headers", {}))
        elif node.get("kind") == "http_defaults":
            ctx["defaults"] = node.get("url", {})
    return ctx


def checks_from_children(sampler: dict[str, Any], conv: Conversion) -> list[dict[str, Any]]:
    """Scan sampler children for assertions and extractors; build check list.

    Records each child exactly once (CONVERTED / PARTIAL / SKIPPED).
    Extractor/assertion children are leaves — do NOT recurse into their children.
    The schema extract.type enum is {css, jsonPath, regex}; boundary has no
    direct contract type and is recorded PARTIAL.
    Inserts a default {status: 200} when no status assertion is present.
    """
    checks: list[dict[str, Any]] = []
    has_status = False
    for child in sampler.get("children", []):
        if not isinstance(child, dict):
            continue
        if not child.get("enabled", True):
            conv.record(child, SKIPPED)
            continue
        kind = child.get("kind")
        if kind == "regex_extractor":
            checks.append({"extract": {
                "type": "regex",
                "expr": child.get("regex", ""),
                "saveAs": child.get("variable", ""),
            }})
            conv.record(child, CONVERTED)
        elif kind == "jsonpath_extractor":
            for ex in child.get("extracts", []):
                checks.append({"extract": {
                    "type": "jsonPath",
                    "expr": ex.get("expr", ""),
                    "saveAs": ex.get("variable", ""),
                }})
            conv.record(child, CONVERTED)
        elif kind == "boundary_extractor":
            # boundary is not in the scenario extract.type enum {css, jsonPath, regex}
            conv.record(child, PARTIAL, "boundary extractor has no direct contract type; translate manually")
        elif kind == "response_assertion":
            if child.get("field") == "Assertion.response_code":
                patterns = [str(p).strip() for p in child.get("patterns", [])]
                numeric = [p for p in patterns if p.isdigit()]
                for p in numeric:
                    checks.append({"status": int(p)})
                    has_status = True
                if len(patterns) == 1 and len(numeric) == 1:
                    conv.record(child, CONVERTED)
                elif numeric:
                    # JMeter ORs multiple patterns; scenario status checks AND.
                    conv.record(child, PARTIAL,
                                "multiple/mixed response-code patterns emitted as AND-ed status checks "
                                "(JMeter semantics are OR) — review")
                else:
                    conv.record(child, PARTIAL,
                                "non-numeric response-code pattern; no status check emitted — translate manually")
            else:
                conv.record(child, PARTIAL, "non-status assertion; translate as a body check manually")
        elif kind == "json_assertion":
            conv.record(child, PARTIAL, "json assertion; translate manually")
        else:
            # Any other child kind (e.g. timers nested under a sampler, unknown kinds)
            record_non_step_element(child, conv)
    if not has_status:
        checks.insert(0, {"status": 200})
    return checks


def fill_http(node: dict[str, Any], step: dict[str, Any], conv: Conversion, ctx: dict[str, Any]) -> None:
    """Real HTTP mapper for http_sampler nodes."""
    url = node.get("url", {})
    path = url.get("path") or "/"
    request: dict[str, Any] = {"method": (node.get("method") or "GET").upper(), "path": path}
    headers = ctx.get("headers") or {}
    if headers:
        request["headers"] = dict(headers)
    body = node.get("body")
    partial_note = ""
    if isinstance(body, dict) and "inline" in body:
        request["body"] = body["inline"]
    elif isinstance(body, dict) and "ref" in body:
        request["body_file"] = body["ref"]
    elif node.get("params"):
        partial_note = "form params not representable in the http contract; emitted as TODO body"
    if not node.get("follow_redirects", True):
        partial_note = (partial_note + "; " if partial_note else "") + "follow_redirects=false (disableFollowRedirect) not in contract"
    step["protocol"] = "http"
    step["request"] = request
    # Consume sampler children (extractors, assertions) and build checks.
    # Each child is recorded here; walk_steps does NOT recurse into sampler children.
    step["checks"] = checks_from_children(node, conv)
    conv.record(node, PARTIAL if partial_note else CONVERTED, partial_note)


def iter_all(nodes: list[Any]):
    """Yield every element in the subtree (depth-first, including node itself)."""
    for node in nodes:
        if isinstance(node, dict):
            yield node
            yield from iter_all(node.get("children", []))


def feeder_strategy(csv: dict[str, Any]) -> str:
    """Map JMeter CSV recycle/stop_thread flags to a Gatling feeder strategy.

    stop_thread=true  → 'queue'   (exhaust and stop the virtual user)
    else              → 'circular' (JMeter recycle maps to Gatling circular;
                        recycle=false in JMeter stops iteration, but Gatling
                        'queue' is the closest safe approximation only when
                        stop_thread is explicitly set)
    """
    if csv.get("stop_thread"):
        return "queue"
    return "circular"


def build_data_and_env(ir: dict[str, Any], scenario: dict[str, Any], conv: Conversion) -> None:
    """Pre-pass over all IR elements: maps csv_data_set → scenario.data.feeders
    and user_defined_variables → sut.base_url / env documentation in the report.

    Ownership: THIS function records csv_data_set and user_defined_variables
    (enabled AND disabled).  walk_steps skips these kinds entirely.
    Disabled elements are recorded SKIPPED; enabled CSV → CONVERTED/PARTIAL;
    enabled UDV → CONVERTED.
    """
    feeders: list[dict[str, Any]] = []
    for node in iter_all(ir.get("children", [])):
        kind = node.get("kind")
        if kind not in CONFIG_KINDS_BUILD_DATA:
            continue
        if not node.get("enabled", True):
            # Disabled CSV/UDV: record skipped; no feeder/env emitted.
            conv.record(node, SKIPPED)
            continue
        if kind == "csv_data_set":
            raw_name = node.get("name") or ""
            file_path = node.get("file") or "feeder"
            # derive stem: last component without extension
            stem = file_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].rsplit(".", 1)[0]
            feeder_name = kebab_seg(raw_name if raw_name else stem)
            has_cols = bool(node.get("variable_names"))
            feeders.append({
                "name": feeder_name,
                "file": node.get("file", ""),
                "strategy": feeder_strategy(node),
            })
            conv.record(
                node,
                CONVERTED if has_cols else PARTIAL,
                "" if has_cols else "variableNames blank; columns inferred from CSV header at runtime",
            )
        elif kind == "user_defined_variables":
            values: dict[str, Any] = node.get("values") or {}
            base_url_keys = {"BASE_URL", "baseUrl", "base_url"}
            if any(k in values for k in base_url_keys):
                scenario["sut"]["base_url"] = "${BASE_URL}"
            conv.record(node, CONVERTED,
                        "UDV mapped to env/base_url (values are env-backed; never inlined per NFR5)")
    if feeders:
        scenario["data"] = {"feeders": feeders}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert JMeter IR to a scenario.yaml")
    parser.add_argument("ir_json")
    parser.add_argument("--system", required=True)
    parser.add_argument("--id", required=True, dest="scenario_id")
    parser.add_argument("--number", required=True, type=int)
    args = parser.parse_args(argv)
    ir = json.loads(Path(args.ir_json).read_text(encoding="utf-8"))
    conv = convert(ir, system=args.system, scenario_id=args.scenario_id, number=args.number)
    print(json.dumps(conv.disposition_counts()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
