# 🔄 Live Master View

The Live Master View (LMV) is a floating window that shows a real-time merged table of all three broker data sources, auto-updating whenever source data changes.

---

## Opening LMV

1. Go to **Data Import**
2. Drop files onto all three broker cards (Sharekhan, ReliableSoftware, NiftyInvest)
3. Click **Run Watcher**

The LMV window opens. A pulsing green dot in the toolbar confirms it is active.

---

## How Live Updates Work

### 🪟 Windows — COM Automation (TradeTiger)

TradeTiger uses **DDE (Dynamic Data Exchange)** to push live price ticks directly into an open Excel workbook (`Snap.xls`) in memory. The file on disk is **never updated continuously** — `QFileSystemWatcher` would never fire.

Instead, the app uses **COM automation** (`pywin32`) to read directly from the open Excel instance every **1 second**:

```
TradeTiger  →  DDE  →  Excel in memory (Snap.xls)
                               ↓
                    COM poll every 1s (pywin32)
                               ↓
                       Live Master View
```

**Prerequisites on Windows:**
```cmd
pip install pywin32
python -m pywin32_postinstall -install
```

**Setup flow:**
1. Open TradeTiger → Market Watch → right-click → **Snap to Excel**
2. Keep the `Snap.xls` Excel window **open**
3. Open Broker Sync → Run Watcher
4. LMV polls `Snap.xls` live every second

If `Snap.xls` is not open, the status bar shows: `Waiting for Snap.xls in Excel…`

### 🍎 macOS / Linux — File Watcher

Uses `QFileSystemWatcher` with a 300ms debounce to detect when source files are saved to disk. Works for any manually saved Excel/CSV file, but **cannot** detect TradeTiger's in-memory DDE updates (which are Windows-only anyway).

---

## Broker File Formats

Each broker exports Excel files in a different format. The file reader handles them automatically:

| Broker | Format | Header Row |
|--------|--------|------------|
| Sharekhan | `.xlsx` / `.xls` — TradeBook export | Row 8 |
| ReliableSoftware | `.xlsx` / `.xls` — Transactions export | Row 1 |
| NiftyInvest | `.csv` — Portfolio export | Row 1 |

---

## Merge Logic

`services/master_generator.py` performs a **3-way merge**:

1. **Sharekhan** is the primary source — all rows are included
2. **ReliableSoftware** rows are matched by script name and merged in
3. **NiftyInvest** rows are matched and merged in
4. Script name mapping from `config_defaults.py` normalises ticker symbols across brokers
5. Output is written as `master.xlsx` using **BytesIO in-place write** — preserves the file inode so Excel auto-reloads without prompting

---

## Toolbar

The LMV toolbar has six controls: **⊞ Filters**, **⚡ Strategies**, **↻ N-Day
Data**, **⭳ Export**, a value-change highlight-color swatch, and a reset
button (clears all filters, turns off all strategies). There is no separate
"Columns" button — it's nested inside **⊞ Filters** (see below). A previous
"Stop" button was removed as unused.

**↻ N-Day Data** manually re-fetches every `AVG_DAYS`/`MIN_DAYS`/etc. historic
aggregate column and every `VALUE_DAYS_AGO`/`VALUE_ON_DATE` historic value
column (see Strategy Columns below) — those don't update on every live tick
like the rest of the table, so this is how you pull a fresher value without
toggling a strategy or changing the category filter.

## Filters Panel

Click **⊞ Filters** to open a single unified popup covering everything that can
narrow down the table:

- **Columns** — opens the column visibility picker: search by name, toggle
  individual columns, **Select All / Clear All**, with a badge showing how many
  columns are currently hidden.
- **Category** — filter rows to strategies filed under a specific Strategy
  Builder category (`All` / `Daily` / `Weekly` / `Monthly` / `Common` / custom).
- **Sector** — filter rows to a single sector (from the sector/stock mapping in
  Config Editor), or `All`.
- **Clear all** — appears once any filter is active, resets Columns/Category/Sector
  together in one click.

## Strategy Columns

Click **⚡ Strategies** to choose which strategies apply — **only strategies
toggled Active in Strategy Builder appear in this picker** (an inactive strategy
never shows up here, so there's nothing to accidentally enable). Active strategy
columns appear on the right side of the table with a tinted header.

Conditional formatting rules are evaluated per cell — the cell background changes to the rule's color with auto-contrasted text (luminance check ensures readability).

If a strategy also has [Strategy Notifications](strategy-notifications.md)
enabled, every LMV refresh also runs that strategy's trigger/lifecycle
evaluation and can push System/Email alerts — this happens as part of the same
render pass described below, so notifications only fire while LMV is open.

A strategy column whose formula uses an `AVG_DAYS`/`MIN_DAYS`/etc. historic
aggregate function, or a `VALUE_DAYS_AGO`/`VALUE_ON_DATE` historic value
function (see [🧮 Strategy Builder → Historic (N days)
Aggregates](strategy-builder.md#historic-n-days-aggregates) and
[Historic Value (Point
Lookup)](strategy-builder.md#historic-value-point-lookup)) doesn't
recompute on every live tick like the rest — it needs a historic-snapshot
fetch, so it (re)computes on load, on a strategy toggle, on a category
change, or via the **↻ N-Day Data** toolbar button. **Click any cell in one
of those columns** to see the individual day-by-day values behind it for
that stock, pre-computed so the breakdown is right there without an extra
click. A strategy column with an ordinary (non-historic) formula, or any
native column, isn't clickable this way.

---

## Opening Range Columns

Two extra columns, `OR.High` / `OR.Low`, can appear in the table — the highest
High and lowest Low captured during the configured opening-range window (see
**Jobs** screen for the capture time). These are pulled from the backend's saved
opening-range snapshot for the day, not computed locally from the live feed.

---

## LMV Daily Snapshots

Beyond the live view itself, **Data → LMV Upload** lets you save the current LMV
grid (or a past one) to the backend as a dated snapshot, and **LMV Snapshot
Viewer** lets you browse previously saved snapshots — useful for keeping a
historical record of exactly what the merged table showed on a given day,
independent of the raw historic-value uploads.

---

## Auto-Refresh Behaviour

| Platform | Trigger | Interval |
|----------|---------|----------|
| Windows (COM) | QTimer poll | 200ms while data is actively changing, backing off to 1000ms after a quiet spell (adaptive) |
| macOS / Linux | File change event | Immediate + 300ms debounce |

On every poll/refresh cycle:
1. **Windows**: reads all rows from the `Streaming_Stock_Watch` sheet in the open Excel instance (macOS/Linux: reads whatever changed on disk)
2. Re-applies active strategies (formula columns + conditional formatting) — on a worker thread, not the GUI thread
3. Runs strategy-notification evaluation for any strategy with alerts enabled
4. Re-renders the table
5. Updates the status bar timestamp

---

← [Back to README](../README)
