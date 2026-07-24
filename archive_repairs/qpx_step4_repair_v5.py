import os
import shutil
from datetime import datetime


TARGET = "/storage/emulated/0/mobile_runner.py"


def backup_file():

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = TARGET + ".backup_" + stamp

    shutil.copy2(TARGET, backup)

    print("[OK] Backup created:")
    print(backup)



def repair():

    if not os.path.exists(TARGET):
        print("[ERROR] Target missing")
        return


    backup_file()


    with open(TARGET, "r", encoding="utf-8") as f:
        content = f.read()


    print("[OK] Inspected mobile_runner.py")
    print("[INFO] Length:", len(content))


    lines = content.splitlines()


    # Remove duplicate imports
    cleaned = []
    seen_imports = set()

    allowed_imports = {
        "from quant_platform.data.sqlite.database import SQLiteDatabase",
        "from quant_platform.data.sqlite.schema import create_tables"
    }


    for line in lines:

        stripped = line.strip()

        if stripped in allowed_imports:

            if stripped in seen_imports:
                continue

            seen_imports.add(stripped)


        cleaned.append(line)


    content = "\n".join(cleaned)



    # Remove any importer block after main guard

    marker = 'if __name__ == "__main__":'

    guard_index = content.find(marker)


    if guard_index != -1:

        before = content[:guard_index]

        after = content[guard_index:]

        if "csv_importer" in after:

            after = 'if __name__ == "__main__":\n    start()\n'

            content = before.rstrip() + "\n\n" + after

            print("[OK] Removed importer outside main guard")



    # Insert importer before db.close()

    block = '''
    from quant_platform.mobile import csv_importer

    print("[OK] Mobile CSV importer connected")

    csv_importer.import_market_csv(
        "sample_market.csv",
        db.connection
    )

'''


    if "csv_importer.import_market_csv" not in content:

        if "    db.close()" in content:

            content = content.replace(
                "    db.close()",
                block + "    db.close()",
                1
            )

            print("[OK] Inserted importer before db.close()")

        else:

            print("[ERROR] db.close() not found")
            return



    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(content)



    print("[OK] Saved repair")



    # Verify

    with open(TARGET, "r", encoding="utf-8") as f:
        verify = f.read()


    tests = [

        "from quant_platform.data.sqlite.database import SQLiteDatabase",

        "from quant_platform.data.sqlite.schema import create_tables",

        "from quant_platform.mobile import csv_importer",

        'csv_importer.import_market_csv(\n        "sample_market.csv",\n        db.connection',

        "db.close()",

        'if __name__ == "__main__":\n    start()'

    ]


    failed = False


    for item in tests:

        if item in verify:
            print("[PASS]", item[:50])

        else:
            print("[FAIL]", item[:50])
            failed = True


    if failed:
        print("[ERROR] Verification failed")

    else:
        print("[OK] Step 4 repair v5 complete")



if __name__ == "__main__":
    repair()
