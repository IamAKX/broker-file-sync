# 📦 Building Executables

Broker File Sync uses **PyInstaller** to produce standalone executables. Builds are automated via GitHub Actions and attached as release artifacts.

---

## Download & Run (No Python Required)

If you just want to run the app without installing Python or building anything yourself:

### Windows

1. Go to the [Releases page](https://github.com/IamAKX/broker-file-sync/releases)
2. Download `BrokerFileSync-windows.zip` from the latest release
3. Unzip it — you'll get a `BrokerFileSync/` folder
4. Open the folder and double-click **`BrokerFileSync.exe`**

> ⚠️ Windows may show a SmartScreen warning ("Windows protected your PC") because the exe is unsigned. Click **More info → Run anyway** to proceed.

> 💡 Keep the entire `BrokerFileSync/` folder intact — the `.exe` depends on files alongside it. Do not move the `.exe` out of the folder.

### macOS

1. Go to the [Releases page](https://github.com/IamAKX/broker-file-sync/releases)
2. Download `BrokerFileSync-mac.zip` from the latest release
3. Unzip it — you'll get `BrokerFileSync.app`
4. Drag it to your **Applications** folder (optional but recommended)
5. Double-click to launch

> ⚠️ On first launch macOS will block the app. Go to **System Settings → Privacy & Security** and click **Open Anyway**.

---

## Automated Builds (CI)

Every push to `main` triggers the CI pipeline which:
1. Runs all tests
2. Builds a macOS `.app` bundle
3. Builds a Windows `.exe` (with `pywin32` bundled for live TradeTiger data)
4. Creates a GitHub Release with both as downloadable `.zip` files

→ Download the latest build from the [Releases page](https://github.com/IamAKX/broker-file-sync/releases)

---

## Manual Build — macOS

```bash
pip install pyinstaller

pyinstaller --windowed --onedir --name "BrokerFileSync" \
  --add-data "assets:assets" \
  --add-data "screens:screens" \
  --add-data "services:services" \
  --add-data "components:components" \
  --add-data "font_scale.py:." \
  --collect-data openpyxl \
  main.py
```

Output: `dist/BrokerFileSync.app`

---

## Manual Build — Windows

```cmd
pip install pyinstaller pywin32
python -m pywin32_postinstall -install

pyinstaller --windowed --onedir --name "BrokerFileSync" ^
  --add-data "assets;assets" ^
  --add-data "screens;screens" ^
  --add-data "services;services" ^
  --add-data "components;components" ^
  --add-data "font_scale.py;." ^
  --collect-data openpyxl ^
  --collect-all pywin32 ^
  --hidden-import win32com.client ^
  --hidden-import win32com ^
  --hidden-import pythoncom ^
  --hidden-import pywintypes ^
  --manifest "windows_dpi.manifest" ^
  main.py
```

Output: `dist/BrokerFileSync/BrokerFileSync.exe`

> The `--manifest` flag embeds `windows_dpi.manifest` into the `.exe`, declaring `PerMonitorV2` DPI awareness so the UI renders sharply on high-DPI Windows displays.

---

## What Gets Bundled

| Source | Destination in build |
|--------|---------------------|
| `assets/` | `assets/` |
| `screens/` | `screens/` |
| `services/` | `services/` |
| `components/` | `components/` |
| `font_scale.py` | root |
| `openpyxl` data | bundled automatically |

> `strategies.json` is **not** bundled — it is created at runtime in the same directory as the executable.

---

## Troubleshooting

**"ModuleNotFoundError" on launch**
- Make sure `--add-data` paths use `:` (macOS) or `;` (Windows) as the separator

**Blurry UI on Windows**
- Ensure `windows_dpi.manifest` is present and `--manifest` is passed to PyInstaller
- Or right-click `.exe` → Properties → Compatibility → Override high DPI → Application

**App crashes on macOS after update**
- Delete the old `.app` and replace with the fresh build — cached resources can cause conflicts

---

← [Back to README](../README)
