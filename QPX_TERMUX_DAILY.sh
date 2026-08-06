#!/data/data/com.termux/files/usr/bin/sh

set -u

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PREFIX_PATH="${PREFIX:-/data/data/com.termux/files/usr}"
PYTHON_BIN="${PREFIX_PATH}/bin/python"
LOG_DIR="${ROOT}/logs"
LOG_FILE="${LOG_DIR}/qpx_daily_operations.log"

mkdir -p "${LOG_DIR}"

wake_locked=0

if command -v termux-wake-lock >/dev/null 2>&1; then
    termux-wake-lock >/dev/null 2>&1 || true
    wake_locked=1
fi

cd "${ROOT}" || exit 1
"${PYTHON_BIN}" QPX_RUN_DAILY_OPERATIONS.py >>"${LOG_FILE}" 2>&1
status=$?

if [ "${status}" -eq 0 ]; then
    "${PYTHON_BIN}" QPX_BACKUP_RUNTIME.py \
        --create \
        --drill-latest >>"${LOG_FILE}" 2>&1
    backup_status=$?

    if [ "${backup_status}" -ne 0 ]; then
        status="${backup_status}"
    fi
fi

if [ "${wake_locked}" -eq 1 ] \
    && command -v termux-wake-unlock >/dev/null 2>&1; then
    termux-wake-unlock >/dev/null 2>&1 || true
fi

exit "${status}"
