"""Parse HTML cause list response for terminal display and structured data."""

from collections import OrderedDict
from dataclasses import dataclass, field

from bs4 import BeautifulSoup


@dataclass
class CaseEntry:
    """A single case entry from a cause list."""
    serial_no: str
    case_type_no: str
    title: str
    advocates: str
    court_no: str
    judge_name: str
    category: str = ""


@dataclass
class CourtSection:
    """Cases grouped by court room."""
    court_no: str
    judge_name: str
    categories: dict = field(default_factory=dict)  # category_name -> list[CaseEntry]


def parse_and_display(html_content: str) -> None:
    """Parse HTML cause list and print formatted results to terminal."""
    soup = BeautifulSoup(html_content, "html.parser")

    tables = soup.find_all("table")

    if not tables:
        # No tables — try extracting text directly
        text = soup.get_text(separator="\n", strip=True)
        if text:
            print(text)
        else:
            print("No displayable content found in response.")
        return

    for table in tables:
        rows = table.find_all("tr")
        if not rows:
            continue

        # Calculate column widths for aligned output
        all_cells = []
        for row in rows:
            cells = row.find_all(["td", "th"])
            cell_texts = [cell.get_text(strip=True) for cell in cells]
            all_cells.append(cell_texts)

        if not all_cells:
            continue

        # Find max width per column
        max_cols = max(len(row) for row in all_cells)
        col_widths = [0] * max_cols
        for row in all_cells:
            for i, cell in enumerate(row):
                col_widths[i] = max(col_widths[i], min(len(cell), 50))

        # Print rows
        for row in all_cells:
            formatted = []
            for i, cell in enumerate(row):
                width = col_widths[i] if i < len(col_widths) else 20
                # Truncate long cells
                display = cell[:50] + "..." if len(cell) > 50 else cell
                formatted.append(display.ljust(width))
            print(" | ".join(formatted))

        print("-" * 80)


def _br_to_separator(cell, separator: str) -> str:
    """Extract text from a cell, replacing <br/> tags with a separator.
    Filters out empty parts to avoid leading/trailing separators.
    """
    parts = []
    current = []
    for child in cell.children:
        if getattr(child, "name", None) == "br":
            text = "".join(current).strip()
            if text:
                parts.append(text)
            current = []
        else:
            current.append(child.get_text() if hasattr(child, "get_text") else str(child))
    text = "".join(current).strip()
    if text:
        parts.append(text)
    return separator.join(parts)


def _extract_title(cell) -> str:
    """Extract case title, using 'Vs' between petitioner and respondent."""
    parts = []
    current = []
    for child in cell.children:
        if getattr(child, "name", None) == "br":
            text = "".join(current).strip()
            if text:
                parts.append(text)
            current = []
        else:
            current.append(child.get_text() if hasattr(child, "get_text") else str(child))
    text = "".join(current).strip()
    if text:
        parts.append(text)
    if len(parts) <= 1:
        return parts[0] if parts else ""
    # First part is petitioner, rest is respondent info joined with space
    return parts[0] + " Vs " + " ".join(parts[1:])


def parse_to_records(html_content: str) -> list[CaseEntry]:
    """Parse HTML cause list into structured CaseEntry records.

    Inspects table rows to detect court headers, category headers, and case data rows.
    Returns a flat list of CaseEntry objects with court/judge/category metadata attached.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    tables = soup.find_all("table")
    records = []
    current_court = ""
    current_judge = ""
    current_category = ""

    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all(["td", "th"])
            cell_texts = [c.get_text(strip=True) for c in cells]

            if not cell_texts:
                continue

            full_text = " ".join(cell_texts).strip()
            lower_text = full_text.lower()

            # Skip empty or page footer rows
            if not full_text or "page" in lower_text and "of" in lower_text:
                continue

            # Detect court number header: "Court No : 2"
            if "court no" in lower_text or "court room" in lower_text:
                current_court = full_text
                current_judge = ""
                current_category = ""
                continue

            # Detect judge name rows: contain "HON'BLE" or "JUSTICE"
            if "hon'ble" in lower_text or "justice" in lower_text:
                judge_parts = [t for t in cell_texts if t]
                current_judge = " | ".join(judge_parts)
                continue

            # Detect column header rows (S.No., Case Type etc.)
            if any(h in lower_text for h in ("s.no", "sr.no", "case type", "name of advocate")):
                continue

            # Detect category headers: text rows that aren't data (no digit in first cell)
            # These are things like "FOR ADMISSION", "AT 2.00 PM", etc.
            if len(cell_texts) <= 2 and full_text and not cell_texts[0][:1].isdigit():
                # Skip generic headers like site name, website, etc.
                if "high court" in lower_text or "website" in lower_text or "causelist" in lower_text:
                    continue
                if "webex" in lower_text or "cisco" in lower_text or "note:" in lower_text:
                    continue
                current_category = full_text
                continue

            # Data rows: expect at least 3 columns and first column starts with digit (S.No.)
            if len(cell_texts) >= 3:
                sno = cell_texts[0]
                # Check if this looks like a case data row
                if not sno or (not sno[0].isdigit() and "with" not in sno.lower()):
                    # Could be a sub-header or misc row
                    if full_text and not any(skip in lower_text for skip in
                                              ["high court", "website", "=", "---"]):
                        current_category = full_text
                    continue

                # Extract title preserving petitioner Vs respondent
                title = _extract_title(cells[2])

                # Extract advocate names with <br/> → ", "
                adv_parts = []
                for c in cells[3:]:
                    part = _br_to_separator(c, ", ")
                    if part:
                        adv_parts.append(part)
                advocates = " | ".join(adv_parts)

                entry = CaseEntry(
                    serial_no=sno.replace("With", "").strip(),
                    case_type_no=cell_texts[1],
                    title=title,
                    advocates=advocates,
                    court_no=current_court,
                    judge_name=current_judge,
                    category=current_category,
                )
                records.append(entry)

    return records


def group_by_court(records: list[CaseEntry]) -> list[CourtSection]:
    """Group CaseEntry records by court room, preserving order."""
    sections: OrderedDict[str, CourtSection] = OrderedDict()
    for entry in records:
        key = entry.court_no or "Unknown"
        if key not in sections:
            sections[key] = CourtSection(
                court_no=entry.court_no,
                judge_name=entry.judge_name,
                categories={},
            )
        section = sections[key]
        cat = entry.category or "General"
        if cat not in section.categories:
            section.categories[cat] = []
        section.categories[cat].append(entry)
    return list(sections.values())
