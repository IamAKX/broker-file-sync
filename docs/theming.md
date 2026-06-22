# 🎨 Theming & Fonts

---

## Theme Toggle

Click the 🌙 / ☀️ button in the top-right corner to switch between **dark** and **light** mode. The change propagates instantly to all open screens, dialogs, and the Live Master View window.

---

## Font Scale

All font sizes are defined in **`font_scale.py`**. To resize text across the entire app, change these three values:

```python
# font_scale.py
SMALL  = 14   # labels, secondary text, table headers, sidebar
MEDIUM = 16   # body text, input fields, buttons
LARGE  = 18   # primary action buttons
```

Display/title sizes scale proportionally:

```python
DISPLAY_SM = 22   # section headings (e.g. "Columns", "Strategy Name")
DISPLAY_MD = 28   # screen titles (e.g. "Data Import", "Config Editor")
DISPLAY_LG = 36   # login / signup card title
```

> **Tip:** Increase all values by 2 to make the whole app feel more comfortable on a large monitor.

---

## Theme Tokens

Defined in `theme.py` as two palettes — `DARK` and `LIGHT`.

| Token | Dark | Light | Usage |
|-------|------|-------|-------|
| `background` | `#0d1117` | `#ffffff` | Main window background |
| `sidebar_bg` | `#161b22` | `#f6f8fa` | Sidebar, menu bar |
| `card_bg` | `#1c2128` | `#f6f8fa` | Cards, panels, tab content |
| `border` | `#30363d` | `#d0d7de` | All borders |
| `accent` | `#39d353` | `#1a7f37` | Buttons, active nav, highlights |
| `text_primary` | `#e6edf3` | `#1f2328` | Main text |
| `text_secondary` | `#8b949e` | `#656d76` | Labels, hints, secondary text |
| `input_bg` | `#0d1117` | `#ffffff` | Input field backgrounds |
| `button_bg` | `#21262d` | `#eaecef` | Default button backgrounds |
| `destructive` | `#da3633` | `#cf222e` | Delete / danger buttons |
| `status_red` | `#f85149` | `#cf222e` | Error indicators |
| `status_blue` | `#58a6ff` | `#0969da` | Info, links |
| `status_orange` | `#e3b341` | `#9a6700` | Warnings |

---

## How Theme Propagation Works

1. `ThemeManager.apply()` sets a global Qt stylesheet on `QApplication` — this covers most widgets automatically
2. Screens that have theme-specific colors call `refresh_theme()` — triggered by `app_window._on_theme_toggled()`
3. Dialogs (popups, column editors) read the theme at creation time via `_apply_dialog_bg(dialog, theme)`
4. Inline styles use `theme.get("token")` at render time, not at build time, so they always reflect the current mode

---

## Adding a New Theme Token

1. Add the key/value to both `DARK` and `LIGHT` dicts in `theme.py`
2. Use it anywhere via `theme.get("my_token")` or `_t(theme, "my_token")`

---

← [Back to README](../README)
