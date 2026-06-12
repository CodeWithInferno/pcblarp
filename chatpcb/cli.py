"""Run the pipeline from the command line.

    python -m chatpcb.cli "Make a small BLE mic with a battery"

Used by the Makefile demo targets. Exits 0 on done/partial (partial results
are still demo-able), 1 on a failed run.
"""

from __future__ import annotations

import argparse

from . import config
from .pipeline import run_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="chatpcb", description="Idea -> fabrication-ready PCB files"
    )
    parser.add_argument("idea", help="plain-language device idea")
    parser.add_argument(
        "--events", action="store_true", help="print the full event log"
    )
    args = parser.parse_args(argv)

    state = run_pipeline(args.idea)

    print(f"\nrun {state.run_id}: {state.status} "
          f"(spec revisions: {state.revision_count})")
    print(f"{'stage':<11} {'status':<8} {'tries':>5} {'ms':>8}  error")
    for record in state.stages:
        print(
            f"{record.name:<11} {record.status:<8} {record.attempts:>5} "
            f"{record.duration_ms:>8.0f}  {record.error or ''}"
        )

    export = next(r for r in state.stages if r.name == "export")
    if export.artifacts:
        print("\nartifacts:")
        for name, url in sorted(export.artifacts.items()):
            print(f"  {name:<24} {url}")
    print(f"\nlocal artifacts dir: {config.artifacts_dir() / state.run_id}")

    if args.events:
        print("\nevents:")
        for event in state.events:
            print(f"  - {event}")

    return 0 if state.status in ("done", "partial") else 1


if __name__ == "__main__":
    raise SystemExit(main())
