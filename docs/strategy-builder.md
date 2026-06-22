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

Formulas are built visually using chips:

```
[ LTP ] [ - ] [ Prev Close ] [ / ] [ Prev Close ] [ * ] [ 100 ]
```

### Building a formula
- **Click a column name pill** → adds a column reference token `[LTP]`
- **Type a number** in the number box → click **Add** to insert it
- **Click an operator button** → `+  −  ×  ÷  (  )`
- **Click a function button** → inserts `MIN(`, `ABS(` etc.
- **Click a chip** to remove it

---

## Per-Row Functions

These operate on values within a single row.

| Function | Description | Example |
|----------|-------------|---------|
| `ABS` | Absolute value | `ABS( [Change] )` |
| `ROUND` | Round to nearest integer | `ROUND( [LTP] )` |
| `FLOOR` | Round down | `FLOOR( [LTP] )` |
| `CEIL` | Round up | `CEIL( [LTP] )` |
| `MIN` | Minimum of values | `MIN( [Bid] , [Ask] )` |
| `MAX` | Maximum of values | `MAX( [High] , [Low] )` |
| `SUM` | Sum of values | `SUM( [Qty] , [Lots] )` |
| `IF` | Conditional value | `IF( [LTP] > 100 , 1 , 0 )` |

---

## Aggregate Functions

These operate **across all rows** in the table and return a single value used in every row's calculation.

| Function | Description |
|----------|-------------|
| `SUM_ALL(col)` | Sum of all values in a column |
| `MIN_ALL(col)` | Minimum value across all rows |
| `MAX_ALL(col)` | Maximum value across all rows |
| `AVG_ALL(col)` | Average value across all rows |
| `COUNT_ALL(col)` | Count of non-empty rows in a column |

**Example:** % contribution to total volume
```
[Volume] / SUM_ALL(Volume) * 100
```

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

← [Back to README](../README)
