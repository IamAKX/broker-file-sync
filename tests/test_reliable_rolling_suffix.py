import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest


# ── _strip_rolling_suffix helper ───────────────────────────────────────────────

def test_strip_rolling_suffix_12d():
    from services.master_generator import _strip_rolling_suffix
    assert _strip_rolling_suffix("ABB LTD.rolling.12D") == "ABB LTD"


def test_strip_rolling_suffix_other_durations():
    from services.master_generator import _strip_rolling_suffix
    assert _strip_rolling_suffix("ADANIENT.rolling.11D") == "ADANIENT"
    assert _strip_rolling_suffix("ADANIENT.rolling.10D") == "ADANIENT"
    assert _strip_rolling_suffix("ADANIENT.rolling.7D") == "ADANIENT"


def test_strip_rolling_suffix_double_dot_company():
    # "BIOCON LIMITED..rolling.12D" → keep the single trailing dot
    from services.master_generator import _strip_rolling_suffix
    assert _strip_rolling_suffix("BIOCON LIMITED..rolling.12D") == "BIOCON LIMITED."


def test_strip_rolling_suffix_no_dots_unchanged():
    from services.master_generator import _strip_rolling_suffix
    assert _strip_rolling_suffix("INFY") == "INFY"


# ── config keys no longer carry the suffix ─────────────────────────────────────

def test_config_script_names_have_no_rolling_suffix():
    from config_defaults import SCRIPT_NAME_DATA
    assert all(".rolling." not in full for full, _ in SCRIPT_NAME_DATA)


# ── merge resolves any rolling duration against the (stripped) config ──────────

def _stub_readers(monkeypatch, rs_rows):
    monkeypatch.setattr(
        "services.live_merge.LiveDataReader._read_sharekhan",
        lambda self: (["Scrip Name", "Current"],
                      [["ADANIENT", 1.0], ["ABB", 2.0]]),
    )
    monkeypatch.setattr(
        "services.file_reader.read_reliable_software",
        lambda path: (["ScripName", "callstrikehighestoi"], rs_rows),
    )
    monkeypatch.setattr(
        "services.file_reader.read_nifty_invest",
        lambda path: (["Symbol", "Max Pain"], []),
    )


def test_live_merge_matches_11d_suffix(monkeypatch):
    from services.live_merge import LiveDataReader
    # Reliable file uses .rolling.11D; config (stripped) has "ADANIENT" → ADANIENT
    _stub_readers(monkeypatch, [["ADANIENT.rolling.11D", "CALL_OI_VAL"]])
    script_name_data = [("ADANIENT", "ADANIENT"), ("ABB LTD", "ABB")]
    reader = LiveDataReader("sk.xlsx", "rs.xlsx", "ni.csv", script_name_data)
    reader._read_slow_sources(force=True)
    headers, data = reader.read_merged(force_slow=True)

    oi_idx = headers.index("callstrikehighestoi")
    rows = {r[0]: r for r in data}
    assert rows["ADANIENT"][oi_idx] == "CALL_OI_VAL"


def test_live_merge_matches_double_dot_company_any_duration(monkeypatch):
    from services.live_merge import LiveDataReader
    monkeypatch.setattr(
        "services.live_merge.LiveDataReader._read_sharekhan",
        lambda self: (["Scrip Name", "Current"], [["BIOCON", 1.0]]),
    )
    monkeypatch.setattr(
        "services.file_reader.read_reliable_software",
        lambda path: (["ScripName", "callstrikehighestoi"],
                      [["BIOCON LIMITED..rolling.10D", "BIO_OI"]]),
    )
    monkeypatch.setattr(
        "services.file_reader.read_nifty_invest",
        lambda path: (["Symbol", "Max Pain"], []),
    )
    # Config key is the suffix-stripped form, including the trailing dot.
    script_name_data = [("BIOCON LIMITED.", "BIOCON")]
    reader = LiveDataReader("sk.xlsx", "rs.xlsx", "ni.csv", script_name_data)
    reader._read_slow_sources(force=True)
    headers, data = reader.read_merged(force_slow=True)

    oi_idx = headers.index("callstrikehighestoi")
    assert data[0][oi_idx] == "BIO_OI"
