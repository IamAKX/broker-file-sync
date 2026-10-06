"""
Indicator Library (LMV/EMV specs §17/§18) — one extensible registry of
technical indicators, the single definition shared by strategy conditions
(configured indicators surface as Inception fields, see
services.inception_formula_builder_columns.compute_for_bars) and report
charts (services.indicator_charts), so the two can never silently disagree
on a formula or parameter set.

Adding an indicator = one @register(...) function below; nothing else in
Strategy Builder / the reports needs to change.

── Shape ────────────────────────────────────────────────────────────────
A definition: {key, name, category, panel ("overlay" on the price chart or
"sub" for its own panel), params [{name, label, type, default, min, max,
choices}], outputs [names], levels [reference lines], compute(bars, params)
-> {output: [value-or-None per bar]}}. Every series is aligned 1:1 with
*bars* (ascending, each {"open","high","low","close","volume",...}); a bar
without enough history yet is None.

A *configured indicator* ("instance") is a saved choice of definition +
parameters: {id, key, params}. Its label — "RSI(14)", "SMA(20)",
"MACD(12,26,9)" — doubles as the field code strategy conditions reference
(secondary outputs as "MACD(12,26,9).Signal"). Only non-default "source"
shows in the label, e.g. "SMA(20,high)".

Pure Python, no numpy/pandas: the desktop client doesn't ship them, and the
series involved (hundreds of daily bars) are tiny.
"""

import uuid

from services import config_store

_INSTANCES_KEY = "indicator_instances"

CATEGORIES = [
    "Trend & Moving Averages",
    "Momentum & Oscillators",
    "MACD / Trend-Momentum",
    "Volatility",
    "Volume",
    "Price / Breakout / Levels",
]

SOURCES = ["open", "high", "low", "close", "volume"]

_REGISTRY: dict = {}


def _period(default: int, label: str = "Period") -> dict:
    return {"name": "period", "label": label, "type": "int", "default": default, "min": 1, "max": 500}


_SOURCE_PARAM = {"name": "source", "label": "Source", "type": "choice", "default": "close", "choices": SOURCES}


def register(key: str, name: str, category: str, panel: str, params: list,
             outputs: list | None = None, levels: list | None = None):
    def deco(fn):
        _REGISTRY[key] = {
            "key": key, "name": name, "category": category, "panel": panel,
            "params": params, "outputs": outputs or [key], "levels": levels or [],
            "compute": fn,
        }
        return fn
    return deco


def get_definition(key: str) -> dict | None:
    return _REGISTRY.get(key)


def list_definitions() -> list:
    """Every registered definition, grouped by CATEGORIES order then name."""
    order = {c: i for i, c in enumerate(CATEGORIES)}
    return sorted(_REGISTRY.values(), key=lambda d: (order.get(d["category"], 99), d["name"]))


def default_params(key: str) -> dict:
    return {p["name"]: p["default"] for p in _REGISTRY[key]["params"]}


def _clean_params(defn: dict, params: dict | None) -> dict:
    """*params* validated against the definition: unknown names dropped,
    ints/floats coerced and clamped into [min, max], choices checked —
    anything invalid falls back to that param's default."""
    out = {}
    given = params or {}
    for p in defn["params"]:
        value = given.get(p["name"], p["default"])
        try:
            if p["type"] == "int":
                value = int(value)
            elif p["type"] == "float":
                value = float(value)
        except (TypeError, ValueError):
            value = p["default"]
        if p["type"] in ("int", "float"):
            value = max(p["min"], min(p["max"], value))
        elif p["type"] == "choice" and value not in p["choices"]:
            value = p["default"]
        out[p["name"]] = value
    return out


# ── Series helpers ───────────────────────────────────────────────────────

def _source(bars: list, name: str) -> list:
    return [b.get(name) for b in bars]


def _sma_of(values: list, period: int) -> list:
    out = [None] * len(values)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1:i + 1]
        if None not in window:
            out[i] = sum(window) / period
    return out


def _ema_of(values: list, period: int) -> list:
    """Seeded with the SMA of the first full window, k = 2/(period+1)."""
    out = [None] * len(values)
    k = 2.0 / (period + 1)
    prev = None
    for i, v in enumerate(values):
        if v is None:
            continue
        if prev is None:
            window = values[i - period + 1:i + 1] if i >= period - 1 else None
            if window is None or None in window:
                continue
            prev = sum(window) / period
        else:
            prev = v * k + prev * (1 - k)
        out[i] = prev
    return out


