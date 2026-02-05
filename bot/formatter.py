"""Format parsed cause list data as Telegram HTML messages."""

import html as html_mod

from bot.config import TELEGRAM_MAX_MESSAGE_LENGTH
from causelist.config import CAUSELIST_TYPE_NAMES
from causelist.parser import CaseEntry, CourtSection, group_by_court


def _esc(text: str) -> str:
    """HTML-escape text for Telegram."""
    return html_mod.escape(text)


def _format_case(entry: CaseEntry) -> str:
    """Format a single case entry as Telegram HTML."""
    lines = [f"<b>{_esc(entry.serial_no)}.</b> {_esc(entry.case_type_no)}"]
    if entry.title:
        title = entry.title[:300] + "..." if len(entry.title) > 300 else entry.title
        lines.append(f"  {_esc(title)}")
    if entry.advocates:
        lines.append(f"  <i>{_esc(entry.advocates)}</i>")
    return "\n".join(lines)


def _format_court_section(section: CourtSection) -> str:
    """Format a court section (header + categorized cases) as Telegram HTML."""
    parts = []
    parts.append(f"\n{'=' * 30}")
    parts.append(f"<b>{_esc(section.court_no)}</b>")
    if section.judge_name:
        parts.append(f"<i>{_esc(section.judge_name)}</i>")
    parts.append(f"{'=' * 30}")

    for category, cases in section.categories.items():
        if category and category != "General":
            parts.append(f"\n<b>{_esc(category)}</b>")
        parts.append("")
        for case in cases:
            parts.append(_format_case(case))
            parts.append("")

    return "\n".join(parts)


def format_causelist_message(
    records: list[CaseEntry],
    cl_type: str,
    target_date: str,
    lawyer_name: str,
) -> list[str]:
    """Build one or more Telegram HTML messages from parsed records.

    Returns a list of strings, each within the 4096-char Telegram limit.
    Splits at court section boundaries to avoid cutting mid-case.
    """
    type_name = CAUSELIST_TYPE_NAMES.get(cl_type, cl_type)

    if not records:
        return [
            f"No cases found in <b>{_esc(type_name)}</b> cause list "
            f"for <b>{_esc(target_date)}</b> "
            f"(Advocate: <b>{_esc(lawyer_name)}</b>)."
        ]

    sections = group_by_court(records)

    header = (
        f"<b>Rajasthan HC - {_esc(type_name)} Cause List</b>\n"
        f"Date: <b>{_esc(target_date)}</b>\n"
        f"Advocate: <b>{_esc(lawyer_name)}</b>\n"
        f"Cases found: <b>{len(records)}</b>"
    )

    messages = []
    current = header
    max_len = TELEGRAM_MAX_MESSAGE_LENGTH

    for section in sections:
        section_text = _format_court_section(section)

        if len(current) + len(section_text) + 2 > max_len:
            # Flush current message
            if current.strip():
                messages.append(current)

            # If a single section is itself too large, split it case by case
            if len(section_text) > max_len:
                messages.extend(_split_large_section(section, type_name))
                current = ""
            else:
                current = f"<b>{_esc(type_name)} Cause List (contd.)</b>\n" + section_text
        else:
            current += "\n" + section_text

    if current.strip():
        messages.append(current)

    return messages


def _split_large_section(section: CourtSection, type_name: str) -> list[str]:
    """Split a single court section that exceeds message limit into multiple messages."""
    section_header = f"<b>{_esc(section.court_no)}</b>\n"
    if section.judge_name:
        section_header += f"<i>{_esc(section.judge_name)}</i>\n"

    messages = []
    current = f"<b>{_esc(type_name)} (contd.)</b>\n{section_header}"
    max_len = TELEGRAM_MAX_MESSAGE_LENGTH

    for cases in section.categories.values():
        for case in cases:
            case_text = _format_case(case) + "\n\n"
            if len(current) + len(case_text) > max_len:
                messages.append(current)
                current = f"<b>{_esc(type_name)} (contd.)</b>\n{section_header}"
            current += case_text

    if current.strip():
        messages.append(current)

    return messages
