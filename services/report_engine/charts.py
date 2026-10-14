"""
Pure-Python inline-SVG chart generators for report HTML — no client-side JS,
no chart library dependency (see the package docstring for why). Every
function here returns a self-contained ``<svg>...</svg>`` string ready to
drop into a template's HTML, sized to its own *width*/*height* in pixels so
callers control layout entirely through normal CSS around it.

All chart functions are defensive about empty/degenerate input (no data,
all-zero values, a single point) — a report section with nothing to show
renders a small "No data" placeholder instead of a malformed/empty SVG, per
every spec's "graphs should be displayed properly" requirement.
"""

import html
import math

_NO_DATA_COLOR = "#94a3b8"


def _esc(value) -> str:
    return html.escape(str(value))


def _no_data_svg(width: int, height: int, message: str = "No data") -> str:
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="none"/>'
        f'<text x="{width / 2}" y="{height / 2}" text-anchor="middle" '
        f'dominant-baseline="middle" fill="{_NO_DATA_COLOR}" '
        f'font-family="sans-serif" font-size="13">{_esc(message)}</text>'
        f'</svg>'
    )


def donut_chart(segments: list, size: int = 180, thickness: int = 26,
                 center_label: str = "", center_sublabel: str = "") -> str:
    """*segments*: [{"label", "value", "color"}, ...]. Renders a ring built
    from stroke-dasharray arcs (one per segment, in the order given),
    starting at 12 o'clock, with *center_label*/*center_sublabel* as the
    headline text in the middle — every spec's "use the centre value for
    the headline metric" requirement.
    """
    positive = [s for s in segments if (s.get("value") or 0) > 0]
    total = sum(s["value"] for s in positive)
    if total <= 0:
        return _no_data_svg(size, size)

    radius = (size - thickness) / 2
    cx = cy = size / 2
    circumference = 2 * math.pi * radius

    arcs = []
    offset = 0.0
    for seg in positive:
        fraction = seg["value"] / total
        dash = fraction * circumference
        arcs.append(
            f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="none" '
            f'stroke="{_esc(seg.get("color", "#2979FF"))}" stroke-width="{thickness}" '
            f'stroke-dasharray="{dash:.2f} {circumference - dash:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}" transform="rotate(-90 {cx} {cy})">'
            f'<title>{_esc(seg.get("label", ""))}: {seg["value"]:g}</title>'
            f'</circle>'
        )
        offset += dash

    center = ""
    if center_label:
        center += (
            f'<text x="{cx}" y="{cy - (4 if center_sublabel else -4)}" text-anchor="middle" '
            f'font-family="sans-serif" font-size="{size * 0.14:.0f}" font-weight="700" '
            f'fill="#0F172A">{_esc(center_label)}</text>'
        )
    if center_sublabel:
        center += (
            f'<text x="{cx}" y="{cy + size * 0.11:.0f}" text-anchor="middle" '
            f'font-family="sans-serif" font-size="{size * 0.07:.0f}" '
            f'fill="#64748b">{_esc(center_sublabel)}</text>'
        )

    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" '
        f'xmlns="http://www.w3.org/2000/svg">{"".join(arcs)}{center}</svg>'
    )


def donut_legend(segments: list) -> str:
    """A small HTML legend (swatch + label + value) matching *segments* —
    kept separate from donut_chart's SVG so callers can lay it beside or
    below the ring rather than the chart function assuming one fixed
    position."""
    rows = []
    for seg in segments:
        rows.append(
            f'<div class="legend-row">'
            f'<span class="legend-swatch" style="background:{_esc(seg.get("color", "#2979FF"))}"></span>'
            f'<span class="legend-label">{_esc(seg.get("label", ""))}</span>'
            f'<span class="legend-value">{seg.get("value", 0):g}</span>'
            f'</div>'
        )
    return f'<div class="legend">{"".join(rows)}</div>'


