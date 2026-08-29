# 🧮 Strategy Builder

The Strategy Builder lets you create custom calculated columns on top of the Live Master View table — no code required.

---

## Concepts

| Term | Meaning |
|------|---------|
| **Strategy** | A named set of columns. Multiple strategies can be active simultaneously. |
| **Column** | A new column appended to LMV, computed per row using a formula. |
| **Formula** | A visual expression built from column tokens, numbers, operators, and functions. |
| **Conditional Formatting** | Color rules: if a condition is true, the cell gets a background color. First matching rule wins. |

---

## Creating a Strategy

1. Go to **Strategy Builder** in the sidebar
2. Click **+ New Strategy**
3. Give it a name
4. Click **+ Add Column**
5. Name the column and build a formula
6. Click **Save Strategy**
7. Toggle it **Active** — the column appears in Live Master View

---

## Formula Builder

Every formula in the app — a column's value, the Row Filter, a
conditional-formatting condition, a Notification's trigger/metrics — is
built in the same Expression Editor: a plain text box (type directly, or
click a Field/Function/Operator/Row/Constant/Variable in the catalogue to
insert it at the cursor), a **Compile & Test** button that validates against
your actually-loaded sheet and highlights exactly what's wrong if it
doesn't compile, and **Save**.

**Full reference — every function, every section, with examples:**
[📐 Formula Builder Reference](formula-builder.md).

---

## Conditional Formatting

Each column can have multiple color rules. The **first matching rule** wins.

### Special token: `THIS`
Refers to the computed value of the current column itself.

**Example rules:**
- If `THIS > 5` → color green `#22c55e`
- If `THIS < 0` → color red `#ef4444`
- If `[LTP] > [Prev Close]` → color blue `#3b82f6`

---

## Persistence

Strategies are saved to `strategies.json` in the app root directory. They reload automatically on next launch.

---

## Stacking Strategies

Multiple strategies can be active at the same time. Each active strategy appends its columns to the right side of the Live Master View table. Strategy columns are highlighted with a tinted header background.

---

## Notifications

Below Columns, each strategy also has a **Notifications** section for turning it
into a live trade-signal alert (entry alert, then Target/Stop Loss/Trailing Exit
tracking until the signal resolves) — see
[🔔 Strategy Notifications](strategy-notifications.md) for the full setup guide.

---

## Historic (N days) Aggregates

`AVG_DAYS`, `MIN_DAYS`, `MAX_DAYS`, `SUM_DAYS`, `COUNT_DAYS`, `STDDEV_DAYS`,
`MEDIAN_DAYS`, `VARIANCE_DAYS`, and `RANGE_DAYS` are functions in the same
formula language as everything else — right there in the Expression Editor's
Functions list, under "Historic (per stock, over the last N trading days)".
They work exactly like `AVG_ALL`/`SUM_ALL`/etc. except aggregating over
*historic days* for the *same stock* instead of across this tick's rows:

```
AVG_DAYS([High], 20)          — 20-day average High for this stock
MIN_DAYS([Low], 10)           — 10-day low
AVG_DAYS([MyComputedCol], 20) — 20-day average of another of THIS strategy's
                                 own columns — any custom formula, since a
                                 column can already be any custom formula
```

Because it's a formula function, not a separate feature, it works anywhere a
formula already works — a column's value, a conditional-formatting rule's
condition, a Notifications trigger condition, risk:reward, or a metric — with
no extra step. Combine it with other operators normally, e.g.
`[Current] > AVG_DAYS([High], 20)`.

**This is the one thing about it that isn't like every other formula
function:** it can't be computed from the row/sheet data alone — it needs a
historic-snapshot fetch from the backend (the same one the Data menu's
**Formula Stats** screen uses). So it does **not** recompute on every live
tick like a normal column does. It (re)computes:
- once when Live Master View first loads,
- again whenever you toggle a strategy on/off or change the category filter,
- or on demand via the **↻ N-Day Data** toolbar button.

Between those, the column just holds its last-computed value — a live price
crossing an `AVG_DAYS(...)` threshold updates correctly (the column's value is
stable, only the live side of the comparison moves), but the average itself
won't drift more current than that. While editing a formula that uses one of
these functions, **Compile & Test** can't run the real historic fetch either
— it reports a placeholder result and says so, rather than blocking Save.

**Click any cell in one of these columns in Live Master View** to see the
individual day-by-day values behind it for that stock — the same breakdown
the Data menu's Formula Stats screen shows on right-click, just one click
away since the stock and column are already known from where you clicked. A
strategy column with an ordinary (non-historic) formula isn't clickable this
way.

## Historic Value (Point Lookup)

`VALUE_DAYS_AGO`, `VALUE_ON_DATE`, `VALUE_AT_MAX_DAYS`, `VALUE_AT_MIN_DAYS`,
`VALUE_AT_MAX_DATES`, and `VALUE_AT_MIN_DATES` are a different kind of
historic function from the aggregates above — a **single historic value**,
not a Min/Max/Average over a window. They live in their own **Historic
Value** section in the Expression Editor's left nav (not folded into
Functions), right next to it:

```
VALUE_DAYS_AGO([High], 2)          — this stock's High exactly 2 trading days
                                       before today (0 = today/most recent)
VALUE_ON_DATE([High], 2026-07-15)  — this stock's High on that exact date
VALUE_AT_MAX_DAYS([High], [CWTO], 5) — High on whichever of the last 5
                                       trading days [CWTO] was at its highest
VALUE_AT_MIN_DAYS([Low], [CWTO], 5)  — same, for whichever day [CWTO] was at
                                       its lowest
VALUE_AT_MAX_DATES([High], [CWTO], 2026-08-10, 2026-08-14)
                                    — same as VALUE_AT_MAX_DAYS, but over an
                                       explicit calendar range instead of
                                       "the last N trading days" — for a
                                       window that doesn't line up to a
                                       trading-day count from today, e.g. one
                                       specific calendar week
VALUE_AT_MIN_DATES([Low], [CWTO], 2026-08-10, 2026-08-14)
                                    — same, for whichever day in the range
                                       [CWTO] was at its lowest
```

