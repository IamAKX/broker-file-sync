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


# ── price_ladder / bubble_chart (Fuku Live report, issue #58) ────────────

def test_price_ladder_orders_levels_and_shows_distance_from_current():
    svg = charts.price_ladder(
        [{"label": "ENTRY", "price": 100.0}, {"label": "T1", "price": 110.0, "sub": "x"},
         {"label": "SL", "price": 95.0}], ref_price=100.0)
    assert svg.index("T1") < svg.index("ENTRY") < svg.index("SL")     # highest price on top
    assert "+10.00%" in svg and "-5.00%" in svg and "+0.00%" in svg


def test_price_ladder_and_bubble_chart_handle_empty_input():
    assert "No levels" in charts.price_ladder([], 100.0)
    assert "No data" in charts.bubble_chart([])


def test_bubble_chart_draws_one_bubble_per_point_and_dedupes_colliding_labels():
    pts = [{"label": f"S{i}", "x": 1.0, "y": 0.0, "size": i + 1, "color": "#16a34a"} for i in range(6)]
    svg = charts.bubble_chart(pts)
    assert svg.count("<circle") == 6
    assert 1 <= svg.count('font-size="8"') < 6   # identical positions -> labels thinned, not stacked


# ── legends / axis values (issue #62) ────────────────────────────────────

def test_line_chart_draws_a_colour_legend_with_dashed_swatches():
    series = [
        {"label": "DT", "points": [1, 2, 3], "color": "#2979FF"},
        {"label": "Close", "points": [1, 2, 3], "color": "#16a34a", "dashed": True},
    ]
    svg = charts.line_chart(series, x_labels=["a", "b", "c"])
    assert ">DT<" in svg and ">Close<" in svg
    assert 'stroke="#16a34a" stroke-width="2.5" stroke-dasharray="4 3"' in svg     # dashed swatch
    assert 'stroke="#2979FF" stroke-width="2.5"/>' in svg                           # solid swatch
    # the legend lives inside the SVG, so the chart grew taller to make room
    assert int(svg.split('height="')[1].split('"')[0]) > 260
    assert ">DT<" not in charts.line_chart(series, legend=False)


def test_line_chart_legend_wraps_onto_extra_rows_for_many_series():
    many = [{"label": f"Indicator number {i}", "points": [1, 2], "color": "#2979FF"} for i in range(8)]
    one = charts.line_chart(many[:1])
    wrapped = charts.line_chart(many)
    assert int(wrapped.split('height="')[1].split('"')[0]) > int(one.split('height="')[1].split('"')[0])


def test_bar_chart_shows_y_axis_values():
    svg = charts.bar_chart(["a", "b"], [4.0, -2.0])
    assert ">4.0<" in svg and ">0.0<" in svg and ">-2.0<" in svg


# ── light / dark report themes (issue #59) ───────────────────────────────

def test_apply_theme_dark_injects_overrides_and_light_is_a_noop():
    doc = templates.render_report(["<p>x</p>"], doc_title="T")
    assert templates.apply_theme(doc, "light") == doc
    assert templates.apply_theme(doc, None) == doc
    dark = templates.apply_theme(doc, "dark")
    assert dark != doc and doc in dark.replace(templates._DARK_CSS, "")      # only a CSS addition
    assert "--text-primary: #E2E8F0" in dark and "background: #0F172A" in dark
    assert dark.count("<style>") == 1                                        # same single stylesheet


def test_dark_theme_remaps_the_svg_chart_colours():
    svg_doc = templates.render_report([charts.line_chart(
        [{"label": "A", "points": [1, 2, 3], "color": "#2979FF"}], x_labels=["a", "b", "c"])])
    dark = templates.apply_theme(svg_doc, "dark")
    for light_value in ('fill="#64748b"', 'stroke="#E2E8F0"'):
        assert light_value in svg_doc                    # the chart itself still draws light-theme colours...
    assert 'svg text[fill="#64748b"]' in dark and 'svg line[stroke="#E2E8F0"]' in dark   # ...remapped by CSS
