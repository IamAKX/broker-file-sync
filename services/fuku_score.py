"""
Generic configurable weighted-rule scoring engine — the "Fuku Score" every
Reports spec (LMV EOD, EMV EOD, Fuku Live) describes, calculated the same
way in all three: a config owns a list of rule conditions, each worth some
points (optionally weighted), summed and clamped into a 0..max_score
result, resolved against configurable score bands (e.g. Strong/Moderate/
Weak, or whatever labels the user configures). No such engine existed
anywhere in this codebase before — screens.strategy_builder's "Score" field
is a single user-typed constant, not a computed rule-satisfaction score.

Rule conditions are plain token-expression lists — the SAME condition
format Strategy Builder's row_filter/fmt_rules and Inception's row_filter
already use (services.strategy_engine's compiled-formula machinery),
evaluated per-row via evaluate_condition(). This is a deliberate reuse: no
second condition-building UI/format is introduced by scoring.

Persistence: one JSON list of configs under a single config_store key (same
pattern as services.strategy_store's custom-category list, or services.
email_recipients_config's recipient list) — a score config is small,
low-cardinality per-user data (a handful per strategy/report), so it
doesn't need its own backend CRUD endpoint the way strategies.json's
richer conflict-resolution does; config_store.save_json/load_json already
gives it backend sync for free.
"""

import uuid

from services import config_store, strategy_engine

_SCORE_CONFIGS_KEY = "fuku_score_configs"


def new_rule(label: str, condition: list | None = None, points: float = 10.0,
             weight: float = 1.0, enabled: bool = True) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "label": label,
        "condition": condition or [],
        "points": points,
        "weight": weight,
        "enabled": enabled,
    }


def new_band(label: str, min_value: float, max_value: float, color: str = "#39d353") -> dict:
    return {"label": label, "min": min_value, "max": max_value, "color": color}


def default_bands(max_score: float = 100.0) -> list:
    """A sensible Strong/Moderate/Weak starter split of [0, max_score] —
    only ever used to seed a NEW config; every spec requires bands stay
    user-configurable, never hard-coded once a config is saved."""
    third = max_score / 3
    return [
        new_band("Weak", 0, third, "#dc2626"),
        new_band("Moderate", third, 2 * third, "#d97706"),
        new_band("Strong", 2 * third, max_score, "#16a34a"),
    ]


def new_config(name: str, max_score: float = 100.0, strategy_id: str | None = None) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "strategy_id": strategy_id,
        "max_score": max_score,
        "rules": [],
        "bands": default_bands(max_score),
    }


def load_all() -> list:
    return list(config_store.load_json(_SCORE_CONFIGS_KEY, []))


def save_all(configs: list) -> None:
    config_store.save_json(_SCORE_CONFIGS_KEY, list(configs))


def save_config(config: dict) -> None:
    """Upserts by id."""
    configs = load_all()
    for i, c in enumerate(configs):
        if c.get("id") == config.get("id"):
            configs[i] = config
            save_all(configs)
            return
    configs.append(config)
    save_all(configs)


def delete_config(config_id: str) -> None:
    save_all([c for c in load_all() if c.get("id") != config_id])


def get_config(config_id: str) -> dict | None:
    for c in load_all():
        if c.get("id") == config_id:
            return c
    return None


def config_for_strategy(strategy_id: str | None) -> dict | None:
    """The user-configured score config bound to *strategy_id*, or None when
    that strategy has none (callers then fall back to default_config())."""
    if not strategy_id:
        return None
    for c in load_all():
        if c.get("strategy_id") == strategy_id:
            return c
    return None


def default_config() -> dict:
    """Single always-true rule worth the full 100 — what a strategy scores
    against until the user configures real per-rule weights: a signal
    existing at all means its trigger condition fired. condition is a
    literal truthy 1, not [] (empty tokens compile to no expression, which
    evaluates to None -> False — see services.strategy_engine.evaluate)."""
    config = new_config("Fuku Score", max_score=100)
    config["rules"] = [new_rule("Trigger Condition", [{"type": "num", "value": "1"}], points=100)]
    return config


