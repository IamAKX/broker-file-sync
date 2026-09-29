from services import fuku_score


def _cond(col, op, value):
    return [
        {"type": "col", "value": col},
        {"type": "op", "value": op},
        {"type": "num", "value": str(value)},
    ]


def test_compute_score_sums_points_for_satisfied_rules_only():
    config = fuku_score.new_config("Breakout Score", max_score=100)
    config["rules"] = [
        fuku_score.new_rule("Above Day Top", _cond("Close", ">", 100), points=20),
        fuku_score.new_rule("Above Week Top", _cond("Close", ">", 500), points=30),
    ]

    result = fuku_score.compute_score(config, {"Close": 150})

    assert result["score"] == 20
    assert result["max_score"] == 100
    assert result["rule_results"][0]["satisfied"] is True
    assert result["rule_results"][1]["satisfied"] is False
    assert result["rule_results"][1]["contribution"] == 0


def test_compute_score_applies_weight_and_clamps_to_max():
    config = fuku_score.new_config("Weighted", max_score=50)
    config["rules"] = [
        fuku_score.new_rule("A", _cond("X", ">", 0), points=40, weight=2.0),
    ]

    result = fuku_score.compute_score(config, {"X": 1})

    # 40 * 2.0 = 80, clamped to max_score=50
    assert result["score"] == 50


def test_compute_score_skips_disabled_rules():
    config = fuku_score.new_config("Disabled rule", max_score=100)
    config["rules"] = [
        fuku_score.new_rule("Always true but disabled", _cond("X", ">", 0),
                             points=50, enabled=False),
    ]

    result = fuku_score.compute_score(config, {"X": 1})

    assert result["score"] == 0
    assert result["rule_results"] == []


def test_band_for_resolves_matching_band():
    bands = fuku_score.default_bands(max_score=100)
    assert fuku_score.band_for(10, bands)["label"] == "Weak"
    assert fuku_score.band_for(50, bands)["label"] == "Moderate"
    assert fuku_score.band_for(90, bands)["label"] == "Strong"


def test_band_for_returns_none_when_no_band_covers_value():
    assert fuku_score.band_for(500, fuku_score.default_bands(100)) is None


def test_compute_score_result_carries_config_identity_for_auditability():
    config = fuku_score.new_config("Auditable")
    result = fuku_score.compute_score(config, {})
    assert result["config_id"] == config["id"]
    assert result["config_name"] == "Auditable"


def test_save_and_load_round_trip():
    config = fuku_score.new_config("Persisted")
    fuku_score.save_config(config)

    loaded = fuku_score.get_config(config["id"])
    assert loaded["name"] == "Persisted"

    config["name"] = "Renamed"
    fuku_score.save_config(config)
    assert fuku_score.get_config(config["id"])["name"] == "Renamed"
    assert len(fuku_score.load_all()) == 1


def test_delete_config_removes_by_id():
    a = fuku_score.new_config("A")
    b = fuku_score.new_config("B")
    fuku_score.save_config(a)
    fuku_score.save_config(b)

    fuku_score.delete_config(a["id"])

    remaining = fuku_score.load_all()
    assert len(remaining) == 1
    assert remaining[0]["id"] == b["id"]
