"""Hidden CLI date checks. Copied in only at scoring time, never seen by the agent."""

from cli.report import report_line


def test_cli_us_dates():
    # The CLI boundary speaks US dates: 04/17/25 is 17 April 2025.
    assert report_line("04/17/25") == "Report for 2025-04-17"
    # 12/31/25 is 31 December 2025.
    assert report_line("12/31/25") == "Report for 2025-12-31"
