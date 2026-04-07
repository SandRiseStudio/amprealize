#!/usr/bin/env python3
"""CI Quality Gate Runner — orchestrates benchmark evaluation and regression checks.

Usage:
    python scripts/run_quality_gates.py --output results.json
    python scripts/run_quality_gates.py --previous previous_results.json --output results.json

Exit codes:
    0 — All gates passed
    1 — One or more gates failed
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run quality gates for CI")
    parser.add_argument(
        "--anchors",
        type=str,
        default=None,
        help="Path to regression_anchors.json (default: auto-detect)",
    )
    parser.add_argument(
        "--previous",
        type=str,
        default=None,
        help="Path to previous benchmark results JSON for regression detection",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="quality_gate_results.json",
        help="Path to write gate results JSON",
    )
    parser.add_argument(
        "--strategy-results",
        type=str,
        default=None,
        help="Path to strategy comparison results JSON (skip live evaluation)",
    )
    args = parser.parse_args()

    # Lazy imports so the script can validate args first
    from mdnt.evaluation import (
        QualityGateService,
        StrategyComparisonResult,
        load_regression_anchors,
    )

    # Load anchors
    anchors_path = args.anchors
    if anchors_path is None:
        pkg_dir = Path(__file__).resolve().parent.parent / "packages" / "midnighter" / "benchmarks"
        default_path = pkg_dir / "regression_anchors.json"
        if default_path.exists():
            anchors_path = str(default_path)
        else:
            print("ERROR: No regression_anchors.json found. Provide --anchors.", file=sys.stderr)
            return 1

    with open(anchors_path) as f:
        anchors = json.load(f)

    gate_service = QualityGateService(anchors=anchors)

    # Load or compute strategy results
    strategy_result = None
    if args.strategy_results:
        with open(args.strategy_results) as f:
            data = json.load(f)
        strategy_result = StrategyComparisonResult(**data)

    # Load previous metrics for regression detection
    previous_metrics = None
    if args.previous:
        with open(args.previous) as f:
            prev_data = json.load(f)
        # Support both raw metrics dict and nested strategy format
        if "strategy_metrics" in prev_data:
            previous_metrics = prev_data["strategy_metrics"].get("pack_bci", {})
        else:
            previous_metrics = prev_data

    # Run all gates
    report = gate_service.run_all_gates(
        strategy_result=strategy_result,
        previous_metrics=previous_metrics,
        anchors_path=anchors_path,
    )

    # Write results
    output_data = report.to_dict()
    output_path = Path(args.output)
    output_path.write_text(json.dumps(output_data, indent=2, default=str))
    print(f"Quality gate results written to {output_path}")

    # Print summary
    print(f"\nGate Results: {output_data['passed_gates']}/{output_data['total_gates']} passed")
    if not report.overall_passed:
        print("\nFAILED GATES:")
        for gate in report.gates:
            if not gate.passed:
                print(f"  - {gate.gate_name}: {', '.join(gate.failures)}")
        return 1

    if report.regression_detected:
        print("\nWARNING: Regression detected (see details in output)")

    print("\n✅ All quality gates passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
