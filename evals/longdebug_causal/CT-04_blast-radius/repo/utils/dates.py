"""Date parsing shared by the CLI and the web API."""

from datetime import datetime

DATE_FMT = "%d/%m/%y"


def parse_date(s):
    return datetime.strptime(s.strip(), DATE_FMT).date()