Clicking any of these opens a picker — pick a column, then either a "days
back" number, a calendar date (dotted where saved snapshot data actually
exists), or (for `VALUE_AT_MAX_DAYS`/`VALUE_AT_MIN_DAYS`/
`VALUE_AT_MAX_DATES`/`VALUE_AT_MIN_DATES`) a second **driver** column plus a
day count or a From/To date range — and the complete call is inserted for
you, ready to use, rather than typing it by hand.

`VALUE_AT_MAX_DAYS`/`VALUE_AT_MIN_DAYS`/`VALUE_AT_MAX_DATES`/
`VALUE_AT_MIN_DATES` take two columns: the first is what gets returned, the
second (the driver) is what decides which day in the window wins. Either
can be a raw sheet column or another of this strategy's own columns (any
custom formula), same as `AVG_DAYS`/etc. above — both column pickers offer
the full Fields list, not a restricted set.

> **Inception's Strategy Builder** (historical EOD data, not Live Master
> View) offers all six of these Historic Value functions too, resolved
> straight from each instrument's locally-synced bar history instead of a
> remote snapshot fetch — but **both** the value column **and** the driver
> column must be a raw OHLCV field (Open/High/Low/Close/Vol/OpenInt); a
> Group A/B (52WH, ATH, ...) or Formula Builder (MT, MB, ...) column on
> either side isn't resolved and the result is blank (`None`), same
> convention as `AVG_DAYS`/etc.'s own raw-field scoping there. Inception
> also has its own extra `VALUE_BEFORE_CHANGE` function — see below.

The `_DATES` pair's date range is **static** — typed into the formula, not
rolling — so "last week" means re-opening the picker (or editing the dates
by hand) to point at a new range each week, unlike `_DAYS`' N-trading-days
window, which is always relative to today.

Same non-live refresh cadence as Historic (N days) above (load/toggle/
category-change/**↻ N-Day Data**), same Compile & Test placeholder caveat,
and the same click-a-cell popup in Live Master View (for any of these four,
the popup drills into the *value* column's own history, not the driver's)
— it's the identical underlying mechanism, just resolving to one specific
day's value instead of an aggregate over several.

### VALUE_BEFORE_CHANGE (Inception's Strategy Builder only)

Inception's own Strategy Builder (historical EOD data, not Live Master
View) has one extra function in its **Historic Value** section that LMV's
doesn't: `VALUE_BEFORE_CHANGE` — "the value this column had immediately
before its CURRENT value last changed." It takes an **optional** second
argument:

```
VALUE_BEFORE_CHANGE([WT])       — "auto": walks back day by day (every
                                   trading day, not just month-ends), up to
                                   ~1 year, and returns the first day whose
                                   value actually differs from today's. Use
                                   this for anything that doesn't change on
                                   a fixed monthly schedule — e.g. WT
                                   changed last Tuesday: this finds that
                                   value directly, no need to know or name
                                   the interval.

VALUE_BEFORE_CHANGE([MT], 6)    — explicit months form: walks back one
                                   CALENDAR MONTH at a time, up to 6 months,
                                   comparing each prior month-end's value
                                   against today's. E.g. MT reads 400 for
                                   both August and July but was 382 in
                                   June: VALUE_BEFORE_CHANGE([MT], 6) -> 382.
                                   Use this only when you specifically want
                                   month-boundary comparisons rather than a
                                   day-by-day search.
```

Both forms return `None` if nothing differs within range, or there isn't
that much synced history yet. Works for both Group A/B columns (52WH,
ATH, ...) and Formula Builder columns (MT, MB, DT, DB, ...). In the
picker (click **VALUE_BEFORE_CHANGE** in the catalogue), pick a column,
then either leave the "Just find the previous changed value" checkbox on
(the auto form) or uncheck it and enter a months count. Same Compile &
Test placeholder caveat as every other Historic Value function above —
not offered in LMV's own Strategy Builder, since it needs Inception's
own per-symbol bar history to resolve.

---

## Row-Filter Streak ("Days True" / "Since")

Any strategy that has a **Row Filter** automatically gets two extra
read-only columns in Live Master View — nothing to build, no formula to
write:

| Column | Meaning |
|--------|---------|
| **\<Strategy Name> — Days True** | How many of the most recent consecutive historic days the Row Filter has evaluated true, counting back from the last saved day. |
| **\<Strategy Name> — Since** | The date that run started (the oldest day of the current streak). |

A strategy with no Row Filter (matches every row) doesn't get these columns
— "always true" has no streak worth tracking.

The lookback window is 60 trading days. If the Row Filter has been true for
the *entire* window, there's no way to tell from that fetch alone whether it
was already true further back — **Days True** shows `≥60` instead of a bare
number in that case, and **Since** is blank (the real start date is
unknown). A row that doesn't currently pass this strategy's filter (shown
because it matched a *different* active strategy) shows blank for both,
same as that strategy's own computed columns do.

Same non-live refresh cadence as Historic (N days)/Historic Value above
(load/toggle/category-change/**↻ N-Day Data**) — these aren't recomputed on
every live tick.

---

← [Back to README](../README)
