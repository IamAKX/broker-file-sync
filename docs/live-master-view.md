# 🔄 Live Master View

The Live Master View (LMV) is a floating window that shows a real-time merged table of all three broker data sources, auto-updating whenever any source file changes on disk.

---

## Opening LMV

1. Go to **Data Import**
2. Drop files onto all three broker cards (Sharekhan, ReliableSoftware, NiftyInvest)
3. Click **Run Watcher**

The LMV window opens and the watcher starts. A pulsing green dot in the top bar confirms it's active.

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
5. Output is written as `master.xlsx` using **BytesIO in-place write** — this preserves the file inode so Excel auto-reloads without prompting

---

## File Watcher

`services/watcher.py` uses `QFileSystemWatcher` to watch all three source files:

- **Debounce:** 300ms — rapid saves don't trigger multiple reloads
- **Retry:** 3 attempts with delay if the file is locked (e.g. Excel is mid-save)
- **Signals emitted:** `started`, `stopped`, `synced`, `sync_failed`

---

## Column Filter

Click **⚙ Columns** in the LMV toolbar to show/hide columns:

- Search by column name
- Toggle individual columns
- **Select All / Clear All** buttons
- Badge shows count of hidden columns

---

## Strategy Columns

Click **⚡ Strategies** in the LMV toolbar to choose which strategies apply. Active strategy columns appear on the right side of the table with a tinted header.

Conditional formatting rules are evaluated per cell — the cell background changes to the rule's color with auto-contrasted text (luminance check ensures readability).

---

## Auto-Refresh

Every time a source file is saved to disk, the LMV:
1. Re-reads all three broker files
2. Re-runs the merge
3. Re-applies active strategies
4. Re-renders the table

The scroll position is preserved between refreshes.

---

← [Back to README](../README)
