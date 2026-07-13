"""CLI reporting tool. People type dates the US way: mm/dd/yy."""

from utils.dates import parse_date


def report_line(raw):
    """One-line report for a single US-format date string."""
    d = parse_date(raw)
    return f"Report for {d.isoformat()}"
