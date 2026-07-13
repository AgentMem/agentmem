from cli.report import report_line


def test_report_line_us():
    # A US date like 04/17/25 means 17 April 2025.
    assert report_line("04/17/25") == "Report for 2025-04-17"