def _wilder(values: list, period: int) -> list:
    """Wilder's smoothing (alpha = 1/period), seeded with a simple average
    of the first *period* non-None values."""
    out = [None] * len(values)
    prev = None
    seed = []
    for i, v in enumerate(values):
        if v is None:
            continue
        if prev is None:
            seed.append(v)
            if len(seed) == period:
                prev = sum(seed) / period
                out[i] = prev
        else:
            prev = (prev * (period - 1) + v) / period
            out[i] = prev
    return out


# ── Trend & Moving Averages ──────────────────────────────────────────────

@register("SMA", "Simple Moving Average", "Trend & Moving Averages", "overlay", [_period(20), _SOURCE_PARAM])
def _sma(bars, p):
    return {"SMA": _sma_of(_source(bars, p["source"]), p["period"])}


@register("EMA", "Exponential Moving Average", "Trend & Moving Averages", "overlay", [_period(20), _SOURCE_PARAM])
def _ema(bars, p):
    return {"EMA": _ema_of(_source(bars, p["source"]), p["period"])}


@register("WMA", "Weighted Moving Average", "Trend & Moving Averages", "overlay", [_period(20), _SOURCE_PARAM])
def _wma(bars, p):
    values, n = _source(bars, p["source"]), p["period"]
    denom = n * (n + 1) / 2
    out = [None] * len(values)
    for i in range(n - 1, len(values)):
        window = values[i - n + 1:i + 1]
        if None not in window:
            out[i] = sum(w * v for w, v in enumerate(window, start=1)) / denom
    return {"WMA": out}


@register("VWAP", "Volume Weighted Average Price", "Trend & Moving Averages", "overlay", [_period(20)])
def _vwap(bars, p):
    """Rolling *period*-bar VWAP of the typical price (H+L+C)/3 — daily
    bars carry no intraday session to anchor to."""
    n = p["period"]
    out = [None] * len(bars)
    for i in range(n - 1, len(bars)):
        window = bars[i - n + 1:i + 1]
        vol = sum(b.get("volume") or 0 for b in window)
        if vol:
            out[i] = sum(((b["high"] + b["low"] + b["close"]) / 3) * (b.get("volume") or 0) for b in window) / vol
    return {"VWAP": out}


# ── Momentum & Oscillators ───────────────────────────────────────────────

@register("RSI", "Relative Strength Index", "Momentum & Oscillators", "sub", [_period(14), _SOURCE_PARAM],
          levels=[30, 70])
def _rsi(bars, p):
    values, n = _source(bars, p["source"]), p["period"]
    gains = [None] * len(values)
    losses = [None] * len(values)
    for i in range(1, len(values)):
        if values[i] is None or values[i - 1] is None:
            continue
        change = values[i] - values[i - 1]
        gains[i], losses[i] = max(change, 0.0), max(-change, 0.0)
    avg_gain, avg_loss = _wilder(gains, n), _wilder(losses, n)
    out = [None] * len(values)
    for i in range(len(values)):
        if avg_gain[i] is None:
            continue
        out[i] = 100.0 if avg_loss[i] == 0 else 100 - 100 / (1 + avg_gain[i] / avg_loss[i])
    return {"RSI": out}


@register("ROC", "Rate of Change %", "Momentum & Oscillators", "sub", [_period(12), _SOURCE_PARAM], levels=[0])
def _roc(bars, p):
    values, n = _source(bars, p["source"]), p["period"]
    out = [None] * len(values)
    for i in range(n, len(values)):
        if values[i] is not None and values[i - n]:
            out[i] = (values[i] - values[i - n]) / values[i - n] * 100
    return {"ROC": out}


@register("STOCH", "Stochastic Oscillator", "Momentum & Oscillators", "sub",
          [_period(14, "%K period"), {"name": "smooth", "label": "%D smoothing", "type": "int",
                                      "default": 3, "min": 1, "max": 100}],
          outputs=["%K", "%D"], levels=[20, 80])
def _stoch(bars, p):
    n = p["period"]
    k = [None] * len(bars)
    for i in range(n - 1, len(bars)):
        window = bars[i - n + 1:i + 1]
        hi, lo = max(b["high"] for b in window), min(b["low"] for b in window)
        k[i] = 50.0 if hi == lo else (bars[i]["close"] - lo) / (hi - lo) * 100
    return {"%K": k, "%D": _sma_of(k, p["smooth"])}


