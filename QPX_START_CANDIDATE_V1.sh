#!/data/data/com.termux/files/usr/bin/bash

set -u

cd "$(dirname "$0")" || exit 1

LOG_DIR="logs/qpx_candidate_v1"
mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/forward_paper.log"

echo "============================================================"
echo "QPX CANDIDATE V1 — CONTINUOUS PAPER MODE"
echo "============================================================"
echo "Symbols: loaded from qpx_bot/candidate_v1_policy.json"
echo "87.5% swing / 12.5% income sleeve"
echo "3% risk / 10% active-risk ceiling"
echo "Kelly disabled"
echo "VIX 20-25 excluded"
echo "LIVE BROKER DISABLED"
echo
echo "Log: $LOG_FILE"
echo
echo "Press CTRL+C to stop."
echo "============================================================"

if command -v termux-wake-lock >/dev/null 2>&1; then
    termux-wake-lock >/dev/null 2>&1 || true
fi

cleanup() {
    echo
    echo "QPX Candidate V1 stopped."

    if command -v termux-wake-unlock >/dev/null 2>&1; then
        termux-wake-unlock >/dev/null 2>&1 || true
    fi

    exit 0
}

trap cleanup INT TERM

while true
do
    echo >> "$LOG_FILE"
    echo "============================================================" >> "$LOG_FILE"
    date >> "$LOG_FILE"
    echo "============================================================" >> "$LOG_FILE"

    python QPX_CANDIDATE_V1_PAPER.py \
        2>&1 | tee -a "$LOG_FILE"

    EXIT_CODE=${PIPESTATUS[0]}

    if [ "$EXIT_CODE" -ne 0 ]; then
        echo "QPX cycle error: exit code $EXIT_CODE" \
            | tee -a "$LOG_FILE"
    fi

    sleep 60
done
