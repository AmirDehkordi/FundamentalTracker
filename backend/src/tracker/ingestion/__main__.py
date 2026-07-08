"""Ingestion CLI: `python -m tracker.ingestion --sources all|xbrl|filings [--from-cache]`."""

from __future__ import annotations

import argparse
import logging

from tracker.ingestion import runner

# Dispatch order matters: xbrl upserts companies + fundamentals that later lanes reference/label.
_AVAILABLE_SOURCES = ("xbrl", "filings")
_ALL = "all"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tracker.ingestion", description="Ingest SEC EDGAR data into the tracker DB."
    )
    parser.add_argument(
        "--sources",
        default="all",
        help=f"comma-separated sources, or 'all' ({', '.join(_AVAILABLE_SOURCES)})",
    )
    parser.add_argument(
        "--from-cache", action="store_true", help="replay from seed/bronze offline, no network"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    sources = {s.strip() for s in args.sources.split(",") if s.strip()}
    if _ALL in sources:
        sources = set(_AVAILABLE_SOURCES)
    unknown = sources - set(_AVAILABLE_SOURCES)
    if unknown:
        parser.error(f"unknown sources {sorted(unknown)}; available: {sorted(_AVAILABLE_SOURCES)}")

    if "xbrl" in sources:
        runner.print_summary(runner.run_xbrl(from_cache=args.from_cache))
    if "filings" in sources:
        runner.print_filings_summary(runner.run_filings(from_cache=args.from_cache))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
