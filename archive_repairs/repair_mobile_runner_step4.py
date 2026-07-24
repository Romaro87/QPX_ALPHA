import os
import shutil
from datetime import datetime

TARGET = "/storage/emulated/0/mobile_runner.py"

print("[STEP 1] Checking target file")

if not os.path.exists(TARGET):
    raise FileNotFoundError(TARGET)

backup = TARGET + ".backup_" + datetime.now().strftime("%Y%m%d_%H%M%S")

shutil.copy2(TARGET, backup)

print("[OK] Backup created:")
print(backup)


print("[STEP 2] Reading actual file")

with open(TARGET, "r", encoding="utf-8") as f:
    content = f.read()

print("[OK] Inspected mobile_runner.py")
print("[INFO] Length:", len(content.splitlines()))


print("[STEP 3] Removing duplicate SQLite imports")

imports = """from quant_platform.data.sqlite.database import SQLiteDatabase
from quant_platform.data.sqlite.schema import create_tables"""

content = content.replace(
    imports + "\n\n" + imports,
    imports
)


print("[STEP 4] Removing misplaced importer block")

bad_block = """
from quant_platform.mobile import csv_importer

print("[OK] Mobile CSV importer connected")

csv_importer.import_market_csv(
    "sample_market.csv"
)
"""

content = content.replace(bad_block, "")


print("[STEP 5] Inserting importer inside start() before db.close()")

insert_block = """
    from quant_platform.mobile import csv_importer

    print("[OK] Mobile CSV importer connected")

    csv_importer.import_market_csv(
        "sample_market.csv",
        db.connection
    )

"""

marker = """
    db.close()
"""

if marker not in content:
    raise Exception("[ERROR] db.close() not found")

content = content.replace(
    marker,
    insert_block + marker,
    1
)


print("[STEP 6] Writing repaired file")

with open(TARGET, "w", encoding="utf-8") as f:
    f.write(content)


print("[STEP 7] Verification")

with open(TARGET, "r", encoding="utf-8") as f:
    verify = f.read()


required = [
    "from quant_platform.data.sqlite.database import SQLiteDatabase",
    "from quant_platform.data.sqlite.schema import create_tables",
    "csv_importer.import_market_csv(",
    "sample_market.csv",
    "db.connection",
    "if __name__ == \"__main__\":",
    "start()"
]

for item in required:
    if item not in verify:
        raise Exception("[ERROR] Missing:", item)


if verify.count(
    "from quant_platform.data.sqlite.database import SQLiteDatabase"
) != 1:
    raise Exception("[ERROR] Duplicate SQLiteDatabase import remains")


if verify.count(
    "from quant_platform.data.sqlite.schema import create_tables"
) != 1:
    raise Exception("[ERROR] Duplicate create_tables import remains")


print("[OK] Repair verification passed")
print("[OK] mobile_runner.py repaired")