def signal_row_data(signal: dict) -> dict:
    """Flattens a live-alert signal into the {field: value} row a score
    rule's condition evaluates against: its price fields plus each
    target/stop-loss metric by name. Deliberately a SNAPSHOT of what the
    signal itself carries — LMV columns at entry time aren't stored."""
    row = {
        "Entry Price": signal.get("entry_price"),
        "High": signal.get("running_high"),
        "Low": signal.get("running_low"),
        "Exit Price": signal.get("exit_price"),
        "Score": signal.get("score"),
    }
    for m in (signal.get("metrics") or {}).values():
        if m.get("name"):
            row[m["name"]] = m.get("value")
    return {k: v for k, v in row.items() if v is not None}


def configs_by_strategy() -> dict:
    """{strategy_id: config} — one load_all() (a server round trip) for a
    caller scoring many signals, passed on to score_signal(configs=...)."""
    return {c["strategy_id"]: c for c in load_all() if c.get("strategy_id")}


def score_signal(signal: dict, strategy_id: str | None = None, configs: dict | None = None) -> dict:
    """compute_score() for one live-alert signal against its strategy's
    configured score config (or default_config()). *configs* is an optional
    pre-loaded configs_by_strategy() map so a table of rows doesn't pay a
    config_store round trip per row."""
    sid = strategy_id or signal.get("strategy_id")
    config = (configs.get(sid) if configs is not None else config_for_strategy(sid)) or default_config()
    row = signal_row_data(signal)
    return compute_score(config, row, [row])


def band_for(value: float, bands: list) -> dict | None:
    """Returns the first band whose [min, max] contains *value*, inclusive
    of both ends so a value sitting exactly on a shared boundary between two
    configured bands still resolves (to whichever is listed first) rather
    than falling through as unbanded. None if no band's range covers it —
    callers must handle an unbanded score (e.g. a max_score edited down
    below a band still using its old range)."""
    for band in bands:
        lo, hi = band.get("min"), band.get("max")
        if lo is None or hi is None:
            continue
        if lo <= value <= hi:
            return band
    return None


def compute_score(config: dict, row_data: dict, all_data: list | None = None,
                   **evaluate_kwargs) -> dict:
    """Evaluate every enabled rule in *config* against *row_data* (one
    stock/signal's field values) and return the score result:
      {"score", "max_score", "band", "rule_results": [...], "config_id",
       "config_name"}

    Each rule_results entry is {"id","label","points","weight","satisfied",
    "contribution"} — the per-rule breakdown every spec's "expandable rule
    detail" requirement needs.

    ``all_data``/``**evaluate_kwargs`` are forwarded to services.
    strategy_engine.evaluate_condition unchanged (self_value, agg_cache,
    sym_index, day_history, variable_store) for a rule whose condition
    references aggregate/day-history functions. ``all_data`` defaults to
    [row_data] alone when the caller has no wider row set to offer — true
    for most per-signal scoring contexts (e.g. Fuku Live scores one alert
    at a time).

    This result IS what every spec calls the score's "rule/version
    snapshot" — callers persist compute_score()'s own output (not just the
    bare number) alongside whatever it scored, so a later report reproduces
    exactly which rules fired without re-running the config as it might
    exist by then.
    """
    all_data = all_data if all_data is not None else [row_data]
    max_score = float(config.get("max_score", 100.0))

    total = 0.0
    rule_results = []
    for rule in config.get("rules", []):
        if not rule.get("enabled", True):
            continue
        satisfied = bool(strategy_engine.evaluate_condition(
            rule.get("condition", []), row_data, all_data, **evaluate_kwargs
        ))
        points = float(rule.get("points", 0.0))
        weight = float(rule.get("weight", 1.0))
        contribution = points * weight if satisfied else 0.0
        total += contribution
        rule_results.append({
            "id": rule.get("id"),
            "label": rule.get("label", ""),
            "points": points,
            "weight": weight,
            "satisfied": satisfied,
            "contribution": contribution,
        })

    score = max(0.0, min(total, max_score))
    return {
        "score": score,
        "max_score": max_score,
        "band": band_for(score, config.get("bands", [])),
        "rule_results": rule_results,
        "config_id": config.get("id"),
        "config_name": config.get("name", ""),
    }
