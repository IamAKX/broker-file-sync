# 🚀 Setup & Installation

## Just Want to Run the App?

Download a pre-built executable from the [Releases page](https://github.com/IamAKX/broker-file-sync/releases) — no Python installation required.

→ See [Building Executables](building.md) for download and first-run instructions.

---

## Prerequisites (Source / Developer Setup)

| Requirement | Version |
|-------------|---------|
| Python | 3.11 or higher |
| pip | latest |
| OS | macOS 12+ or Windows 10/11 |

---

## 🍎 macOS Setup

### 1. Clone the Repository

```bash
git clone https://github.com/IamAKX/broker-file-sync.git
cd broker-file-sync
```

### 2. Create a Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the App

```bash
python main.py
```

---

## 🪟 Windows Setup

### 1. Clone the Repository

```cmd
git clone https://github.com/IamAKX/broker-file-sync.git
cd broker-file-sync
```

### 2. Create a Virtual Environment

```cmd
python -m venv .venv
.venv\Scripts\activate
```

### 3. Install Core Dependencies

```cmd
pip install -r requirements.txt
```

### 4. Install pywin32 (Required for Live TradeTiger Data)

TradeTiger pushes live prices into Excel via **DDE** — the file on disk never updates continuously. `pywin32` lets the app read directly from the open Excel instance via COM automation.

```cmd
pip install pywin32
python -m pywin32_postinstall -install
```

> ⚠️ The `pywin32_postinstall` step is **mandatory** — without it, the COM runtime won't initialise correctly and live data won't work.

### 5. Run the App

```cmd
python main.py
```

---

## 🔴 Setting Up TradeTiger Live Data (Windows)

For the Live Master View to update in real time, TradeTiger must push data to Excel first:

1. Open **TradeTiger**
2. Open your **Market Watch**
3. Right-click → **Snap to Excel**
4. Excel opens with a `Snap.xls` workbook — prices will start updating live
5. **Keep this Excel window open** — do not save or close it
6. Now open **Broker File Sync** → **Data Import** → drop your broker files → click **Run Watcher**
7. The Live Master View will poll the open `Snap.xls` every **1 second** and reflect live prices

> 💡 The `Snap.xls` workbook must remain open in Excel while the Live Master View is running. If you close it, the status will show **"Waiting for Snap.xls in Excel…"** until you reopen it.

---

## 📦 Dependencies

| Package | Purpose | Platform |
|---------|---------|----------|
| `PySide6 >= 6.6` | Qt6 GUI framework | All |
| `openpyxl` | Read/write `.xlsx` files | All |
| `xlrd` | Read legacy `.xls` files | All |
| `pywin32` | COM automation for live TradeTiger data | Windows only |

---

## 🍎 macOS Notes

On first launch macOS may show a security warning. Go to **System Settings → Privacy & Security** and click **Open Anyway**.

On macOS, the Live Master View uses `QFileSystemWatcher` to detect file changes — this works for manually saved files but **not** for TradeTiger's live DDE updates (which are Windows-only).

---

## 🪟 Windows Notes

- The app is DPI-aware on Windows. If text appears blurry, right-click the `.exe` → Properties → Compatibility → Override high DPI scaling → set to **Application**
- `pywin32` must be installed for Live Master View to work with TradeTiger
- Run the app from the same virtual environment where `pywin32` was installed

---

← [Back to README](../README)
