"""
Report visualisation of configured Indicator Library entries (EMV spec
§17.3): price-panel indicators (SMA/EMA/Bollinger/...) are overlaid on a
Close line, oscillators/sub-panel indicators (RSI/MACD/ATR/...) each get
their own panel with their reference levels (e.g. RSI 30/70). Indicators are
calculated on the symbol's FULL stored bar history and then sliced to the
report's dates, so the required lookback is always included — a 20-day SMA
over a 10-day report window is still correct from its first plotted day.
"""

from services import indicator_library as il
from services.report_engine import charts

_PALETTE = ["#2979FF", "#D97706", "#8250df", "#dc2626", "#0969da", "#bf3989", "#65a30d"]


def _label_of(instance: dict) -> str:
    return il.instance_label(instance["key"], instance.get("params"))


def build_indicator_sections(bars: list, report_dates: list, instances: list) -> list:
    """[(title, svg_html)] — one price-panel chart (Close + every overlay
    output) if any overlay indicator is selected, then one chart per
    sub-panel indicator. *bars* ascending, each with "trade_date"; only
    bars whose date is in *report_dates* are plotted."""
    if not bars or not report_dates or not instances:
        return []
    wanted = set(report_dates)
    keep = [i for i, b in enumerate(bars) if b["trade_date"] in wanted]
    if not keep:
        return []
    x_labels = [bars[i]["trade_date"].strftime("%d-%b") for i in keep]

    def _slice(series):
        return [series[i] for i in keep]

    sections = []
    overlay_series = [{"label": "Close", "points": _slice([b["close"] for b in bars]),
                       "color": "#16a34a"}]
    overlay_titles = []
    color_i = 0

    for inst in instances:
        defn = il.get_definition(inst.get("key"))
        if defn is None:
            continue
        computed = il.compute(inst["key"], bars, inst.get("params"))
        codes = il.output_codes(inst)

        if defn["panel"] == "overlay":
            overlay_titles.append(_label_of(inst))
            for code, output in codes:
                overlay_series.append({
                    "label": code, "points": _slice(computed[output]),
                    "color": _PALETTE[color_i % len(_PALETTE)],
                    "dashed": output in ("Upper", "Lower"),
                })
                color_i += 1
        else:
            panel_series = []
            for code, output in codes:
                panel_series.append({
                    "label": code, "points": _slice(computed[output]),
                    "color": _PALETTE[color_i % len(_PALETTE)],
                })
                color_i += 1
            n = len(keep)
            for level in defn["levels"]:
                panel_series.append({"label": f"{level:g}", "points": [float(level)] * n,
                                     "color": "#94a3b8", "dashed": True})
            sections.append((
                f'{_label_of(inst)} — {defn["name"]}',
                charts.line_chart(panel_series, x_labels=x_labels, height=180, y_label=defn["key"]),
            ))

    if overlay_titles:
        sections.insert(0, (
            "Price with " + ", ".join(overlay_titles),
            charts.line_chart(overlay_series, x_labels=x_labels, y_label="Price"),
        ))
    return sections
