"""Column catalogue for Inception's historical EOD dataset — ports the ~70
derived columns from the backend's (now-removed) app/services/
inception_columns.py verbatim, now the single source of truth on THIS
client: Group A/B computation moved here entirely (see
services.inception_formula_engine), so the backend no longer knows these
column names exist at all — it only ever serves raw bars (api.inception_api.
get_bars) for this client to compute from.

Every column here is a field name the Strategy Builder's Fields list offers
and services.inception_compute_service produces a value for. Strategy
formulas reference these fields exactly like they always did — nothing
about the token/formula shape changed, only where the values underneath
come from.

── RAW vs derived ───────────────────────────────────────────────────────────
RAW_FIELDS are the bar's own OHLCV fields (not computed — services.
inception_bars_store already stores exactly these).

── Group A vs Group B ───────────────────────────────────────────────────────
GROUP_A: ~47 columns computable with a single forward pass per instrument —
running period (day/week/quarter/half-year/year/financial-year) high/low/
open/close bookkeeping, 52-week and all-time high/low, period top/bottom of
the last 2 periods.

GROUP_B: 24 "gap area" columns (12 daily + 12 weekly) — stateful: whether an
area is still "unfilled" depends on every day since it opened. See
services.inception_formula_engine's module docstring for the exact state
machine. Every Group B entry expands to 3 stored metrics: "<CODE> LOW",
"<CODE> HIGH", "<CODE> DATE" (a gap area is a price range, not a single
number).
"""

RAW_FIELDS = ["OPEN", "HIGH", "LOW", "CLOSE", "VOL", "OPENINT"]

# code -> description, ported verbatim from the backend catalogue.
GROUP_A: dict[str, str] = {
    "P.OPEN": "Previous day open",
    "P.HIGH": "Previous day high",
    "P.LOW": "Previous day low",
    "P.CLOSE": "Previous day close",
    "P.QTY": "Previous day volume",
    "P.OI": "Previous day open interest",
    "% CHG PDC AND OPEN": "Percentage change between previous day close and current day open",
    "% CHG PWC AND OPEN": "Percentage change between previous week close and current week open",
    "DAY % CHANGE": "Percentage change between current day close and previous day close",
    "52WH": "52 week high — max(highest high of all highs of last 52 weeks)",
    "52WL": "52 week low — min(lowest low of all lows of last 52 weeks)",
    "ATH": "All time high — max(highest high of all highs from the date of inception)",
    "ATL": "All time low — min(lowest low of all lows from the date of inception)",
    "CQH": "Current quarter high — max(highs of the current calendar quarter till the last working day); resets on the first trading day of the quarter",
    "CQO": "Current quarter open — open of current running calendar quarter",
    "CQL": "Current quarter low — min(lows of the current calendar quarter till the last working day); resets on the first trading day of the quarter",
    "PQH": "Previous quarter high — max(highest high of all highs of working days of previous calendar quarter)",
    "PQO": "Previous quarter open",
    "PQL": "Previous quarter low — min(lowest low of all lows of working days of previous calendar quarter)",
    "PQC": "Previous quarter close — close price on the last working day of previous calendar quarter",
    "QT": "Quarter top — max(PQC of last 2 quarters)",
    "QB": "Quarter bottom — min(PQC of last 2 quarters)",
    "CHYH": "Current half-year high; resets on the first trading day of the half year",
    "CHYO": "Current half-year open",
    "CHYL": "Current half-year low; resets on the first trading day of the half year",
    "PHYH": "Previous half-year high",
    "PHYO": "Previous half-year open",
    "PHYL": "Previous half-year low",
    "PHYC": "Previous half-year close — close price on the last working day of previous calendar half year",
    "HYT": "Half-year top — max(PHYC of last 2 half years)",
    "HYB": "Half-year bottom — min(PHYC of last 2 half years)",
    "CYH": "Current year high; resets on the first trading day of the year",
    "CYO": "Current year open",
    "CYL": "Current year low; resets on the first trading day of the year",
    "PYH": "Previous year high",
    "PYO": "Previous year open",
    "PYL": "Previous year low",
    "PYC": "Previous year close — close price on the last working day of previous calendar year",
    "YT": "Year top — max(PYC of last 2 years)",
    "YB": "Year bottom — min(PYC of last 2 years)",
    "CFYH": "Current financial year high (Apr 1 start); reset to zero on the first working day of the financial year",
    "CFYO": "Current financial year open",
    "CFYL": "Current financial year low (Apr 1 start); reset to zero on the first working day of the financial year",
    "PFYH": "Previous financial year high",
    "PFYO": "Previous financial year open",
    "PFYL": "Previous financial year low",
    "PFYC": "Previous financial year close — close price on the last working day (Mar 31) of previous financial year",
}

