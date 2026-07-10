#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

source .venv/bin/activate

python -m pip install --upgrade pip >/dev/null
pip install -r requirements.txt

echo "Starting Broker File Sync..."
python main.py
