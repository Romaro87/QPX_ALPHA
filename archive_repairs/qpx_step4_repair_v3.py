import os
import shutil
from datetime import datetime


TARGET = "/storage/emulated/0/mobile_runner.py"


def backup(path):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = path + ".backup_" + stamp
    shutil.copy2(path, backup_path)
    print("[OK] Backup:", backup_path)


def repair():

    if not os.path.exists(TARGET):
        print("[ERROR] Missing:", TARGET)
        return

    backup(TARGET)

    with open(TARGET, "r", encoding="utf-8") as f:
        content = f.read()

    print("[OK] Loaded file")
    print("[INFO] Size:", len(content))

    # Remove duplicate SQLite imports
    lines = content.splitlines()

    imports = {
        "from quant_platform.data.sqlite.database import SQLiteDatabase",
        "from quant_platform.data.sqlite.schema import create_tables"
    }

    seen = set()
    cleaned = []

    for line in lines:
        if line.strip() in imports:
            if line.strip() in seen:
                continue
            seen.add(line.strip())

        cleaned.append(line)

    content = "\n".join(cleaned)


    # Remove everything after main guard
    guard = 'if __name__ == "__main__":'

    guard_index = content.find(guard)

    if guard_index != -1:

        content = content[:guard_index]

        content += '''
if __name__ == "__main__":
    start()
'''

    print("[OK] Main guard cleaned")


    # Insert importer before db.close()

    importer_block = '''
    from quant_platform.mobile import csv_importer

    print("[OK] Mobile CSV importer connected")

    csv_importer.import_market_csv(
        "sample_market.csv",
        db.connection
    )

'''


    close_index = content.find("    db.close()")

    if close_index == -1:
        print("[ERROR] db.close() not found")
        return


    if "db.connection" not in content:

        content = (
            content[:close_index]
            + importer_block
            + content[close_index:]
        )

        print("[OK] Importer inserted")

    else:
        print("[INFO] Importer already present")


    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(content)


    print("[OK] File written")


    # Verification

    with open(TARGET, "r", encoding="utf-8") as f:
        verify = f.read()


    checks = [
        "from quant_platform.data.sqlite.database import SQLiteDatabase",
        "from quant_platform.data.sqlite.schema import create_tables",
        "from quant_platform.mobile import csv_importer",
        "db.connection",
        "db.close()",
        'if __name__ == "__main__":'
    ]


    failed = False

    for item in checks:
        if item in verify:
            print("[PASS]", item)
        else:
            print("[FAIL]", item)
            failed = True


    if failed:
        print("[VERIFY FAILED]")
    else:
        print("[OK] Repair complete")


if __name__ == "__main__":
    print("==============================")
    print(" QPX STEP 4 REPAIR v3 ")
    print("==============================")
    repair()
