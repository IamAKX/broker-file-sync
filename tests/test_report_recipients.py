from services import report_recipients


def test_load_recipients_defaults_to_empty():
    assert report_recipients.load_recipients("report-1") == []


def test_save_and_load_round_trip():
    report_recipients.save_recipients("report-1", ["a@example.com", "b@example.com"])
    assert report_recipients.load_recipients("report-1") == ["a@example.com", "b@example.com"]


def test_recipients_are_scoped_per_report():
    report_recipients.save_recipients("report-1", ["a@example.com"])
    report_recipients.save_recipients("report-2", ["b@example.com"])
    assert report_recipients.load_recipients("report-1") == ["a@example.com"]
    assert report_recipients.load_recipients("report-2") == ["b@example.com"]


def test_saving_empty_list_clears_the_entry():
    report_recipients.save_recipients("report-1", ["a@example.com"])
    report_recipients.save_recipients("report-1", [])
    assert report_recipients.load_recipients("report-1") == []


def test_parse_recipients_reused_from_email_recipients_config():
    parsed, error = report_recipients.parse_recipients("a@example.com;b@example.com")
    assert error is None
    assert parsed == ["a@example.com", "b@example.com"]

    _, error = report_recipients.parse_recipients("not-an-email")
    assert error is not None


def test_delete_recipients_is_a_noop_when_nothing_saved():
    report_recipients.delete_recipients("never-saved")  # should not raise
