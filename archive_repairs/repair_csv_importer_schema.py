#!/usr/bin/env python3

from pathlib import Path
import shutil
import re
import sys

TARGET = Path(
    "/storage/emulated/0/QPX_ALPHA/quant_platform/mobile/csv_importer.py"
)

BACKUP = TARGET.with_suffix(TARGET.suffix + ".backup")


def main():
    print("[INSPECT] Target importer:")
    print(TARGET)

    if not TARGET.exists():
        print("[FAIL] csv_importer.py not found")
        sys.exit(1)

    if not BACKUP.exists():
        shutil.copy2(TARGET, BACKUP)
        print("[BACKUP] Creating backup:")
        print(f"[OK] {BACKUP}")
    else:
        print("[OK] Backup already exists:")
        print(f"[OK] {BACKUP}")

    source = TARGET.read_text(encoding="utf-8")

    original = source

    # Match common INSERT layouts:
    # INSERT INTO market_data (...)
    # INSERT INTO market_data
    # (
    #     symbol,
    #     date,
    #     open,
    #     ...
    # )
    pattern = re.compile(
        r"(INSERT\s+INTO\s+market_data\s*\(\s*"
        r"symbol\s*,\s*"
        r")date(\s*,\s*open\s*,\s*high\s*,\s*low\s*,\s*close\s*,\s*volume\s*\))",
        re.IGNORECASE | re.DOTALL
    )

    patched, count = pattern.subn(
        r"\1timestamp\2",
        source
    )

    if count == 0:
        print("[FAIL] INSERT column mapping not found")
        print("[INFO] No changes applied")
        sys.exit(2)

    TARGET.write_text(patched, encoding="utf-8")

    print("[PATCH] Applied importer timestamp mapping")
    print("[OK] Changed:")
    print("      date -> timestamp")

    # Verify
    verify = TARGET.read_text(encoding="utf-8")

    if "INSERT" in verify and "timestamp" in verify:
        print("[VERIFY] INSERT mapping updated")
    else:
        print("[FAIL] Verification failed")
        shutil.copy2(BACKUP, TARGET)
        print("[RESTORE] Original file restored")
        sys.exit(3)

    print("[DONE] Repair completed")


if __name__ == "__main__":
    main()