def _legend_svg(series: list, width: int, y0: int) -> tuple:
    """(svg_parts, extra_height): a colour key under the plot — a short line
    swatch (dashed when the series is) plus its label, wrapped into rows."""
    items = [(s.get("label", ""), s.get("color", "#2979FF"), bool(s.get("dashed")))
             for s in series if s.get("label")]
    if not items:
        return [], 0
    parts, x, y, row_h = [], 8, y0 + 10, 16
    for label, color, dashed in items:
        w = 34 + 6.2 * len(str(label))
        if x + w > width - 8 and x > 8:
            x, y = 8, y + row_h
        dash = ' stroke-dasharray="4 3"' if dashed else ""
        parts.append(f'<line x1="{x}" y1="{y - 3}" x2="{x + 20}" y2="{y - 3}" stroke="{_esc(color)}" stroke-width="2.5"{dash}/>')
        parts.append(
            f'<text x="{x + 25}" y="{y}" font-family="sans-serif" font-size="10" fill="#334155">{_esc(label)}</text>'
        )
        x += w
    return parts, (y - y0) + 8


def line_chart(series: list, width: int = 680, height: int = 260,
                x_labels: list | None = None, y_label: str = "",
                zero_line: bool = False, legend: bool = True) -> str:
    """*series*: [{"label", "points": [float|None, ...], "color", "dashed": bool}, ...]
    — every series must have the same number of points, aligned to
    *x_labels* (or plain index labels if omitted). A None point renders as
    a gap (per every spec's "missing values must be visibly distinguished
    from zero" requirement) rather than being silently connected across.
    """
    series = [s for s in series if s.get("points")]
    if not series:
        return _no_data_svg(width, height)

    n = len(series[0]["points"])
    if n == 0:
        return _no_data_svg(width, height)

    pad_left, pad_right, pad_top, pad_bottom = 48, 16, 26, 28
    plot_w = max(1, width - pad_left - pad_right)
    plot_h = max(1, height - pad_top - pad_bottom)

    all_values = [v for s in series for v in s["points"] if v is not None]
    if not all_values:
        return _no_data_svg(width, height)
    lo, hi = min(all_values), max(all_values)
    if zero_line:
        lo, hi = min(lo, 0.0), max(hi, 0.0)
    if lo == hi:
        lo, hi = lo - 1, hi + 1
    span = hi - lo

    def x_at(i):
        return pad_left + (i / max(1, n - 1)) * plot_w

    def y_at(v):
        return pad_top + plot_h - ((v - lo) / span) * plot_h

    parts = []
    # Gridlines: 4 horizontal bands.
    for i in range(5):
        gy = pad_top + plot_h * i / 4
        parts.append(
            f'<line x1="{pad_left}" y1="{gy:.1f}" x2="{pad_left + plot_w}" y2="{gy:.1f}" '
            f'stroke="#E2E8F0" stroke-width="1"/>'
        )
        tick = hi - span * i / 4
        parts.append(
            f'<text x="{pad_left - 6}" y="{gy + 3:.1f}" text-anchor="end" '
            f'font-family="sans-serif" font-size="9" fill="#94a3b8">{tick:.1f}</text>'
        )

    if zero_line and lo < 0 < hi:
        zy = y_at(0)
        parts.append(
            f'<line x1="{pad_left}" y1="{zy:.1f}" x2="{pad_left + plot_w}" y2="{zy:.1f}" '
            f'stroke="#94a3b8" stroke-width="1.5"/>'
        )

    for s in series:
        color = _esc(s.get("color", "#2979FF"))
        dash = ' stroke-dasharray="6 4"' if s.get("dashed") else ""
        segment_points = []
        run = []
        for i, v in enumerate(s["points"]):
            if v is None:
                if len(run) > 1:
                    segment_points.append(run)
                run = []
                continue
            run.append((x_at(i), y_at(v)))
        if len(run) > 1:
            segment_points.append(run)

        for pts in segment_points:
            path = " ".join(f'{"M" if idx == 0 else "L"}{x:.1f},{y:.1f}' for idx, (x, y) in enumerate(pts))
            parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2"{dash}/>')

        for i, v in enumerate(s["points"]):
            if v is None:
                continue
            parts.append(
                f'<circle cx="{x_at(i):.1f}" cy="{y_at(v):.1f}" r="2.5" fill="{color}">'
                f'<title>{_esc(s.get("label", ""))}: {v:g}</title></circle>'
            )

    # X-axis labels — thinned to avoid overlap (spec: "reduce label density
    # while preserving access to every date via hover", which the per-point
    # <title> above already provides).
    labels = x_labels or [str(i) for i in range(n)]
    max_labels = max(2, plot_w // 80)
    step = max(1, math.ceil(n / max_labels))
    for i in range(0, n, step):
        # The final label would overhang the right edge if centered on its
        # point — right-align it instead of clipping it.
        anchor = "end" if x_at(i) + 30 > width else "middle"
        parts.append(
            f'<text x="{x_at(i):.1f}" y="{height - 8}" text-anchor="{anchor}" '
            f'font-family="sans-serif" font-size="10" fill="#64748b">{_esc(labels[i])}</text>'
        )

    if y_label:
        parts.append(
            f'<text x="{4}" y="{10}" font-family="sans-serif" '
            f'font-size="10" fill="#64748b">{_esc(y_label)}</text>'
        )

    total_height = height
    if legend:
        legend_parts, extra = _legend_svg(series, width, height)
        parts += legend_parts
        total_height = height + extra

    return (
        f'<svg width="{width}" height="{total_height}" viewBox="0 0 {width} {total_height}" '
        f'xmlns="http://www.w3.org/2000/svg">{"".join(parts)}</svg>'
    )


def bar_chart(categories: list, values: list, width: int = 680, height: int = 220,
               color: str = "#2979FF", min_bar_width: int = 18,
               negative_color: str | None = None, show_values: bool = False) -> str:
    """Vertical bar chart, one bar per (category, value) pair. *width* is a
    target — if fitting ``len(categories)`` bars at *min_bar_width* each
    would exceed it, the returned SVG is WIDER than *width* instead of
    squeezing bars unreadably thin (every spec's "never compress N columns
    into an unreadable narrow chart" rule); callers render this inside a
    horizontally-scrollable container for that case, and PDF export lets it
    print at its natural width.

    *negative_color* recolors bars below zero; *show_values* prints each
    bar's value above (or below, for negatives) it.
    """
    n = len(values)
    if n == 0:
        return _no_data_svg(width, height)

    pad_left, pad_right, pad_top, pad_bottom = 44, 12, 12, 30
    available = max(1, width - pad_left - pad_right)
    bar_slot = max(min_bar_width, available / n)
    plot_w = bar_slot * n
    actual_width = int(plot_w + pad_left + pad_right)
    plot_h = max(1, height - pad_top - pad_bottom)

    positive_values = [v for v in values if v is not None]
    lo = min(0.0, *positive_values) if positive_values else 0.0
    hi = max(0.0, *positive_values) if positive_values else 1.0
    if lo == hi:
        hi = lo + 1
    span = hi - lo
    zero_y = pad_top + plot_h - ((0 - lo) / span) * plot_h

    parts = [
        f'<line x1="{pad_left}" y1="{zero_y:.1f}" x2="{pad_left + plot_w:.1f}" y2="{zero_y:.1f}" '
        f'stroke="#CBD5E1" stroke-width="1"/>'
    ]
    # Y-axis values: the top, zero and bottom of the scale.
    for tick_value, tick_y in ((hi, pad_top), (0.0, zero_y), (lo, pad_top + plot_h)):
        parts.append(
            f'<text x="{pad_left - 6}" y="{tick_y + 3:.1f}" text-anchor="end" font-family="sans-serif" '
            f'font-size="9" fill="#94a3b8">{tick_value:.1f}</text>'
        )
    bar_width = bar_slot * 0.6
    for i, (cat, v) in enumerate(zip(categories, values)):
        cx = pad_left + bar_slot * i + bar_slot / 2
        if v is None:
            continue
        bar_y = pad_top + plot_h - ((v - lo) / span) * plot_h
        bar_h = abs(zero_y - bar_y)
        top = min(bar_y, zero_y)
        fill = negative_color if (negative_color and v < 0) else color
        parts.append(
            f'<rect x="{cx - bar_width / 2:.1f}" y="{top:.1f}" width="{bar_width:.1f}" '
            f'height="{max(bar_h, 1):.1f}" fill="{_esc(fill)}" rx="2">'
            f'<title>{_esc(cat)}: {v:g}</title></rect>'
        )
        if show_values:
            label_y = top + bar_h + 12 if v < 0 else top - 4
            parts.append(
                f'<text x="{cx:.1f}" y="{label_y:.1f}" text-anchor="middle" '
                f'font-family="sans-serif" font-size="10" font-weight="600" fill="#334155">{v:.2f}</text>'
            )

    max_labels = max(2, int(plot_w // 40))
    step = max(1, math.ceil(n / max_labels))
    for i in range(0, n, step):
        cx = pad_left + bar_slot * i + bar_slot / 2
        parts.append(
            f'<text x="{cx:.1f}" y="{height - 8}" text-anchor="middle" '
            f'font-family="sans-serif" font-size="10" fill="#64748b">{_esc(categories[i])}</text>'
        )

    return (
        f'<svg width="{actual_width}" height="{height}" viewBox="0 0 {actual_width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg">{"".join(parts)}</svg>'
    )


def progress_bar(fraction: float, color: str = "#16a34a", label: str = "") -> str:
    """A simple HTML (not SVG) progress bar — target/SL/investment-goal
    progress doesn't need SVG's geometry, just a filled div, so this stays
    plain CSS for simplicity. *fraction* is clamped to [0, 1]."""
    pct = max(0.0, min(1.0, fraction)) * 100
    label_html = f'<span class="progress-label">{_esc(label)}</span>' if label else ""
    return (
        f'<div class="progress-track">'
        f'<div class="progress-fill" style="width:{pct:.1f}%;background:{_esc(color)}"></div>'
        f'</div>{label_html}'
    )


def price_ladder(levels: list, ref_price: float | None, width: int = 620) -> str:
    """Support/resistance-style level map: one row per level, highest price
    on top. *levels*: [{"label", "price", "color", "emphasis": bool}, ...].
    Each row shows the label, the price over its line, and the % distance
    from *ref_price* (the current price) on the right. Rows are evenly
    spaced in price order — readable even when levels cluster, which a
    proportional price axis isn't (the ladder is a map of order and
    distance, not a scaled chart)."""
    rows = [l for l in levels if l.get("price") is not None]
    if not rows:
        return _no_data_svg(width, 80, "No levels")
    rows.sort(key=lambda l: -l["price"])
    gap = 30
    pad_top, pad_bottom = 8, 8
    height = pad_top + pad_bottom + gap * len(rows)
    line_x1, line_x2 = 150, width - 70
    parts = []
    for i, lvl in enumerate(rows):
        y = pad_top + gap * i + gap / 2 + 6
        color = _esc(lvl.get("color", "#64748b"))
        weight = 700 if lvl.get("emphasis") else 600
        stroke_w = 2.5 if lvl.get("emphasis") else 1.5
        parts.append(
            f'<text x="4" y="{y + 4:.1f}" font-family="sans-serif" font-size="10" '
            f'font-weight="{weight}" fill="{color}">{_esc(lvl.get("label", ""))}</text>'
        )
        if lvl.get("sub"):
            parts.append(
                f'<text x="4" y="{y + 14:.1f}" font-family="sans-serif" font-size="8" '
                f'fill="#94a3b8">{_esc(lvl["sub"])}</text>'
            )
        parts.append(
            f'<text x="{line_x1}" y="{y - 7:.1f}" font-family="sans-serif" font-size="12" '
            f'font-weight="700" fill="#0f172a">{lvl["price"]:,.2f}</text>'
        )
        parts.append(
            f'<line x1="{line_x1}" y1="{y:.1f}" x2="{line_x2}" y2="{y:.1f}" '
            f'stroke="{color}" stroke-width="{stroke_w}" stroke-linecap="round"/>'
        )
        if ref_price:
            pct = (lvl["price"] - ref_price) / ref_price * 100
            parts.append(
                f'<text x="{width - 4}" y="{y + 4:.1f}" text-anchor="end" font-family="sans-serif" '
                f'font-size="10" fill="#64748b">{pct:+.2f}%</text>'
            )
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg">{"".join(parts)}</svg>'
    )


def bubble_chart(points: list, width: int = 680, height: int = 320,
                 x_label: str = "", y_label: str = "", y_is_percent: bool = True) -> str:
    """Scatter of bubbles. *points*: [{"label", "x", "y", "size", "color"}].
    Bubble radius scales with *size* (6-18px); color is caller-chosen (the
    Fuku report uses green/red by direction-adjusted % move). A zero line is
    drawn when the y range crosses zero; labels are drawn beside bubbles and
    thinned when there are many."""
    pts = [p for p in points if p.get("x") is not None and p.get("y") is not None]
    if not pts:
        return _no_data_svg(width, height)

    pad_left, pad_right, pad_top, pad_bottom = 52, 20, 26, 38
    plot_w, plot_h = width - pad_left - pad_right, height - pad_top - pad_bottom
    xs, ys = [p["x"] for p in pts], [p["y"] for p in pts]
    x_lo, x_hi = min(xs), max(xs)
    y_lo, y_hi = min(min(ys), 0.0), max(max(ys), 0.0)
    if x_lo == x_hi:
        x_lo, x_hi = x_lo - 1, x_hi + 1
    if y_lo == y_hi:
        y_lo, y_hi = y_lo - 1, y_hi + 1
    y_span_pad = (y_hi - y_lo) * 0.1
    y_lo, y_hi = y_lo - y_span_pad, y_hi + y_span_pad

    def sx(v):
        return pad_left + (v - x_lo) / (x_hi - x_lo) * plot_w * 0.94 + plot_w * 0.03

    def sy(v):
        return pad_top + plot_h - (v - y_lo) / (y_hi - y_lo) * plot_h

    sizes = [p.get("size") or 0 for p in pts]
    s_lo, s_hi = min(sizes), max(sizes)

    def radius(size):
        if s_hi == s_lo:
            return 10
        return 6 + (size - s_lo) / (s_hi - s_lo) * 12

    parts = []
    for i in range(5):
        gy = pad_top + plot_h * i / 4
        val = y_hi - (y_hi - y_lo) * i / 4
        parts.append(f'<line x1="{pad_left}" y1="{gy:.1f}" x2="{pad_left + plot_w}" y2="{gy:.1f}" stroke="#E2E8F0"/>')
        parts.append(
            f'<text x="{pad_left - 6}" y="{gy + 3:.1f}" text-anchor="end" font-family="sans-serif" '
            f'font-size="9" fill="#94a3b8">{val:.1f}</text>'
        )
    if y_lo < 0 < y_hi:
        zy = sy(0)
        parts.append(f'<line x1="{pad_left}" y1="{zy:.1f}" x2="{pad_left + plot_w}" y2="{zy:.1f}" stroke="#94a3b8" stroke-width="1.5"/>')
    for i in range(5):
        gx = pad_left + plot_w * i / 4
        val = x_lo + (x_hi - x_lo) * i / 4
        parts.append(
            f'<text x="{gx:.1f}" y="{height - 20}" text-anchor="middle" font-family="sans-serif" '
            f'font-size="9" fill="#94a3b8">{val:.0f}</text>'
        )

    placed_labels: list = []   # (x, y) of labels already drawn — skip any that would collide
    for p in sorted(pts, key=lambda q: -(q.get("size") or 0)):
        cx, cy, r = sx(p["x"]), sy(p["y"]), radius(p.get("size") or 0)
        color = _esc(p.get("color", "#2979FF"))
        parts.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{color}" fill-opacity="0.55" '
            f'stroke="{color}" stroke-width="1"><title>{_esc(p.get("label", ""))}: {p["y"]:+.2f}{"%" if y_is_percent else ""}</title></circle>'
        )
        ly = cy - r - 3
        if all(abs(cx - ox) > 46 or abs(ly - oy) > 10 for ox, oy in placed_labels):
            placed_labels.append((cx, ly))
            parts.append(
                f'<text x="{cx:.1f}" y="{ly:.1f}" text-anchor="middle" font-family="sans-serif" '
                f'font-size="8" fill="#334155">{_esc(str(p.get("label", ""))[:12])}</text>'
            )
    if x_label:
        parts.append(
            f'<text x="{pad_left + plot_w / 2:.1f}" y="{height - 4}" text-anchor="middle" '
            f'font-family="sans-serif" font-size="10" fill="#64748b">{_esc(x_label)}</text>'
        )
    if y_label:
        parts.append(
            f'<text x="4" y="10" font-family="sans-serif" font-size="10" fill="#64748b">{_esc(y_label)}</text>'
        )
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg">{"".join(parts)}</svg>'
    )
