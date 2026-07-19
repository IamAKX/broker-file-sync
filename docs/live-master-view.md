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

## Column Filter

Click **⊞ Columns** in the LMV toolbar to show/hide columns:

- Search by column name
- Toggle individual columns
- **Select All / Clear All** buttons
- Badge shows count of hidden columns

---

## Strategy Columns

Click **⚡ Strategies** in the LMV toolbar to choose which strategies apply. Active strategy columns appear on the right side of the table with a tinted header.

Conditional formatting rules are evaluated per cell — the cell background changes to the rule's color with auto-contrasted text (luminance check ensures readability).

---

## Auto-Refresh Behaviour

| Platform | Trigger | Interval |
|----------|---------|----------|
| Windows (COM) | QTimer poll | Every 1 second |
| macOS / Linux | File change event | Immediate + 300ms debounce |

On Windows, every poll cycle:
1. Reads all rows from `Streaming_Stock_Watch` sheet in the open Excel instance
2. Re-applies active strategies
3. Re-renders the table
4. Updates the status bar timestamp

---

← [Back to README](../README)
