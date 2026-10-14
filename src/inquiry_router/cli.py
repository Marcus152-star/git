from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .classifier import assess_inquiry
from .config import load_config
from .customers import CustomerIndex
from .email_parser import parse_eml
from .router import make_decision
from .state import StateStore


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _configure_output_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")


def _eml_paths(value: str | Path) -> list[Path]:
    path = Path(value)
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(path.glob("*.eml"))
    raise FileNotFoundError(f"EML path does not exist: {path}")


def command_inspect_customers(args: argparse.Namespace) -> int:
    index = CustomerIndex.from_xlsx_files(args.customers)
    _print_json(index.summary())
    return 0


def command_match_customer(args: argparse.Namespace) -> int:
    index = CustomerIndex.from_xlsx_files(args.customers)
    match = index.match([args.email], args.company or "")
    _print_json(
        {
            "status": match.status,
            "reason": match.reason,
            "matched_email": match.matched_email,
            "owner": match.owner,
            "customer_ids": match.customer_ids,
            "company_names": match.company_names,
            "countries": match.countries,
        }
    )
    return 0 if match.status == "matched" else 2


def command_route_eml(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    index = CustomerIndex.from_xlsx_files(args.customers)
    paths = _eml_paths(args.eml)
    if not paths:
        raise ValueError("No .eml files found")

    decisions: list[dict] = []
    with StateStore(args.state, config.initial_standard_inquiry_count) as state:
        stored_count_before = state.get_standard_count()
        preview_count = stored_count_before
        blacklisted_senders = state.get_blacklisted_senders()
        for path in paths:
            parsed = parse_eml(path, config)
            assessment = assess_inquiry(parsed, blacklisted_senders)
            match = index.match(parsed.customer_email_candidates, parsed.company_name)
            if args.commit:
                decision = state.commit(parsed, assessment, match, config)
                blacklisted_senders = state.get_blacklisted_senders()
            else:
                decision = make_decision(parsed, assessment, match, preview_count, config)
                if decision.advances_standard_counter:
                    preview_count += 1
            result = decision.to_dict()
            result.update(
                {
                    "source_path": parsed.source_path,
                    "subject": parsed.subject,
                    "envelope_from": parsed.envelope_from,
                    "reply_to": parsed.reply_to,
                    "customer_name": parsed.customer_name,
                    "company_name": parsed.company_name,
                }
            )
            decisions.append(result)

        payload = {
            "mode": "commit-decision-only" if args.commit else "preview",
            "email_sending_enabled": False,
            "stored_standard_inquiry_count_before_run": stored_count_before,
            "stored_standard_inquiry_count_after_run": state.get_standard_count(),
            "projected_standard_inquiry_count_after_run": (
                state.get_standard_count() if args.commit else preview_count
            ),
            "decisions": decisions,
        }

    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _print_json(payload)
    return 0


def command_state(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    with StateStore(args.state, config.initial_standard_inquiry_count) as state:
        if args.set_count is not None:
            state.set_standard_count(args.set_count)
        _print_json({"standard_inquiry_count": state.get_standard_count()})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="inquiry-router",
        description="Shadow-mode customer matching and inquiry routing. This version never sends email.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect-customers", help="Summarize a YiiCRM customer export")
    inspect_parser.add_argument(
        "--customers", nargs="+", required=True, help="Paths to one or more YiiCRM .xlsx exports"
    )
    inspect_parser.set_defaults(func=command_inspect_customers)

    match_parser = subparsers.add_parser("match-customer", help="Test one email against the customer export")
    match_parser.add_argument("--customers", nargs="+", required=True)
    match_parser.add_argument("--email", required=True)
    match_parser.add_argument("--company")
    match_parser.set_defaults(func=command_match_customer)

    route_parser = subparsers.add_parser("route-eml", help="Preview routing for one EML file or a directory")
    route_parser.add_argument("--customers", nargs="+", required=True)
    route_parser.add_argument("--eml", required=True)
    route_parser.add_argument("--config")
    route_parser.add_argument("--state", default="data/router_state.sqlite3")
    route_parser.add_argument("--output")
    route_parser.add_argument(
        "--commit",
        action="store_true",
        help="Record decisions and advance standard counter. Still does not send email.",
    )
    route_parser.set_defaults(func=command_route_eml)

    state_parser = subparsers.add_parser("state", help="View or explicitly set the standard-routing counter")
    state_parser.add_argument("--state", default="data/router_state.sqlite3")
    state_parser.add_argument("--config")
    state_parser.add_argument("--set-count", type=int)
    state_parser.set_defaults(func=command_state)
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_output_encoding()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