@register("CCI", "Commodity Channel Index", "Momentum & Oscillators", "sub", [_period(20)], levels=[-100, 100])
def _cci(bars, p):
    n = p["period"]
    tp = [(b["high"] + b["low"] + b["close"]) / 3 for b in bars]
    sma = _sma_of(tp, n)
    out = [None] * len(bars)
    for i in range(n - 1, len(bars)):
        mean_dev = sum(abs(v - sma[i]) for v in tp[i - n + 1:i + 1]) / n
        out[i] = 0.0 if mean_dev == 0 else (tp[i] - sma[i]) / (0.015 * mean_dev)
    return {"CCI": out}


# ── MACD ─────────────────────────────────────────────────────────────────

@register("MACD", "MACD", "MACD / Trend-Momentum", "sub",
          [{"name": "fast", "label": "Fast period", "type": "int", "default": 12, "min": 1, "max": 500},
           {"name": "slow", "label": "Slow period", "type": "int", "default": 26, "min": 1, "max": 500},
           {"name": "signal", "label": "Signal period", "type": "int", "default": 9, "min": 1, "max": 500},
           _SOURCE_PARAM],
          outputs=["MACD", "Signal", "Histogram"], levels=[0])
def _macd(bars, p):
    values = _source(bars, p["source"])
    fast, slow = _ema_of(values, p["fast"]), _ema_of(values, p["slow"])
    line = [f - s if f is not None and s is not None else None for f, s in zip(fast, slow)]
    signal = _ema_of(line, p["signal"])
    hist = [m - s if m is not None and s is not None else None for m, s in zip(line, signal)]
    return {"MACD": line, "Signal": signal, "Histogram": hist}


# ── Volatility ───────────────────────────────────────────────────────────

@register("BBANDS", "Bollinger Bands", "Volatility", "overlay",
          [_period(20), {"name": "stddev", "label": "Std deviations", "type": "float",
                         "default": 2.0, "min": 0.1, "max": 10.0}, _SOURCE_PARAM],
          outputs=["Middle", "Upper", "Lower"])
def _bbands(bars, p):
    values, n = _source(bars, p["source"]), p["period"]
    mid = _sma_of(values, n)
    upper, lower = [None] * len(values), [None] * len(values)
    for i in range(n - 1, len(values)):
        if mid[i] is None:
            continue
        window = values[i - n + 1:i + 1]
        sd = (sum((v - mid[i]) ** 2 for v in window) / n) ** 0.5   # population std dev, as TradingView/most platforms do
        upper[i], lower[i] = mid[i] + p["stddev"] * sd, mid[i] - p["stddev"] * sd
    return {"Middle": mid, "Upper": upper, "Lower": lower}


@register("ATR", "Average True Range", "Volatility", "sub", [_period(14)])
def _atr(bars, p):
    tr = [None] * len(bars)
    for i, b in enumerate(bars):
        if i == 0:
            tr[i] = b["high"] - b["low"]
        else:
            pc = bars[i - 1]["close"]
            tr[i] = max(b["high"] - b["low"], abs(b["high"] - pc), abs(b["low"] - pc))
    return {"ATR": _wilder(tr, p["period"])}


# ── Volume ───────────────────────────────────────────────────────────────

@register("OBV", "On-Balance Volume", "Volume", "sub", [])
def _obv(bars, p):
    out, total = [], 0.0
    for i, b in enumerate(bars):
        if i > 0:
            if b["close"] > bars[i - 1]["close"]:
                total += b.get("volume") or 0
            elif b["close"] < bars[i - 1]["close"]:
                total -= b.get("volume") or 0
        out.append(total)
    return {"OBV": out}


# ── Price / Breakout / Levels ────────────────────────────────────────────

@register("DONCHIAN", "Donchian Channel", "Price / Breakout / Levels", "overlay", [_period(20)],
          outputs=["Upper", "Lower"])
def _donchian(bars, p):
    n = p["period"]
    upper, lower = [None] * len(bars), [None] * len(bars)
    for i in range(n - 1, len(bars)):
        window = bars[i - n + 1:i + 1]
        upper[i], lower[i] = max(b["high"] for b in window), min(b["low"] for b in window)
    return {"Upper": upper, "Lower": lower}


