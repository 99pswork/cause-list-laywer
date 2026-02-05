"""Command-line interface for the cause list tool."""

import argparse
import logging
import sys

from causelist.client import CauseListClient
from causelist.config import CAUSELIST_TYPE_NAMES, CAUSELIST_TYPES
from causelist.date_utils import resolve_date
from causelist.parser import parse_and_display


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rajasthan High Court Cause List Lookup",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python main.py --lawyer "SHARMA"
  python main.py --lawyer "SHARMA" --date 10/02/2026
  python main.py --lawyer "SHARMA" --type supplementary
  python main.py --lawyer "SHARMA" --date today
  python main.py --lawyer "SHARMA" --date tomorrow
        """,
    )
    parser.add_argument(
        "--lawyer", "-l",
        required=True,
        help="Lawyer name to search (minimum 3 characters)",
    )
    parser.add_argument(
        "--date", "-d",
        default=None,
        help="Cause list date (dd/mm/yyyy). Default: next working day. "
             "Also accepts 'today' or 'tomorrow'.",
    )
    parser.add_argument(
        "--type", "-t",
        default="daily",
        choices=list(CAUSELIST_TYPES.keys()),
        help="Cause list type (default: daily)",
    )
    return parser


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = build_parser()
    args = parser.parse_args()

    if len(args.lawyer) < 3:
        parser.error("Lawyer name must be at least 3 characters")

    try:
        date_str = resolve_date(args.date)
    except ValueError as e:
        parser.error(str(e))

    cl_type = CAUSELIST_TYPES[args.type]
    cl_type_name = CAUSELIST_TYPE_NAMES[cl_type]

    print(f"=== Rajasthan HC Cause List Lookup ===")
    print(f"Lawyer: {args.lawyer}")
    print(f"Date:   {date_str}")
    print(f"Type:   {cl_type_name}")
    print(f"{'=' * 38}\n")

    client = CauseListClient()
    try:
        result = client.search_causelist(
            lawyer_name=args.lawyer,
            date_str=date_str,
            cl_type=cl_type,
        )
        if result:
            print("\n--- Results ---\n")
            parse_and_display(result)
        else:
            print("\nNo records found for the given criteria.")
    except RuntimeError as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}", file=sys.stderr)
        sys.exit(1)
