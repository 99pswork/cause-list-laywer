"""Date utilities for cause list date handling."""

from datetime import date, datetime, timedelta


def next_working_day(from_date: date = None) -> date:
    """Return next working day (skipping weekends) from given date or today."""
    d = from_date or date.today()
    d += timedelta(days=1)
    while d.weekday() >= 5:  # Saturday=5, Sunday=6
        d += timedelta(days=1)
    return d


def format_date_for_api(d: date) -> str:
    """Format date as dd/mm/yyyy for the cause list form."""
    return d.strftime("%d/%m/%Y")


def parse_date_input(date_str: str) -> date:
    """Parse user-provided date string. Accepts dd/mm/yyyy, dd-mm-yyyy, yyyy-mm-dd."""
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {date_str}. Use dd/mm/yyyy format.")


def resolve_date(date_arg: str = None) -> str:
    """Resolve a CLI date argument to dd/mm/yyyy string.

    Accepts: None (next working day), 'today', 'tomorrow', or a date string.
    """
    if date_arg is None:
        return format_date_for_api(next_working_day())
    lower = date_arg.lower()
    if lower == "today":
        return format_date_for_api(date.today())
    if lower == "tomorrow":
        return format_date_for_api(date.today() + timedelta(days=1))
    return format_date_for_api(parse_date_input(date_arg))
