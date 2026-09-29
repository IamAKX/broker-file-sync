import pytest

from services import report_store


def test_new_report_rejects_unknown_type():
    with pytest.raises(ValueError):
        report_store.new_report("bogus", "My Report")


def test_new_report_has_sensible_defaults():
    report = report_store.new_report(report_store.REPORT_TYPE_LMV, "Weekly LMV")
    assert report["type"] == "lmv"
    assert report["name"] == "Weekly LMV"
    assert report["timeframe"]["mode"] == "daily"
    assert report["columns"] == []


def test_save_and_get_round_trip():
    report = report_store.new_report(report_store.REPORT_TYPE_EMV, "EMV Trend")
    report_store.save_report(report)

    loaded = report_store.get_report(report["id"])
    assert loaded["name"] == "EMV Trend"


def test_save_report_upserts_by_id_and_stamps_updated_at():
    report = report_store.new_report(report_store.REPORT_TYPE_FUKU_LIVE, "Live")
    report_store.save_report(report)
    first_updated_at = report_store.get_report(report["id"])["updated_at"]

    report["name"] = "Live (renamed)"
    report_store.save_report(report)

    reloaded = report_store.get_report(report["id"])
    assert reloaded["name"] == "Live (renamed)"
    assert len(report_store.load_all()) == 1
    assert reloaded["updated_at"] >= first_updated_at


def test_load_by_type_filters_correctly():
    lmv = report_store.new_report(report_store.REPORT_TYPE_LMV, "L")
    emv = report_store.new_report(report_store.REPORT_TYPE_EMV, "E")
    report_store.save_report(lmv)
    report_store.save_report(emv)

    assert [r["id"] for r in report_store.load_by_type(report_store.REPORT_TYPE_LMV)] == [lmv["id"]]


def test_delete_report_removes_it_and_its_recipients():
    from services import report_recipients

    report = report_store.new_report(report_store.REPORT_TYPE_LMV, "To delete")
    report_store.save_report(report)
    report_recipients.save_recipients(report["id"], ["a@example.com"])

    report_store.delete_report(report["id"])

    assert report_store.get_report(report["id"]) is None
    assert report_recipients.load_recipients(report["id"]) == []
