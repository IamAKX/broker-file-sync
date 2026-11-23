"""services.master_generator — broker-source name matching."""


def test_script_name_lookup_ignores_trailing_dot_and_spacing():
    """Issue #118: ReliableSoftware's "City Union Bank Ltd..rolling.20D"
    strips to "City Union Bank Ltd." while the Script Name tab says
    "City Union Bank Ltd" — must still map to CUB."""
    from services.master_generator import _build_script_name_lookup, _strip_rolling_suffix
    lookup = _build_script_name_lookup([("City Union Bank Ltd", "CUB"), ("BIOCON LIMITED.", "BIOCON"),
                                        ("NAVIN FLUORINE INTERNATI", "NAVINFLUOR")])
    full = _strip_rolling_suffix("City Union Bank Ltd..rolling.20D")
    assert full == "City Union Bank Ltd."
    assert lookup.get(full.lower()) == "CUB"
    assert lookup.get("biocon limited") == "BIOCON"            # config has the dot, file doesn't
    assert lookup.get("BIOCON LIMITED.") == "BIOCON"
    assert lookup.get("navin  fluorine internati") == "NAVINFLUOR"
    assert lookup.get("unknown") is None and "city union bank ltd." in lookup
