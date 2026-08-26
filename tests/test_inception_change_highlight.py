"""Tests for services/inception_change_highlight.py — pure logic, no Qt/DB."""
from services.inception_change_highlight import changed_cells


def test_no_previous_data_flags_nothing():
    headers = ["Symbol", "CLOSE"]
    data = [["ABB", 100]]
    assert changed_cells([], [], headers, data) == set()


def test_flags_cells_whose_value_differs_for_same_symbol():
    prev_headers = ["Symbol", "CLOSE", "MT"]
    prev_data = [["ABB", 100, 400], ["TCS", 200, 50]]
    headers = ["Symbol", "CLOSE", "MT"]
    data = [["ABB", 105, 400], ["TCS", 200, 60]]

    assert changed_cells(prev_headers, prev_data, headers, data) == {(0, 1), (1, 2)}


def test_symbol_matched_not_row_position_matched():
    """Row order/count differing between the two renders (universe change,
    sort, filter) must not produce false positives — matched by Symbol,
    not by row index."""
    prev_headers = ["Symbol", "CLOSE"]
    prev_data = [["TCS", 200], ["ABB", 100]]   # TCS first
    headers = ["Symbol", "CLOSE"]
    data = [["ABB", 100], ["TCS", 200]]        # ABB first, same values

    assert changed_cells(prev_headers, prev_data, headers, data) == set()


def test_new_symbol_not_in_previous_is_not_flagged():
    prev_headers = ["Symbol", "CLOSE"]
    prev_data = [["ABB", 100]]
    headers = ["Symbol", "CLOSE"]
    data = [["ABB", 100], ["NEWCO", 50]]   # newly synced instrument
    assert changed_cells(prev_headers, prev_data, headers, data) == set()


def test_column_absent_from_previous_is_not_flagged():
    """A strategy column just toggled on has nothing to compare against —
    not flagged, same as a brand-new row."""
    prev_headers = ["Symbol", "CLOSE"]
    prev_data = [["ABB", 100]]
    headers = ["Symbol", "CLOSE", "My Strategy Col"]
    data = [["ABB", 100, 999]]
    assert changed_cells(prev_headers, prev_data, headers, data) == set()


def test_missing_symbol_column_returns_empty():
    assert changed_cells(["A"], [[1]], ["A"], [[2]]) == set()
