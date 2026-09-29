def test_send_report_email_uploads_file_bytes_and_joins_recipients(tmp_path, monkeypatch):
    from api import reports_api
    from api.client import api_client

    pdf_path = tmp_path / "r.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 hello")

    captured = {}

    def fake_post_multipart(path, data=None, files=None, auth=True, timeout=None):
        captured["path"] = path
        captured["data"] = data
        captured["files"] = files
        captured["timeout"] = timeout
        return {}

    monkeypatch.setattr(api_client, "post_multipart", fake_post_multipart)

    reports_api.send_report_email(str(pdf_path), ["a@example.com", "b@example.com"], "My Report")

    assert captured["path"] == "/notifications/email/send-report"
    assert captured["data"]["recipients"] == "a@example.com;b@example.com"
    assert captured["data"]["subject"] == "My Report"
    assert captured["files"]["attachment"][1] == b"%PDF-1.4 hello"
    assert captured["files"]["attachment"][2] == "application/pdf"
    assert captured["timeout"] > 15
