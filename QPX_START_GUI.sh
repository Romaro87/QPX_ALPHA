#!/data/data/com.termux/files/usr/bin/bash
set -e
cd "$(dirname "$0")"
PORT="${QPX_GUI_PORT:-8765}"
echo "QPX GUI: http://127.0.0.1:${PORT}"
if command -v termux-open-url >/dev/null 2>&1; then (sleep 1; termux-open-url "http://127.0.0.1:${PORT}" >/dev/null 2>&1 || true) & fi
exec python QPX_GUI.py --port "$PORT"
