# 📐 Formula Builder Reference

The **Expression Editor** is the one formula-building UI used everywhere in the
app — a strategy column's value, a Row Filter, a conditional-formatting rule's
condition, a Notification's trigger condition, a Risk:Reward numerator/
denominator, and a Metric's formula are all the *exact same editor*, just
opened in a different mode. Learn it once, use it everywhere.

This page is the full reference: every function, every catalogue section,
every syntax form, with examples. For the higher-level tour of Strategy
Builder itself (Columns, Row Filter, Conditional Formatting, Historic (N days)
Aggregates as a feature), see [🧮 Strategy Builder](strategy-builder.md).

---

## Contents

- [Where you'll find it](#where-youll-find-it)
- [How a formula is built](#how-a-formula-is-built)
- [Fields — `[Column]`](#fields--column)
- [THIS — a column's own value](#this--a-columns-own-value)
- [Constants](#constants)
- [Operators](#operators)
- [Functions](#functions)
  - [Math](#math)
  - [Trigonometry](#trigonometry)
  - [Conditional / Logic](#conditional--logic)
  - [String](#string)
  - [Type Conversion](#type-conversion)
  - [Aggregate — across all rows, this tick](#aggregate--across-all-rows-this-tick)
  - [Historic — over the last N days](#historic--over-the-last-n-days)
- [Variables — `{Name}`](#variables--name)
- [Worked examples](#worked-examples)
- [Common errors & gotchas](#common-errors--gotchas)

---

## Where you'll find it

| Entry point | Mode | `THIS` available? |
|---|---|---|
| Strategy Builder → Columns → **Edit Formula…** | value | No |
| Strategy Builder → Column → Conditional Formatting → **Edit Condition…** | condition | **Yes** — the column's own computed value |
| Strategy Builder → **Edit Filter…** (Row Filter) | condition | No — a filter isn't owned by one column |
| Strategy Builder → Notifications → **Edit Condition…** (Trigger Condition) | condition | No |
| Strategy Builder → Notifications → Risk:Reward → **Edit Formula…** | value | No |
| Strategy Builder → Notifications → Metrics → **Edit Formula…** | value | No |
| Strategy Builder → **Variables** → a variable's own formula | value | No |

A formula built in **value** mode produces a number/string; one in
**condition** mode must produce something truthy/falsy (used with comparison
operators like `>`, `==`, or wrapping the whole thing in `IIf`).

---

## How a formula is built

The editor is a plain text box — type directly, or click anything in the
catalogue (left: Functions / Operators / Fields / Rows / Constants /
Variables) to insert it at the cursor. The quick operator toolbar and
**THIS** button (when available) do the same.

1. **Type or click to build the expression.**
2. **Compile & Test** — validates the formula against your actually-loaded
   sheet's first row (never dummy data) and shows what it evaluates to. A
   structural problem (unmatched bracket, unknown column, a formula that
   errors) is reported in plain language *and* highlighted directly in the
   text — no guessing which part is wrong.
3. **Save** — enabled only once Compile & Test has succeeded.
4. **Save as Variable…** — saves the whole compiled formula as a reusable
   `{Name}` (see [Variables](#variables--name) below), also gated on a
   successful compile.

---

## Fields — `[Column]`

Any column from the loaded sheet, or one of this strategy's own columns, by
name in square brackets:

```
[LTP]
[High] - [Low]
[Sector]
```

An empty/missing cell reads as `None` in a formula — see
[Common errors & gotchas](#common-errors--gotchas).

### Referencing another stock's row — `[Column of Symbol]`

```
[LTP] / [LTP of Nifty]        — this stock's price as a ratio of Nifty's
[Open of Nifty]                — Nifty's own Open, regardless of the current row
```

In the UI: click a Field (e.g. `[Open]`), then click a stock name under the
**Rows** catalogue tab to turn it into `[Open of Nifty]`. Typed directly, just
write `[Column of Symbol]` — the space before/after `of` matters, the column
name doesn't need to.

---

## THIS — a column's own value

Available only where a formula is unambiguously "owned" by one column — a
conditional-formatting rule's condition. Refers to that column's own computed
value, so a rule can reference the value it's about to color without
recomputing it:

```
THIS > 100     — this column's own value is greater than 100
```

Not available in a Row Filter, Trigger Condition, or Metric formula — none of
those are owned by a single column, so there'd be no one value for `THIS` to
mean.

---

## Constants

| Constant | Meaning |
|---|---|
| `True` / `False` | Boolean literals |
| `None` | Null / missing value |
| a bare number | `1.5`, `-20`, `0.998` |
| a quoted string | `"INFY"`, `'Long text'` |

---

## Operators

| Operator | Meaning | Operator | Meaning |
|---|---|---|---|
| `+` `-` `*` `/` | Arithmetic | `<` `<=` `>` `>=` | Comparison |
| `%` | Modulo (remainder) | `==` `!=` | Equal / not equal |
| `**` | Exponentiation | `And` `Or` `Not` | Logical |
| `(` `)` | Grouping | `,` | Argument separator |

`And`/`Or`/`Not` are typed as words, not symbols (`[LTP] > [Open] And [Volume] > 100000`).

---

## Functions

### Math

| Function | Example | Result |
|---|---|---|
| `Abs(value)` | `Abs(-7)` | `7` |
| `Ceiling(value)` | `Ceiling(2.1)` | `3` |
| `Floor(value)` | `Floor(2.9)` | `2` |
| `Round(value)` | `Round(2.5)` | `2` — see the banker's-rounding note below |
| `Round(value, digits)` | `Round(3.14159, 2)` | `3.14` |
| `Exp(value)` | `Exp(1)` | `2.718281828...` (eˣ) |
| `Log(value)` | `Log(2.718281828)` | `1.0` (natural log) |
| `Log(value, base)` | `Log(8, 2)` | `3.0` |
| `Log10(value)` | `Log10(100)` | `2.0` |
| `Max(a, b)` | `Max([High], [PrevHigh])` | the larger of the two |
| `Min(a, b)` | `Min([Low], [PrevLow])` | the smaller of the two |
| `Power(base, exp)` | `Power(2, 10)` | `1024` |
| `Sign(value)` | `Sign(-3)` | `-1` (else `1`, or `0` for exactly `0`) |
| `Sqr(value)` | `Sqr(9)` | `3.0` — this is **square root**, not "square" (classic-VB-style name) |
| `BigMul(a, b)` | `BigMul(12345, 67890)` | `838102050` |

### Trigonometry

All angles in **radians**.

| Function | Example | Result |
|---|---|---|
| `Sin(value)` / `Cos(value)` / `Tan(value)` | `Sin(0)` | `0.0` |
| `Sinh(value)` / `Cosh(value)` / `Tanh(value)` | `Cosh(0)` | `1.0` |
| `Asin(value)` / `Acos(value)` / `Atn(value)` | `Atn(1)` | `0.7853981...` (π/4) |
| `Atn2(y, x)` | `Atn2(1, 1)` | `0.7853981...` (π/4) |

### Conditional / Logic

| Function | Example | Result |
|---|---|---|
| `IIf(condition, trueVal, falseVal)` | `IIf([LTP] > 100, 1, 0)` | `1` when `LTP > 100`, else `0` |
| `IsNull(value)` | `IsNull([Sector])` | `True` if the cell is empty/missing |
| `IsNullOrEmpty(value)` | `IsNullOrEmpty([Notes])` | `True` if empty, missing, or blank text |
| `InRange(value, low, high)` | `InRange([LTP], 100, 200)` | `True` if `100 <= LTP <= 200` (both ends inclusive) |
| `Digits(value)` | `Digits(12123.77)` | `5` — digit count of the value's integer part |

> ⚠️ **Gotcha — `IIf` evaluates *both* branches, every time.**
> Unlike a short-circuiting `if`, `IIf(cond, a, b)` computes `a` *and* `b`
> before picking one — so an error in the branch you don't expect to use
> still breaks the whole formula. `IIf([X] > 0, 1 / [X], 0)` returns a blank
> result the moment `[X]` is `0`, even though the `1/[X]` branch was never
> "supposed" to run. Guard the risky operand instead:
> `IIf([X] == 0, 0, 1 / [X])`.

`Digits` is built specifically to combine with `IIf` for a price-tiered
threshold — see [Worked examples](#worked-examples).

### String

| Function | Example | Result |
|---|---|---|
| `Concat(a, b)` | `Concat("IN", "FY")` | `"INFY"` |
| `Len(str)` | `Len("Hello")` | `5` |
| `Lower(str)` / `Upper(str)` | `Upper("hi")` | `"HI"` |
| `Trim(str)` | `Trim("  hi  ")` | `"hi"` |
| `Reverse(str)` | `Reverse("abc")` | `"cba"` |
| `Replace(str, old, new)` | `Replace("Hello", "l", "L")` | `"HeLLo"` |
| `Remove(str, search)` | `Remove("Hello", "l")` | `"Heo"` |
| `Contains(str, search)` | `Contains("Hello World", "World")` | `True` |
| `StartsWith(str, prefix)` / `EndsWith(str, suffix)` | `StartsWith("Hello", "He")` | `True` |
| `Substring(str, start, length)` | `Substring("Hello", 1, 3)` | `"ell"` — 0-indexed start, second arg is a *length*, not an end index |
| `CharIndex(str, search)` | `CharIndex("Hello", "l")` | `2` — 0-indexed, `-1` if not found |
| `Insert(str, pos, val)` | `Insert("Hello", 5, "!")` | `"Hello!"` |
| `PadLeft(str, width)` / `PadRight(str, width)` | `PadLeft("7", 3)` | `"  7"` |
| `Char(code)` | `Char(65)` | `"A"` |
| `Ascii(char)` | `Ascii("A")` | `65` |

### Type Conversion

| Function | Example | Result |
|---|---|---|
| `ToInt(value)` / `ToLong(value)` | `ToInt(7.8)` | `7` — **truncates**, does not round |
| `ToFloat(value)` / `ToDouble(value)` / `ToDecimal(value)` | `ToFloat("3.5")` | `3.5` |
| `ToStr(value)` | `ToStr(42)` | `"42"` |

### Aggregate — across all rows, this tick

Aggregate *across every currently-visible row*, recomputed every live tick —
the counterpart to the [Historic](#historic--over-the-last-n-days) functions
below, which aggregate one stock's own history over time instead.

| Function | Example | Result |
|---|---|---|
| `SUM_ALL(column)` | `SUM_ALL(Volume)` | Sum of `Volume` across every row |
| `MIN_ALL(column)` / `MAX_ALL(column)` | `MAX_ALL(High)` | Highest `High` across every row |
| `AVG_ALL(column)` | `AVG_ALL(Volume)` | Average `Volume` across every row |
| `COUNT_ALL(column)` | `COUNT_ALL(Volume)` | Count of rows with a non-empty `Volume` |

```
[Volume] / SUM_ALL(Volume) * 100     — this stock's % share of total volume today
[Volume] > AVG_ALL(Volume) * 2       — a volume spike vs. the rest of the sheet
```

### Historic — over the last N days

Aggregate *one stock's own value, over its last N historic trading days* —
the same concept as the `_ALL` functions above, just across time instead of
across today's rows. This is the one function family that **doesn't**
recompute on every live tick — see
[🧮 Strategy Builder → Historic (N days) Aggregates](strategy-builder.md#historic-n-days-aggregates)
for the full explanation of refresh cadence, and why.

| Function | Example |
|---|---|
| `AVG_DAYS(column, days)` | `AVG_DAYS([High], 20)` — 20-day average High |
| `MIN_DAYS(column, days)` / `MAX_DAYS(column, days)` | `MIN_DAYS([Low], 10)` — 10-day low |
| `SUM_DAYS(column, days)` | `SUM_DAYS([Volume], 5)` |
| `COUNT_DAYS(column, days)` | `COUNT_DAYS([High], 20)` — how many of the last 20 days had usable data |
| `STDDEV_DAYS(column, days)` / `VARIANCE_DAYS(column, days)` | `STDDEV_DAYS([Close], 20)` |
| `MEDIAN_DAYS(column, days)` | `MEDIAN_DAYS([Close], 20)` |
| `RANGE_DAYS(column, days)` | `RANGE_DAYS([High], 20)` — Max minus Min over the window |

```
[Current] > AVG_DAYS([High], 20)               — breakout above its own 20-day average High
AVG_DAYS([MyComputedCol], 20)                  — 20-day average of another of THIS strategy's
                                                   own columns (any custom formula, since a
                                                   column can already be built from one)
```

---

## Variables — `{Name}`

A reusable named formula, inserted anywhere as `{Name}` — it inlines that
variable's own formula wherever it's used, so a formula you'd otherwise
retype in five places (a tiered threshold, say) is built once.

- **Create one**: build the formula in any Expression Editor instance, click
  **Save as Variable…**, name it. Or open **Variables** (Strategy Builder's
  top bar) → **+ New**.
- **Use one**: click it under the **Variables** catalogue tab, or type
  `{Name}` directly.
- **Nesting**: a variable's formula can reference other variables — expanded
  recursively wherever it's used.
- A variable that references itself (directly or through another variable)
  is dropped from the expansion rather than looping forever; a deleted
  variable's `{Name}` references silently drop out of any formula still
  using them — both degrade that one spot rather than crashing everything
  that happens to reference it.

```
{PriceTier} = IIf(Digits([Open]) >= 5, 0.998, IIf(Digits([Open]) >= 4, 0.919, 0.85))

[LTP] > [Open] * {PriceTier}     — reuses the tiered threshold without retyping the nested IIf
```

---

## Worked examples

**% change from previous close**
```
([LTP] - [Prev Close]) / [Prev Close] * 100
```

**Price-tiered threshold** (the `Digits`+`IIf` pattern this app was built around)
```
IIf(Digits([Open]) >= 5, 0.998, IIf(Digits([Open]) >= 4, 0.919, 0.85))
```

**This stock vs. the index**
```
[LTP] / [LTP of Nifty]
```

**Volume spike relative to the rest of today's sheet**
```
[Volume] > AVG_ALL(Volume) * 2
```

**20-day breakout**
```
[Current] > AVG_DAYS([High], 20)
```

**A safe divide-by-zero guard** (see the `IIf` gotcha above)
```
IIf([Denominator] == 0, 0, [Numerator] / [Denominator])
```

---

## Common errors & gotchas

- **`Round` uses banker's rounding.** `Round(2.5)` is `2`, not `3` —
  round-half-to-even, not round-half-up. `Round(3.5)` is `4`. Only matters
  exactly on the `.5` boundary.
- **`Sqr` is square *root*, not "squared".** `Sqr(9)` is `3`, not `81`. For
  squaring, use `Power(value, 2)`.
- **`IIf` evaluates both branches.** See the callout under
  [Conditional / Logic](#conditional--logic) — an error in the branch you
  don't expect to hit still blanks the whole formula.
- **An empty cell is `None`, not `0` or `""`.** `[Sector] == ""` won't match
  a blank Sector cell — use `IsNull([Sector])` or `IsNullOrEmpty([Sector])`
  instead. Arithmetic on a `None` (e.g. `[Sector] + 1` where Sector is
  blank) fails the same way any Python arithmetic on `None` would — the
  formula evaluates to blank rather than crashing anything else.
- **Compile & Test always runs against your real first row**, never dummy
  data — if it says a column is unknown, that's checked against your
  actually-loaded sheet's real column names, not a guess.
- **Historic (`_DAYS`) functions don't update on every live tick.** Compile
  & Test can't run their real historic fetch either — it reports a
  placeholder and says so, rather than blocking Save. See
  [🧮 Strategy Builder → Historic (N days) Aggregates](strategy-builder.md#historic-n-days-aggregates).
- **`Rnd()` appears in the Functions catalogue but isn't implemented yet** —
  using it evaluates to blank rather than a random number. Everything else
  on this page is live.

---

← [Back to README](../README)
