"""Which cells changed since the last time this screen rendered — for
Inception's HMV and View by Date grids — LMV's "flash a cell amber on live
tick change" (screens.live_viewer.HighlightColorManagerDialog, services.
config_store's lmv_highlight_color/lmv_column_highlight_colors) doesn't
apply as-is: neither Inception screen has live ticks, nothing updates while
a render is on screen. The equivalent here is "changed since the last
Load/View" — comparing the newly rendered (headers, data) against the
previous render's, matched by Symbol (row order/count can differ between
renders — universe changes, sorting, a strategy toggle adding/removing
rows) rather than row position.

Both screens reuse screens.live_viewer.HighlightColorManagerDialog as-is
for picking colors (it's already generic — columns/default_color/
column_colors/theme, no LMV-specific state) and services.config_store's
inception_highlight_color/inception_column_highlight_colors for
persistence — this module is just the diff.
"""


def changed_cells(prev_headers: list, prev_data: list, headers: list, data: list,
                  symbol_col: str = "Symbol") -> set:
    """{(row_idx, col_idx), ...} — cells in *data* (indexed as returned,
    i.e. against *headers*) whose value differs from the same symbol's
    value in *prev_data*/*prev_headers* for the SAME column name.

    A column present in *headers* but not *prev_headers* (a strategy just
    toggled on, or the saved column order/filter changed which columns are
    visible) has nothing to compare against and is never flagged — same
    "nothing to compare, so nothing changed" rule a brand-new row (a symbol
    not in *prev_data* at all, e.g. newly synced) follows too. Empty/absent
    *prev_data* (the first Load/View this screen has ever done this
    session) means nothing is flagged at all — there's no "previous" yet.
    """
    if not prev_data or not prev_headers or symbol_col not in prev_headers or symbol_col not in headers:
        return set()
    prev_sym_idx = prev_headers.index(symbol_col)
    new_sym_idx = headers.index(symbol_col)
    prev_by_symbol = {row[prev_sym_idx]: row for row in prev_data}
    prev_col_idx = {name: i for i, name in enumerate(prev_headers)}

    changed = set()
    for r, row in enumerate(data):
        prev_row = prev_by_symbol.get(row[new_sym_idx])
        if prev_row is None:
            continue
        for c, name in enumerate(headers):
            pidx = prev_col_idx.get(name)
            if pidx is None:
                continue
            if row[c] != prev_row[pidx]:
                changed.add((r, c))
    return changed
