#!/usr/bin/env python3

"""
QPX Alpha Quant Research Platform
STEP 10 Backtesting Engine Repair Resume

Purpose:
- Detect non UTF-8 Step 10 files
- Convert safely to UTF-8
- Resume automated repair
- Verify repaired files exist
"""

from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(".")
BACKUP_DIR = Path("step10_encoding_backup")

TARGET_FILES = [
    "validate_step10_backtesting_engine.py",
    "repair_step10_backtesting_engine.py",
    "backtesting_engine.py",
    "repair_step10_backtesting_engine_validation.py",
]


def detect_encoding(path):
    """
    Try common encodings.
    """
    encodings = [
        "utf-8",
        "latin-1",
        "cp1252",
        "iso-8859-1"
    ]

    for enc in encodings:
        try:
            path.read_text(encoding=enc)
            return enc
        except Exception:
            continue

    return None


def convert_to_utf8(path):

    encoding = detect_encoding(path)

    if encoding is None:
        print(
            f"[FAIL] Unable to detect encoding: {path}"
        )
        return False

    if encoding == "utf-8":
        print(
            f"[PASS] Already UTF-8: {path}"
        )
        return True

    BACKUP_DIR.mkdir(exist_ok=True)

    backup = BACKUP_DIR / path.name

    shutil.copy2(path, backup)

    print(
        f"[BACKUP] {backup}"
    )

    content = path.read_text(
        encoding=encoding,
        errors="replace"
    )

    path.write_text(
        content,
        encoding="utf-8"
    )

    print(
        f"[FIXED] {path} converted {encoding} -> UTF-8"
    )

    return True


def repair_encoding():

    print(
        "\n[STEP10 REPAIR] Starting encoding repair\n"
    )

    success = True

    for filename in TARGET_FILES:

        file = ROOT / filename

        if not file.exists():

            print(
                f"[SKIP] Missing file: {filename}"
            )

            continue

        if not convert_to_utf8(file):
            success = False


    return success



def resume_step10_repair():

    """
    Search for existing repair scripts
    """

    candidates = [
        "repair_step10_backtesting_engine.py",
        "repair_step10_backtesting_engine_validation.py"
    ]


    for script in candidates:

        path = ROOT / script

        if path.exists():

            print(
                f"\n[EXECUTE] Resuming {script}"
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(path)
                ],
                capture_output=False
            )

            return result.returncode == 0


    print(
        "[FAIL] No Step 10 repair script found"
    )

    return False



def validate_files():

    print(
        "\n[STEP10 CHECK] Verifying repair outputs"
    )

    required = [
        "trade_event_schema_v2.py"
    ]

    status = True

    for item in required:

        if (ROOT / item).exists():

            print(
                f"[PASS] {item}"
            )

        else:

            print(
                f"[FAIL] Missing {item}"
            )

            status = False


    return status



def main():

    encoding_status = repair_encoding()

    if not encoding_status:

        print(
            "\n[BLOCKED] Encoding repair incomplete"
        )

        return


    repair_status = resume_step10_repair()

    validation_status = validate_files()


    print("\n==============================")
    print("STEP 10 REPAIR RESUME RESULT")
    print("==============================")

    if repair_status and validation_status:

        print(
            "STATUS: READY FOR VALIDATION"
        )

    else:

        print(
            "STATUS: REPAIR INCOMPLETE"
        )



if __name__ == "__main__":
    main()
