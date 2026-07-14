#!/usr/bin/env bash
# Bootstrap the Michigan Pesticide Heat Map: deps, data, then start server.
set -euo pipefail

cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || PY="python"
command -v "$PY" >/dev/null 2>&1 || PY="py"

echo "[setup] Using interpreter: $($PY --version 2>&1)"

if [[ ! -d ".venv" ]]; then
  echo "[setup] Creating virtual environment .venv ..."
  "$PY" -m venv .venv
fi

if [[ -f ".venv/Scripts/python.exe" ]]; then
  VENV_PY=".venv/Scripts/python.exe"
else
  VENV_PY=".venv/bin/python"
fi

echo "[setup] Installing Python dependencies ..."
"$VENV_PY" -m pip install --quiet --upgrade pip
"$VENV_PY" -m pip install --quiet -r requirements.txt

echo "[setup] Downloading and ingesting real datasets (USGS, Census, optional NASS) ..."
"$VENV_PY" -m app.data_loader

echo "[setup] Generating app icon ..."
"$VENV_PY" scripts/make_icon.py

# Desktop shortcut creator is Windows-only; skip on other platforms.
if [[ "$OSTYPE" == "msys"* || "$OSTYPE" == "cygwin"* || "$OSTYPE" == "win32" ]]; then
  echo "[setup] Creating desktop shortcut ..."
  "$VENV_PY" create_shortcut.py
fi

echo "[setup] Starting server on http://127.0.0.1:8080 ..."
"$VENV_PY" app.py
