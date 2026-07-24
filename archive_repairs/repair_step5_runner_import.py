#!/usr/bin/env python3

"""
QPX Alpha Step 5 Runtime Import Repair

Purpose:
Repair missing csv_importer runtime reference in mobile_runner.py

Preserves:
- QPX Alpha architecture
- importer logic
- database schema
- existing runner flow

Creates:
- backup of mobile_runner.py before modification
"""

from pathlib import Path
import shutil
import datetime


RUNNER = Path("/storage/emulated/0/QPX_ALPHA/mobile_runner.py")
BACKUP = Path(
    "/storage/emulated/0/QPX_ALPHA/mobile_runner.py.step5_backup"
)


def create_backup():
    if not BACKUP.exists():
        shutil.copy2(RUNNER, BACKUP)
        print("[OK] Backup created:", BACKUP)
    else:
        print("[OK] Backup already exists:", BACKUP)


def repair_import_reference():

    text = RUNNER.read_text()

    if "import csv_importer" in text or "from quant_platform.mobile import csv_importer" in text:
        print("[OK] csv_importer import already present")
        return

    lines = text.splitlines()

    insert_index = 0

    # Insert after shebang if present
    if lines and lines[0].startswith("#!"):
        insert_index = 1

    import_block = [
        "",
        "# Step 5 repair: restore CSV importer runtime reference",
        "from quant_platform.mobile import csv_importer",
        ""
    ]

    lines[insert_index:insert_index] = import_block

    RUNNER.write_text("\n".join(lines) + "\n")

    print("[OK] csv_importer import restored")


def validate():

    text = RUNNER.read_text()

    if "csv_importer" in text:
        print("[OK] Runtime reference confirmed")
    else:
        print("[FAIL] csv_importer reference missing")


def main():

    print("=" * 45)
    print("QPX Alpha Step 5 Runner Repair")
    print("=" * 45)

    if not RUNNER.exists():
        print("[FAIL] mobile_runner.py not found")
        return

    create_backup()
    repair_import_reference()
    validate()

    print()
    print("Next command:")
    print(
        "python3 /storage/emulated/0/QPX_ALPHA/verify_step5_import_pipeline.py"
    )


if __name__ == "__main__":
    main()