# ── Public computation API ───────────────────────────────────────────────

def compute(key: str, bars: list, params: dict | None = None) -> dict:
    """{output: series} for definition *key* over *bars* with *params*
    (validated/defaulted). Raises KeyError for an unknown key."""
    defn = _REGISTRY[key]
    return defn["compute"](bars, _clean_params(defn, params))


def instance_label(key: str, params: dict | None = None) -> str:
    """"RSI(14)" / "SMA(20,high)" / "MACD(12,26,9)" — numeric params in
    definition order, plus source only when it isn't the default."""
    defn = _REGISTRY[key]
    p = _clean_params(defn, params)
    parts = []
    for spec in defn["params"]:
        if spec["name"] == "source":
            if p["source"] != spec["default"]:
                parts.append(p["source"])
        else:
            v = p[spec["name"]]
            parts.append(f"{v:g}" if isinstance(v, float) else str(v))
    return f"{key}({','.join(parts)})" if parts else key


def output_codes(instance: dict) -> list:
    """[(field_code, output_name)] for an instance: the first output keeps
    the plain label ("RSI(14)"), the others are "<label>.<Output>"."""
    defn = _REGISTRY[instance["key"]]
    label = instance_label(instance["key"], instance.get("params"))
    return [(label if i == 0 else f"{label}.{o}", o) for i, o in enumerate(defn["outputs"])]


def latest_values(bars: list, instances: list) -> dict:
    """{field_code: value as of the last bar} for every instance — the
    strategy-condition view of the library. An instance that can't compute
    (unknown key, too few bars) contributes None rather than raising."""
    out = {}
    for inst in instances:
        try:
            series = compute(inst["key"], bars, inst.get("params"))
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            for code, _ in _safe_codes(inst):
                out[code] = None
            continue
        for code, output in output_codes(inst):
            s = series.get(output) or []
            out[code] = s[-1] if s else None
    return out


def _safe_codes(inst: dict) -> list:
    try:
        return output_codes(inst)
    except KeyError:
        return []


# ── Configured indicators (persisted) ────────────────────────────────────

# In-memory copy — compute_for_bars runs per instrument on every HMV/EMV
# load (often the GUI thread), so it must never hit config_store.load_json's
# server round trip. peek_instances() is network-free; load_instances()
# warms it (screens that edit the library call that; reload_cache() on
# login/logout).
_cache: list | None = None


def new_instance(key: str, params: dict | None = None) -> dict:
    defn = _REGISTRY[key]
    return {"id": str(uuid.uuid4()), "key": key, "params": _clean_params(defn, params)}


def load_instances() -> list:
    global _cache
    if _cache is None:
        loaded = config_store.load_json(_INSTANCES_KEY, [])
        _cache = [i for i in loaded if isinstance(i, dict) and i.get("key") in _REGISTRY] \
            if isinstance(loaded, list) else []
    return list(_cache)


def peek_instances() -> list:
    return list(_cache) if _cache is not None else []


def _persist(instances: list) -> None:
    global _cache
    _cache = list(instances)
    config_store.save_json(_INSTANCES_KEY, _cache)
    _invalidate_dependents()


def _invalidate_dependents() -> None:
    """compute_for_bars memoizes per (symbol, bars, date) — a changed
    indicator set makes those entries stale."""
    from services import inception_formula_builder_columns
    inception_formula_builder_columns.clear_cache()


def field_codes() -> list:
    """Every field code the configured indicators expose to strategy
    conditions (see output_codes) — warms the cache if needed."""
    codes = []
    for inst in load_instances():
        codes += [code for code, _ in _safe_codes(inst)]
    return codes


def save_instance(instance: dict) -> None:
    """Upsert by id; an identical label already present (same key+params
    under another id) is not added twice."""
    instances = load_instances()
    label = instance_label(instance["key"], instance.get("params"))
    for i, existing in enumerate(instances):
        if existing.get("id") == instance.get("id"):
            instances[i] = instance
            _persist(instances)
            return
        if instance_label(existing["key"], existing.get("params")) == label:
            return
    instances.append(instance)
    _persist(instances)


def delete_instance(instance_id: str) -> None:
    _persist([i for i in load_instances() if i.get("id") != instance_id])


def reload_cache() -> None:
    global _cache
    _cache = None
