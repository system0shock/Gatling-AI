#!/usr/bin/env python3
"""Aggregate and reconcile methodology evidence artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from . import aggregate, reconcile
    from .contracts import load_evidence, load_section_reviews
except ImportError:
    import aggregate
    import reconcile
    from contracts import load_evidence, load_section_reviews


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Methodology evidence artifact tools")
    commands = parser.add_subparsers(dest="command", required=True)
    aggregate_parser = commands.add_parser("aggregate", help="aggregate confirmed module evidence")
    aggregate_parser.add_argument("--snapshot", type=Path, required=True)
    aggregate_parser.add_argument("--evidence", type=Path, nargs="+", required=True)
    aggregate_parser.add_argument("--out-dir", type=Path, required=True)
    reconcile_parser = commands.add_parser("reconcile", help="reconcile repository, Confluence, confirmations, and section reviews")
    reconcile_parser.add_argument("--repository", type=Path, required=True)
    reconcile_parser.add_argument("--confluence", type=Path, required=True)
    reconcile_parser.add_argument("--confirmations", type=Path, required=True)
    reconcile_parser.add_argument("--reviews", type=Path, required=True)
    reconcile_parser.add_argument("--out-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "aggregate":
        snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
        document = aggregate.aggregate_modules(snapshot, args.evidence)
        aggregate.write_aggregation_outputs(document, args.out_dir)
        return 0
    result = reconcile.reconcile_documents(
        load_evidence(args.repository),
        load_evidence(args.confluence),
        load_evidence(args.confirmations),
        load_section_reviews(args.reviews),
    )
    reconcile.write_reconciliation_outputs(result, args.out_dir)
    return 2 if result.blocking_gaps else 0


if __name__ == "__main__":
    sys.exit(main())
