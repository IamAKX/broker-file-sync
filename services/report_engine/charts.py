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


def line_chart(series: list, width: int = 680, height: int = 260,
                x_labels: list | None = None, y_label: str = "",
                zero_line: bool = False) -> str:
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

    pad_left, pad_right, pad_top, pad_bottom = 48, 16, 16, 28
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
    max_labels = max(2, plot_w // 60)
    step = max(1, math.ceil(n / max_labels))
    for i in range(0, n, step):
        parts.append(
            f'<text x="{x_at(i):.1f}" y="{height - 8}" text-anchor="middle" '
            f'font-family="sans-serif" font-size="10" fill="#64748b">{_esc(labels[i])}</text>'
        )

    if y_label:
        parts.append(
            f'<text x="{12}" y="{pad_top - 4}" font-family="sans-serif" '
            f'font-size="10" fill="#64748b">{_esc(y_label)}</text>'
        )

    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg">{"".join(parts)}</svg>'
    )


def bar_chart(categories: list, values: list, width: int = 680, height: int = 220,
               color: str = "#2979FF", min_bar_width: int = 18) -> str:
    """Vertical bar chart, one bar per (category, value) pair. *width* is a
    target — if fitting ``len(categories)`` bars at *min_bar_width* each
    would exceed it, the returned SVG is WIDER than *width* instead of
    squeezing bars unreadably thin (every spec's "never compress N columns
    into an unreadable narrow chart" rule); callers render this inside a
    horizontally-scrollable container for that case, and PDF export lets it
    print at its natural width.
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
    bar_width = bar_slot * 0.6
    for i, (cat, v) in enumerate(zip(categories, values)):
        cx = pad_left + bar_slot * i + bar_slot / 2
        if v is None:
            continue
        bar_y = pad_top + plot_h - ((v - lo) / span) * plot_h
        bar_h = abs(zero_y - bar_y)
        top = min(bar_y, zero_y)
        parts.append(
            f'<rect x="{cx - bar_width / 2:.1f}" y="{top:.1f}" width="{bar_width:.1f}" '
            f'height="{max(bar_h, 1):.1f}" fill="{_esc(color)}" rx="2">'
            f'<title>{_esc(cat)}: {v:g}</title></rect>'
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