# 4 buckets x {UF, FD} x {GUP, GDN} x {1,2,3}. Each becomes 3 stored metrics:
# "<CODE> LOW"/"<CODE> HIGH" (the gap area's price bounds) and "<CODE> DATE"
# (when the gap opened).
_GAP_PERIODS = ("DAY", "WEEK")
_GAP_FILL_STATES = ("UF", "FD")   # unfilled, filled
_GAP_DIRECTIONS = ("GUP", "GDN")  # gap up, gap down
_GAP_RANKS = (1, 2, 3)            # recent-most .. 3rd recent-most

GROUP_B: dict[str, str] = {}
for _period in _GAP_PERIODS:
    _label = "Daily" if _period == "DAY" else "Weekly"
    for _fill in _GAP_FILL_STATES:
        _fill_label = "unfilled" if _fill == "UF" else "filled"
        for _direction in _GAP_DIRECTIONS:
            _dir_label = "up" if _direction == "GUP" else "down"
            for _rank in _GAP_RANKS:
                _rank_label = {1: "recent most", 2: "2nd recent most", 3: "3rd recent most"}[_rank]
                code = f"{_period} {_fill} {_direction} {_rank}"
                GROUP_B[code] = (
                    f"{_label} {_fill_label} gap-{_dir_label} area {_rank_label} — "
                    f"previous {_label.lower()[:-2] if _period == 'DAY' else 'week'} close vs "
                    f"current {'day' if _period == 'DAY' else 'week'} open, "
                    f"gap % beyond the configured threshold, "
                    f"{'not yet' if _fill == 'UF' else 'already'} closed back through"
                )
del _period, _label, _fill, _fill_label, _direction, _dir_label, _rank, _rank_label, code

GAP_METRIC_SUFFIXES = ("LOW", "HIGH", "DATE")


def gap_metric_names(gap_code: str) -> list[str]:
    return [f"{gap_code} {suffix}" for suffix in GAP_METRIC_SUFFIXES]


def all_derived_codes() -> list[str]:
    return list(GROUP_A) + list(GROUP_B)


def is_stateful_gap(code: str) -> bool:
    return code in GROUP_B


class ColumnInfo:
    __slots__ = ("code", "description", "group", "stateful_gap")

    def __init__(self, code: str, description: str, group: str, stateful_gap: bool):
        self.code = code
        self.description = description
        self.group = group
        self.stateful_gap = stateful_gap


def column_catalogue() -> list[ColumnInfo]:
    """Full catalogue for the Strategy Builder Fields list — raw fields
    first (group 'raw'), then Group A ('derived'), then Group B ('derived',
    stateful_gap=True).

    Each Group B code appears FOUR times: the bare code itself (e.g. "DAY UF
    GUP 1"), aliased to its HIGH bound — the single number most formulas
    want — plus its three explicit LOW/HIGH/DATE sub-fields for anyone who
    wants the full range or the date it opened (see
    services.inception_compute_service's gap-alias step, and
    gap_metric_names below).
    """
    out = [ColumnInfo(f, f"Raw uploaded field ({f})", "raw", False) for f in RAW_FIELDS]
    out += [ColumnInfo(code, desc, "derived", False) for code, desc in GROUP_A.items()]
    for code, desc in GROUP_B.items():
        out.append(ColumnInfo(code, f"{desc} — alias for {code} HIGH", "derived", True))
        for name in gap_metric_names(code):
            out.append(ColumnInfo(name, desc, "derived", True))
    return out
