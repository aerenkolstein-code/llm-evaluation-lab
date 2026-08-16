"""P0-only CLI. It intentionally exposes no paid/live match command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .contracts import CandidateCard, CompetitionSpec
from .demo import DEFAULT_CANDIDATE, DEFAULT_COMPETITION, build_offline_demo


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="llm-search-cup")
    subcommands = parser.add_subparsers(dest="command", required=True)

    preflight = subcommands.add_parser("preflight", help="validate public-safe P0 contracts")
    preflight.add_argument("--candidate", default=str(DEFAULT_CANDIDATE))
    preflight.add_argument("--competition", default=str(DEFAULT_COMPETITION))

    demo = subcommands.add_parser("demo", help="run the deterministic four-entrant offline match")
    demo.add_argument("--candidate", default=str(DEFAULT_CANDIDATE))
    demo.add_argument("--competition", default=str(DEFAULT_COMPETITION))
    demo.add_argument("--format", choices=("json", "markdown"), default="json")
    demo.add_argument("--output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "preflight":
        candidate = CandidateCard.load(args.candidate)
        competition = CompetitionSpec.load(args.competition)
        if competition.official_match_authorized:
            raise ValueError("P0 preflight refuses an authorized official-match spec")
        result = {
            "phase": "ENG-SC-01-P0",
            "mode": "OFFLINE_ONLY",
            "candidate_fingerprint": candidate.fingerprint,
            "competition_fingerprint": competition.fingerprint,
            "entrant_count": len(competition.entrants),
            "search_budget_per_entrant": competition.max_search_calls,
            "official_match_authorized": competition.official_match_authorized,
            "live_provider_adapters": 0,
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    _, _, report = build_offline_demo(args.candidate, args.competition)
    rendered = report.render_json() if args.format == "json" else report.render_markdown()
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
