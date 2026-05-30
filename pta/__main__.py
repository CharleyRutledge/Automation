"""
CLI for the PTA model builder and validator.

Build a model from existing passing runs:
    python -m pta build --test test_playwright_docs_intro_flow_chromium

Validate a new trace against a stored model:
    python -m pta validate --test test_playwright_docs_intro_flow_chromium \\
        --trace reports/latest/screenshots/test_playwright_docs_intro_flow_chromium

List stored models:
    python -m pta list
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _reports_root() -> Path:
    return Path(__file__).resolve().parents[1] / "reports"


def _models_root() -> Path:
    return Path(__file__).resolve().parents[1] / "pta_models"


def cmd_build(args: argparse.Namespace) -> int:
    from .model import PTAModel
    from .equivalence import TieredEquivalenceChecker, AdaptiveThresholdCalibrator

    test_name: str = args.test
    reports_root = Path(args.reports) if args.reports else _reports_root()

    # Find all screenshot directories for this test across all report runs
    trace_dirs: list[Path] = []
    for run_dir in sorted(reports_root.iterdir()):
        if run_dir.name == "latest":
            continue
        candidate = run_dir / "screenshots" / test_name
        if candidate.is_dir() and any(candidate.glob("*.png")):
            trace_dirs.append(candidate)

    if len(trace_dirs) < 2:
        print(
            f"Error: found {len(trace_dirs)} trace(s) for '{test_name}' under {reports_root}. "
            "Need at least 2 passing runs. Run the test a couple more times first.",
            file=sys.stderr,
        )
        return 1

    print(f"Found {len(trace_dirs)} traces for '{test_name}':")
    for d in trace_dirs:
        imgs = list(d.glob("*.png"))
        print(f"  {d.parent.parent.name}/{d.name}  ({len(imgs)} steps)")

    calibrator = AdaptiveThresholdCalibrator()
    checker = TieredEquivalenceChecker(calibrator)
    model = PTAModel.build(test_name, trace_dirs, checker)

    model_path = _models_root() / f"{test_name}.json"
    model.save(model_path)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    from .model import PTAModel
    from .validator import TraceValidator

    test_name: str = args.test
    model_path = _models_root() / f"{test_name}.json"

    if not model_path.exists():
        print(f"Error: no model found at {model_path}. Run 'python -m pta build' first.", file=sys.stderr)
        return 1

    model = PTAModel.load(model_path)

    if args.trace:
        trace_dir = Path(args.trace)
    else:
        # Default: latest report
        latest = _reports_root() / "latest" / "screenshots" / test_name
        if not latest.is_dir():
            print(f"Error: trace directory not found: {latest}", file=sys.stderr)
            return 1
        trace_dir = latest

    if not trace_dir.is_dir():
        print(f"Error: trace directory not found: {trace_dir}", file=sys.stderr)
        return 1

    validator = TraceValidator()
    result = validator.validate(trace_dir, model)
    print(result.summary())
    print()
    print(validator._checker.cost_report() if hasattr(validator, "_checker") and validator._checker else "")
    return 0 if result.passed else 1


def cmd_list(_args: argparse.Namespace) -> int:
    models_root = _models_root()
    if not models_root.exists() or not any(models_root.glob("*.json")):
        print("No models stored yet. Run 'python -m pta build' to create one.")
        return 0
    from .model import PTAModel
    for f in sorted(models_root.glob("*.json")):
        m = PTAModel.load(f)
        print(f"  {m.test_name}  —  {len(m.essential_states)} essential states  ({m.training_traces} training traces)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pta",
        description="PTA-based test model builder and validator",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="Build a model from passing traces")
    p_build.add_argument("--test", required=True, help="Test name (screenshot directory name)")
    p_build.add_argument("--reports", default=None, help="Reports root dir (default: reports/)")

    p_validate = sub.add_parser("validate", help="Validate a trace against a stored model")
    p_validate.add_argument("--test", required=True, help="Test name")
    p_validate.add_argument("--trace", default=None, help="Path to screenshot dir (default: reports/latest/screenshots/<test>)")

    sub.add_parser("list", help="List stored models")

    args = parser.parse_args()
    dispatch = {"build": cmd_build, "validate": cmd_validate, "list": cmd_list}
    return dispatch[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
