"""Ingestion CLI: `python -m tracker.ingestion --sources xbrl [--from-cache]`."""

from __future__ import annotations

import argparse
import logging

from tracker.ingestion import runner

_AVAILABLE_SOURCES = {"xbrl"}  # narratives/prices land in P3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tracker.ingestion", description="Ingest SEC EDGAR data into the tracker DB."
    )
    parser.add_argument(
        "--sources", default="xbrl", help="comma-separated sources (only 'xbrl' in P2)"
    )
    parser.add_argument(
        "--from-cache", action="store_true", help="replay from seed/bronze offline, no network"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    sources = {s.strip() for s in args.sources.split(",") if s.strip()}
    unknown = sources - _AVAILABLE_SOURCES
    if unknown:
        parser.error(f"unknown sources {sorted(unknown)}; available: {sorted(_AVAILABLE_SOURCES)}")

    if "xbrl" in sources:
        runner.print_summary(runner.run_xbrl(from_cache=args.from_cache))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
