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
| `divider` | `#2a2f36` | `#e5e7eb` | Thin separator lines (`_sep()`), lighter-weight than `border` |
| `accent` | `#39d353` | `#1a7f37` | Buttons, active nav, highlights |
| `accent_hover` | `#2ea043` | `#116329` | Hover state for accent buttons |
| `text_primary` | `#e6edf3` | `#1f2328` | Main text |
| `text_secondary` | `#8b949e` | `#656d76` | Labels, hints, secondary text |
| `input_bg` | `#0d1117` | `#ffffff` | Input field backgrounds |
| `button_bg` | `#21262d` | `#eaecef` | Default button backgrounds |
| `destructive` | `#da3633` | `#cf222e` | Delete / danger buttons |
| `status_red` | `#f85149` | `#cf222e` | Error indicators |
| `status_blue` | `#58a6ff` | `#0969da` | Info, links |
| `status_orange` | `#e3b341` | `#9a6700` | Warnings |
| `status_amber` | `#d29922` | `#bf8700` | A second warning/gold tone, distinct from `status_orange` |
| `status_purple` | `#a371f7` | `#8250df` | Qualitative accent (e.g. a strategy category color) |
| `status_pink` | `#f778ba` | `#bf3989` | Qualitative accent (e.g. a strategy category color) |
| `info_banner_bg` | `#2d1f00` | `#fffbeb` | Background of an informational banner |
| `info_banner_border` | `#d97706` | `#d97706` | Border of an informational banner (same in both modes) |
| `info_banner_text` | `#fcd34d` | `#78350f` | Text inside an informational banner |
| `watcher_banner_bg` | `#0d2116` | `#f0fdf4` | Background of the "watcher active" banner |
| `watcher_banner_border` | `#39d353` | `#1a7f37` | Border of the "watcher active" banner |

---

## How Theme Propagation Works

1. `ThemeManager.apply()` sets a global Qt stylesheet **and** an explicit
   `QPalette` (`_build_palette`) on `QApplication`. The palette exists because
   Fusion-style popups that spawn their own top-level window — a `QComboBox`
   dropdown, a `QMenu`, a tooltip — paint their frame from the ambient palette
   *before* any QSS on the inner view applies; without it, popups fall back to
   native white regardless of dark/light mode. This covers most widgets
   automatically.
2. A module-level patch on `QComboBox.showPopup` (`_patch_combo_popup_frame`,
   applied once at import time) strips the popup list's own native frame, so
   only the one QSS-declared border shows instead of a doubled-looking edge.
3. Screens that have theme-specific colors call `refresh_theme()` — triggered by `app_window._on_theme_toggled()`
4. Dialogs (popups, column editors) read the theme at creation time via `_apply_dialog_bg(dialog, theme)`
5. Inline styles use `theme.get("token")` at render time, not at build time, so they always reflect the current mode

---

## Adding a New Theme Token

1. Add the key/value to both `DARK` and `LIGHT` dicts in `theme.py`
2. Use it anywhere via `theme.get("my_token")` or `_t(theme, "my_token")`

---

← [Back to README](../README)
