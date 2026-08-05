# 🔔 Strategy Notifications

Strategy Notifications turn a Strategy Builder strategy into a live trade-signal
alert: when a condition you define holds true for long enough to rule out a false
breakout, you get an **entry alert** with computed Stop Loss / Target / Risk:Reward
figures — then the app keeps watching that stock until the signal resolves (a
Target hit, or a stop-out), sending a follow-up alert at each step, delivered by
System tray, Email, or Telegram (once implemented), whichever you've enabled.

This is a different mechanism from conditional formatting: formatting rules just
color a cell. Notifications track a stock's story over time — entry → target(s) →
resolution — and push that story to you instead of requiring you to watch the
screen.

---

## ⚡ Setup Guide

1. **Open Strategy Builder** and select (or create) a strategy. It needs at least
   one column if your trigger/metrics should reference a computed value — you can
   also reference raw LMV columns directly without adding any columns first.
2. Scroll down past **Columns** to the **Notifications** section.
3. Toggle **Enabled** on.
4. Set **Direction** — `BUY` or `SELL`. This decides which way "hit" and
   "stopped out" mean for every metric below.
5. Click **Edit Condition…** under **Trigger Condition** and build the condition
   that should start a signal (see [Trigger Condition](#-trigger-condition) below).
6. Set **Debounce (minutes)** — how long the condition must hold continuously
   before an entry alert actually fires (default 2).
7. *(Optional)* Set a **Strength/Weakness Score** — a plain number, shown on the
   entry alert.
8. *(Optional)* Check **Risk : Reward → Enabled** and set the Numerator/Denominator
   formulas.
9. Click **+ Add Metric** for Stop Loss, each Target, and Trailing Exit as needed
   (see [Metrics](#-metrics) below) — add as many `target` metrics as you want
   (Target 1, Target 2, Target 3, ...).
10. Click **Save Strategy**.
11. **Make sure the strategy itself is toggled Active** in the strategy list
    (the toggle switch on its card) — an inactive strategy is never evaluated,
    notifications included, regardless of what's configured inside it.
12. Go to **Notifications** in the sidebar and confirm the channels you want
    (System / Email) are switched on. Telegram is visible but not delivered yet
    (see [Delivery Channels](#-delivery-channels)).
13. **Open Live Master View and start the watcher.** This part matters:
    notifications are only evaluated as part of LMV's live render loop — if LMV
    isn't open, nothing is being checked, no matter how long you wait.
14. Check **Live Alerts** in the sidebar to see signals as they open, progress,
    and resolve.

---

## 🧭 Notification Lifecycle

```
 no signal
    │  trigger condition becomes true for a stock
    ▼
 pending ──(condition goes false before debounce elapses)──► cleared, back to "no signal"
    │
    │  condition stays true continuously for the full debounce window
    ▼
 ENTRY ALERT fires — Stop Loss / Target(s) / Score / Risk:Reward computed once, frozen
    │
    ▼
  open ──── every tick after entry ────────────────────────────────────────
    │
    ├─ Trailing Exit metric(s): recomputed fresh every tick (expected to move)
    ├─ each Target metric: checked for a favorable crossing
    │      → first time it's crossed: fires its OWN "Target achieved" alert,
    │        signal stays open if other targets remain
    ├─ Stop Loss / Trailing Exit: checked for an unfavorable crossing
    │      → first one crossed: fires a "Stopped Out" alert, resolves immediately
    ▼
resolved — moved into Live Alerts history — either:
    • every Target metric achieved (last one's alert already sent), or
    • a Stop Loss/Trailing Exit crossing stopped it out
```

Key rules:
- **Only one pending/open signal per strategy per stock at a time.** If the trigger
  fires again for a stock that's already pending or open under the same strategy,
  it's ignored until that signal resolves.
- **Debounce is wall-clock, not tick-count** — it doesn't matter how fast or slow
  the Live Master View is polling; "2 minutes" means 2 real minutes of the
  condition holding continuously. Any single tick where it reads false resets the
  timer back to zero.
- **`informational` metrics never trigger anything.** They're computed at entry
  and just shown as extra context — nothing crosses/achieves them.
- Stop Loss and Target values are **frozen at entry** (computed once, from the
  price/columns at that moment). Trailing Exit is the one exception — it's
  **recomputed every tick** for as long as the signal is open, which is exactly
  what lets it "trail" price as described below.

---

## 🎯 Trigger Condition

The trigger is a single standalone condition — **not** "pick one of this
strategy's columns' existing conditional-formatting rules". That option was
deliberately removed: conditional formatting is defined per-column, and a
strategy can have several columns, each with its own independent rules, so
there's no single well-defined "the strategy's rule" to point at.

Instead, **Edit Condition…** opens the same chip-based formula builder used
everywhere else in Strategy Builder (Row Filter, fmt-rule conditions), and it can
reference:
- Any raw column from the loaded Live Master View (`[LTP]`, `[High]`, `[Open]`, …)
- Any of this strategy's own computed columns, by name
- Combined with `AND` / `OR`, comparison operators (`>`, `<`, `>=`, `<=`, `==`,
  `!=`), functions, and constants — exactly like a row filter.

**Examples:**

| Goal | Condition |
|---|---|
| Price breaks above previous month's high | `[Current] > [PMH]` |
| Price breaks a resistance column your strategy computes | `[Current] > [Resistance]` |
| Price above open, high, close, and a computed pivot, all at once (the union used in the worked example below) | `( [Current] > [Open] ) AND ( [Current] > [Close] ) AND ( [Current] > [PMH] )` |
| Sell breakdown below a support level | `[Current] < [Support]` |
| Only fire during a volume spike | `( [Current] > [PMH] ) AND ( [Volume] > AVG_ALL(Volume) )` |

`THIS` is **not** available here (unlike a column's own fmt-rule condition) —
a trigger condition isn't "owned" by one column, so there's no single self-value
for it to mean.

A trigger condition can also use a historic aggregate function —
`[Current] > AVG_DAYS([High], 20)` fires when price breaks above its own
20-day average High. See [🧮 Strategy Builder → Historic (N days)
Aggregates](strategy-builder.md#historic-n-days-aggregates) for the full
function list and, importantly, how its refresh cadence differs from every
other column (not live every tick).

---

## ⏱ Debounce (minutes)

Guards against false breakouts: a condition that flickers true for one tick and
false the next never fires an alert. Set to `0` to fire as soon as the condition
is next confirmed true on a following tick; higher values require it to hold for
that many real minutes, uninterrupted, first.

---

## 💯 Strength/Weakness Score

A plain constant number you type in — not computed from any formula or column.
It's shown on the entry alert only, for you to set based on however you weigh
that particular strategy's setups (e.g. from a variable/formula you've already
worked out elsewhere in Strategy Builder). Leave it blank for no score.

---

## ⚖️ Risk : Reward

Off by default. When **Enabled**, set:
- **Numerator** — a formula, e.g. `[Current] - 1360` (entry price minus your
  intended Stop Loss level, for a buy)
- **Denominator** — a formula, e.g. `1380 - [Current]` (your intended Target 1
  level minus entry price)

Both are evaluated once, at entry, using the same combined column picker as
everything else (this strategy's columns + any LMV column) — **not** a
reference to the Stop Loss/Target metrics themselves (see the limitation under
[Metrics](#-metrics)), so if you also add those as metrics, keep the numbers in
sync by hand. The ratio (`numerator ÷ denominator`) is computed and shown on the
entry alert as `Risk:Reward = <numerator>:<denominator> (<ratio>)`. It is
**not** re-evaluated after entry.

---

## 📊 Metrics

An open-ended list — add as many as you need, each with a **Name**, a **Role**,
and a **Formula**. The role tells the engine how to treat it:

| Role | When it's (re)computed | What triggers a notification |
|---|---|---|
| `stop_loss` | Frozen once, at entry | Unfavorable crossing → **Stopped Out** alert, signal resolves |
| `target` | Frozen once, at entry | Favorable crossing → its own **Target achieved** alert; signal stays open until every `target` metric is achieved |
| `trailing_exit` | **Recomputed every tick** while open | Unfavorable crossing (of its *current* value) → **Stopped Out** alert, signal resolves |
| `informational` | Frozen once, at entry | Never — display-only, shown on the entry alert for context |

"Favorable"/"unfavorable" depend on **Direction**:
- `BUY`: a Target is hit when price rises to/above it; a Stop Loss/Trailing Exit
  stops you out when price falls to/below it.
- `SELL`: reversed — a Target is hit falling to/below it; stopped out rising
  to/above it.

You can add **multiple `target` metrics** (Target 1, Target 2, Target 3, ...) —
each is tracked and notified independently; see the worked example below for the
exact sequence.

A metric's formula can reference:
- A fixed number (e.g. Stop Loss = a constant price)
- Any LMV column (e.g. an ATR, Williams %R, or Fibonacci-level column you've
  already built via Formula Builder / this strategy's own columns)
- A historic aggregate function, e.g. `AVG_DAYS([Low], 10)` as a trailing stop
  loss — see [🧮 Strategy Builder → Historic (N days)
  Aggregates](strategy-builder.md#historic-n-days-aggregates). Its caveat
  applies here too: a `trailing_exit` metric re-evaluates every tick, but an
  `AVG_DAYS(...)` inside it only actually changes when the historic data
  itself refreshes (load/strategy-toggle/**↻ N-Day Data**) — it won't drift
  intraday the way a live-data trailing formula would.
- Any combination via the same formula builder used elsewhere

**Important limitation**: a metric's formula evaluates against the stock's live
LMV/strategy-column data only — it **cannot** reference the signal's own entry
price, another metric's value, or whether a target has already been achieved.
That means a rule like *"stop-loss becomes cost price once price crosses X, then
becomes Target 1's price once Target 1 hits"* isn't directly expressible today.
What **does** work well is a `trailing_exit` formula built from an indicator that
naturally trails price on its own — an ATR-based stop, a Chandelier Exit, a
Williams %R band — computed as a regular column (via Formula Builder or this
strategy's own columns) and simply referenced here; since it's recomputed fresh
every tick from live data, it trails automatically without needing to know the
signal's history.

---

## 🧪 Worked Example

A `BUY` strategy on `PAYTM`, mirroring the original requirements sheet:

**Config:**
| Field | Value |
|---|---|
| Direction | `BUY` |
| Trigger Condition | `( [Current] > [Open] ) AND ( [Current] > [Close] ) AND ( [Current] > [PMH] )` |
| Debounce | 2 minutes |
| Score | 150 |
| Risk:Reward | Numerator: `[Current] - 1360` (Current minus the same fixed Stop Loss price used below) · Denominator: `1380 - [Current]` (Target 1's price minus Current) — both evaluated once, at entry |
| Metrics | Stop Loss = `1360` (fixed) · Target 1 = `1380` (fixed) · Target 2 = `1413` (fixed) · Target 3 = `1435` (fixed) · Trailing Exit = `[Current] - ( [ATR] * 2 )` (a live ATR-based stop, assuming this strategy already has an `ATR` column) |

Note the Numerator/Denominator/metric formulas repeat the literal `1360`/`1380`
independently rather than referencing each other — see the limitation above; if
you later change Stop Loss's value, update the Risk:Reward formula to match by
hand.

**Timeline:**

| Time | Price | What happens |
|---|---|---|
| 09:29 | 1366 | Condition becomes true (ATR ≈ 7 at this point) — debounce timer starts, no alert yet |
| 09:31 | 1367 | Condition has held 2 min → **entry fires**. Trailing Exit = `1367 - (7*2)` = 1353; Stop Loss/Targets frozen at 1360/1380/1413/1435 |
| 09:35 | 1381 | Price crosses Target 1 (1380) → **Target alert #1** |
| 09:35+ | 1381 | Trailing Exit keeps recomputing from live ATR/price every tick — e.g. now `1381 - (7*2)` = 1367, moving up with price. No alert (only fires when crossed *against* you) |
| 10:09 | 1414 | Price crosses Target 2 (1413) → **Target alert #2** |
| 11:35 | 1436 | Price crosses Target 3 (1435), the last remaining target → **Target alert #3**, and since every target is now achieved, the **signal resolves** |
| — | — | Moves to Live Alerts as **Targets Achieved**, with High/Low since signal and % move recorded |

**Exact notification text sent at each step** (Title / Message, as delivered to
System tray and Email):

```
[Entry, 03-Aug-2026 09:31 AM]
Title:   PWHBUY — BUY Signal: PAYTM
Message: Sector: FINANCE
         Entry Price: 1367.00 @ 3-Aug-2026 09:31 AM
         Stop Loss: 1360.00
         Target 1: 1380.00
         Target 2: 1413.00
         Target 3: 1435.00
         Trailing Exit: 1353.00
         Risk:Reward = 7.00:13.00 (0.54)
         Strength/Weakness Score: 150

[Target 1, 09:35 AM]
Title:   PWHBUY — PAYTM: Target Achieved
Message: Target "Target 1" achieved at 1381.00 (3-Aug-2026 09:35 AM, 4 minutes from signal)

[Target 2, 10:09 AM]
Title:   PWHBUY — PAYTM: Target Achieved
Message: Target "Target 2" achieved at 1414.00 (3-Aug-2026 10:09 AM, 38 minutes from signal)

[Target 3, 11:35 AM — final alert, signal resolves]
Title:   PWHBUY — PAYTM: Target Achieved
Message: Target "Target 3" achieved at 1436.00 (3-Aug-2026 11:35 AM, 124 minutes from signal)
```

*(`_fmt_time` always renders a full `D-Mon-YYYY hh:mm AM/PM` timestamp — the
table above shortens these to bare times for readability, but the real
notification text always includes the date.)*

**Alternative ending** — if price had instead pulled back through the (by-then
higher) Trailing Exit value sometime after 09:35 but before hitting Target 2,
you'd instead get one final alert there and the signal would resolve as
**Stopped Out**, not Targets Achieved — Target 1's alert from 09:35 still stands
(it already fired), but Target 2/3 never get a chance to:

```
Title:   PWHBUY — PAYTM: Stopped Out
Message: Stopped out via "Trailing Exit" at 1366.00 (3-Aug-2026 10:47 AM)
         High/Low since signal: 1381.00/1360.00
         % move from entry: 1.02%
```

---

## 📣 Delivery Channels

Entry/Target/Stop-out alerts are sent through whichever channels are enabled on
the **Notifications** screen (sidebar):

| Channel | Status |
|---|---|
| System | Live — OS tray notification + alert sound |
| Email | Live — sent to your registered account email via the backend |
| Telegram | **Visible but not implemented yet** — enabling it is a harmless no-op; alerts simply won't be delivered there until the Telegram bot backend exists |

These toggles are global and specific to strategy alerts — they don't affect the
separate background-job notifications (historic save, LMV check, etc.), which
keep their own existing behavior.

### Multiple signals on one tick

If more than one stock triggers an alert on the same Live Master View tick —
a market-wide move crossing several strategies' entry conditions at once, say
— you get **one combined notification per channel**, not one per stock. Each
channel gets the level of detail that fits it:

- **System tray**: one toast, one sound, with a compact summary grouped by
  what happened — e.g. `Entries: INFY @1520.50, TCS @3800.00` /
  `Targets: WIPRO @410.00` / `Stop-Outs: RELIANCE @2400.00`. Past 6 stocks in
  one group it switches to `..., +N more` rather than let the OS silently
  truncate a longer line.
- **Email**: one email with every triggered stock's **full** detail —
  sector, entry price, every metric, risk:reward — stacked one after another
  under its own heading, exactly as detailed as the single-stock email
  always was.

The title summarizes the whole batch, e.g. `4 Signals — 2 New Entries, 1
Target Achieved, 1 Stopped Out`, and the notification's severity follows the
most attention-worthy thing in it: a **Stopped Out** anywhere in the batch
always wins (shown as a warning), otherwise a **Target Achieved** does,
otherwise it's an ordinary entry notification.

A single triggered stock is unaffected — it's delivered exactly as before,
with no "1 Signal —" framing.

---

## 🗂 Live Alerts Screen

A read-only log (sidebar → **Live Alerts**) of every pending/open signal and
resolved alert. **Double-click any row** to open a full, structured detail
popup for that signal — every field (Date/Time, Sector, Entry Price, High/Low,
% Move, Score, Risk:Reward if configured) plus every metric with its role and
achievement status, scrollable if it's long. A single click just selects the
row; it takes a double-click to avoid opening a popup on every accidental
click while scanning the table.

- **Recency filter**: Last 5/10/15/30 minutes, Last 1/2/3 hours, Since Market
  Open, or All.
- **Status column**: `Pending`, `Open`, `Targets Achieved`, or `Stopped Out` —
  color-coded (orange/blue/green/red) so outcomes are scannable at a glance.
- **Details column**: every metric's name, current/frozen value, and (for
  targets) whether it's been achieved yet. Only this column stretches to fill
  extra space; every other column has a fixed, content-sized width and the
  table scrolls horizontally rather than squeezing everything to fit — hover
  any cell for its full text if it's still truncated.
- **High** and **Low**: the running extremes reached since entry (separate
  columns, not a combined string).
- **% Move**: the percentage move from entry to the relevant extreme (High for
  a BUY, Low for a SELL).
- **Clear History**: wipes all open signals and resolved history (asks for
  confirmation first — this cannot be undone).
- **Refresh**: manually re-reads the underlying data; the screen also refreshes
  automatically whenever you navigate to it.

---

## 📌 Where the Data Lives

- **Notification config** (everything you set up in Strategy Builder) is synced
  through the same generic per-user settings mechanism as other app
  preferences — it survives reinstalls and syncs across devices logged into the
  same account.
- **Open signals and alert history** are stored **locally only**, per logged-in
  user on this machine — not synced to the backend or across devices. History is
  capped at 500 entries (oldest dropped first).
- Deleting a strategy removes its notification config and any open signals being
  tracked under it; already-resolved history for that strategy is left alone (it's
  a record of what already happened, not a live subscription).

---

## 🛠 Troubleshooting

Nothing firing? Check, in order:
1. Is the **strategy** itself toggled **Active** in the strategy list? (Separate
   from the Notifications section's own **Enabled** toggle — both must be on.)
2. Is **Live Master View** open, loaded, and running (the watcher started)?
   Notifications only evaluate as part of its render loop.
3. Has the trigger condition actually held **continuously** for the full
   debounce window? Check **Live Alerts** — a `Pending` row confirms the
   condition is true and the timer is running.
4. Is at least one delivery channel enabled on the **Notifications** screen?
5. For a Target/Stop Loss/Trailing Exit that never fires: confirm its formula
   actually produces a number for this stock (an empty/None value is silently
   never crossed) — the same combined column picker used for the formula shows
   what's available.

---

← [Back to README](../README)
