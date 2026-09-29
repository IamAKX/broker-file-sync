"""Tests for services/report_engine/ — the shared HTML/SVG/PDF pipeline
every report type (LMV EOD, EMV EOD, Fuku Live) builds on."""
import os
import sys
import time

import pytest
from PySide6.QtWidgets import QApplication

from services.report_engine import charts, templates


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


# ── charts.py ────────────────────────────────────────────────────────────

def test_donut_chart_renders_svg_for_positive_segments():
    svg = charts.donut_chart(
        [{"label": "Target Hit", "value": 7, "color": "#16a34a"},
         {"label": "Stopped Out", "value": 3, "color": "#dc2626"}],
        center_label="70%",
    )
    assert svg.startswith("<svg")
    assert svg.count("<circle") == 2
    assert "70%" in svg


def test_donut_chart_handles_no_data():
    svg = charts.donut_chart([])
    assert "No data" in svg
    assert svg.startswith("<svg")


def test_donut_chart_ignores_zero_and_negative_segments():
    svg = charts.donut_chart([
        {"label": "Zero", "value": 0, "color": "#000"},
        {"label": "Real", "value": 5, "color": "#111"},
    ])
    assert svg.count("<circle") == 1


def test_line_chart_renders_series_with_gap_for_none():
    svg = charts.line_chart(
        [{"label": "Strategy A", "points": [1.0, None, 3.0, 4.0], "color": "#2979FF"}],
        x_labels=["d1", "d2", "d3", "d4"],
    )
    assert svg.startswith("<svg")
    # Two separate <path> segments because of the None gap in the middle
    # would need 3+ consecutive points per segment to draw a path — here
    # each side of the gap has only one point, so no <path> is drawn but
    # both points still render as <circle>s.
    assert svg.count("<circle") == 3


def test_line_chart_no_data_returns_placeholder():
    svg = charts.line_chart([])
    assert "No data" in svg


def test_line_chart_dashed_series_gets_dasharray():
    svg = charts.line_chart([
        {"label": "A", "points": [1, 2, 3], "color": "#111", "dashed": True},
    ])
    assert "stroke-dasharray" in svg


def test_bar_chart_widens_rather_than_compresses_many_bars():
    categories = [f"d{i}" for i in range(40)]
    values = [float(i) for i in range(40)]
    svg = charts.bar_chart(categories, values, width=400, min_bar_width=18)
    # 40 bars * 18px min each far exceeds the requested 400px width — the
    # chart must widen instead of shrinking bars unreadably thin.
    import re
    width_attr = int(re.search(r'width="(\d+)"', svg).group(1))
    assert width_attr > 400
    assert svg.count("<rect") == 40


def test_bar_chart_no_data_returns_placeholder():
    assert "No data" in charts.bar_chart([], [])


def test_progress_bar_clamps_fraction():
    bar = charts.progress_bar(1.5, color="#16a34a", label="Target 1")
    assert "width:100.0%" in bar
    assert "Target 1" in bar

    bar_negative = charts.progress_bar(-0.2)
    assert "width:0.0%" in bar_negative


# ── templates.py ─────────────────────────────────────────────────────────

def test_kpi_card_escapes_and_colors_by_kind():
    card = templates.kpi_card("Yield", "<script>", kind="positive")
    assert "&lt;script&gt;" in card
    assert "positive" in card


def test_data_table_escapes_cells_by_default():
    html = templates.data_table(["Name"], [["<b>x</b>"]])
    assert "&lt;b&gt;" in html


def test_data_table_allows_raw_html_for_declared_columns():
    pill = templates.status_pill("TARGET HIT", "positive")
    html = templates.data_table(["Status"], [[pill]], column_html={"Status"})
    assert "status-pill" in html
    assert "&lt;span" not in html


def test_render_report_produces_page_x_of_y_footer_per_page():
    doc = templates.render_report(["<p>Page one</p>", "<p>Page two</p>"], doc_title="Test Report")
    assert "Page 1 of 2" in doc
    assert "Page 2 of 2" in doc
    assert doc.count('class="report-page"') == 2
    assert "<!DOCTYPE html>" in doc


def test_render_report_single_page():
    doc = templates.render_report(["<p>only page</p>"])
    assert "Page 1 of 1" in doc


# ── pdf_export.py (real QWebEngineView round trip) ──────────────────────

def test_render_to_pdf_writes_a_real_pdf_file(qapp, tmp_path):
    from services.report_engine import pdf_export

    doc = templates.render_report(["<h1>Smoke test report</h1>"], doc_title="Smoke")
    output_path = str(tmp_path / "smoke.pdf")
    result = {}

    def on_done(success, error):
        result["success"] = success
        result["error"] = error

    pdf_export.render_to_pdf(doc, output_path, on_done)

    deadline = time.time() + 15
    while "success" not in result and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.02)

    assert result.get("success") is True, result.get("error")
    assert os.path.exists(output_path)
    assert os.path.getsize(output_path) > 0
