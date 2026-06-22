# 🚀 Setup & Installation

## Prerequisites

| Requirement | Version |
|-------------|---------|
| Python | 3.11 or higher |
| pip | latest |
| OS | macOS 12+ or Windows 10/11 |

---

## 1️⃣ Clone the Repository

```bash
git clone https://github.com/IamAKX/broker-file-sync.git
cd broker-file-sync
```

---

## 2️⃣ Create a Virtual Environment

**macOS / Linux**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows**
```cmd
python -m venv .venv
.venv\Scripts\activate
```

---

## 3️⃣ Install Dependencies

```bash
pip install -r requirements.txt
```

### Dependencies

| Package | Purpose |
|---------|---------|
| `PySide6 >= 6.6` | Qt6 GUI framework |
| `openpyxl` | Read/write `.xlsx` files |
| `xlrd` | Read legacy `.xls` files |

---

## 4️⃣ Run the App

```bash
python main.py
```

The app opens on the **Login** screen. Click **Login** to enter (no credentials required in the prototype).

---

## 🗂️ First-Time Setup

1. Go to **Data Import**
2. Drop your broker Excel files onto each broker card
3. Click **Run Watcher** — the Live Master View opens
4. Go to **Strategy Builder** to create formula columns
5. Go to **My Profile** → Preferences to set your output directory

---

## 🪟 Windows Notes

The app is DPI-aware on Windows. If text appears blurry, right-click the `.exe` → Properties → Compatibility → Override high DPI scaling → set to **Application**.

---

## 🍎 macOS Notes

On first launch macOS may show a security warning. Go to **System Settings → Privacy & Security** and click **Open Anyway**.

---

← [Back to README](../README)
