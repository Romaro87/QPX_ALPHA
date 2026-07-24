import os
import shutil
from datetime import datetime


TARGET = "/storage/emulated/0/mobile_runner.py"


def make_backup():

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = TARGET + ".backup_" + stamp

    shutil.copy2(TARGET, backup)

    print("[OK] Backup created:")
    print(backup)


def repair():

    if not os.path.exists(TARGET):
        print("[ERROR] File missing")
        return


    make_backup()


    with open(TARGET, "r", encoding="utf-8") as f:
        content = f.read()


    print("[OK] File inspected")
    print("[INFO] Characters:", len(content))


    lines = content.splitlines()


    # Remove duplicate sqlite imports
    sqlite_imports = {
        "from quant_platform.data.sqlite.database import SQLiteDatabase",
        "from quant_platform.data.sqlite.schema import create_tables"
    }


    output = []
    seen = set()


    for line in lines:

        if line.strip() in sqlite_imports:

            if line.strip() in seen:
                continue

            seen.add(line.strip())


        output.append(line)


    content = "\n".join(output)


    # Remove importer execution after main guard

    guard = 'if __name__ == "__main__":'

    guard_position = content.find(guard)

    if guard_position != -1:

        after_guard = content[guard_position:]

        if "csv_importer" in after_guard:

            content = content[:guard_position]

            content += '''
if __name__ == "__main__":
    start()
'''

            print("[OK] Removed importer after main guard")


    # Insert importer before db.close()

    required_block = '''
    from quant_platform.mobile import csv_importer

    print("[OK] Mobile CSV importer connected")

    csv_importer.import_market_csv(
        "sample_market.csv",
        db.connection
    )

'''


    close_marker = "    db.close()"


    if close_marker not in content:

        print("[ERROR] Could not locate db.close()")
        return


    if "db.connection" not in content:

        content = content.replace(
            close_marker,
            required_block + close_marker,
            1
        )

        print("[OK] Importer inserted inside start()")


    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(content)


    print("[OK] Saved repaired file")


    # Verification

    with open(TARGET, "r", encoding="utf-8") as f:
        verify = f.read()


    checks = [
        "from quant_platform.data.sqlite.database import SQLiteDatabase",
        "from quant_platform.data.sqlite.schema import create_tables",
        "from quant_platform.mobile import csv_importer",
        "db.connection",
        "csv_importer.import_market_csv",
        "db.close()",
        'if __name__ == "__main__":'
    ]


    failed = False


    for check in checks:

        if check in verify:
            print("[PASS]", check)
        else:
            print("[FAIL]", check)
            failed = True


    if failed:
        print("[ERROR] Verification failed")
    else:
        print("[OK] Step 4 repair verified")


if __name__ == "__main__":
    print("==============================")
    print(" QPX STEP 4 REPAIR v4 ")
    print("==============================")

    repair()
