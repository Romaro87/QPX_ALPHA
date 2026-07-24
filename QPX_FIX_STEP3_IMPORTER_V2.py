import os
import shutil


print("==============================")
print(" QPX Alpha CSV Importer Repair")
print("==============================")

# QPX Alpha location
BASE_PATH = "/storage/emulated/0/QPX_ALPHA"

IMPORTER_PATH = os.path.join(
    BASE_PATH,
    "quant_platform",
    "mobile",
    "csv_importer.py"
)

BACKUP_PATH = IMPORTER_PATH + ".backup"


# Check file exists
if not os.path.exists(IMPORTER_PATH):

    print("[ERROR] csv_importer.py not found")
    print(IMPORTER_PATH)
    input("Press Enter to exit...")
    exit()


print("[OK] Found csv_importer.py")


# Create backup
if not os.path.exists(BACKUP_PATH):

    shutil.copy(
        IMPORTER_PATH,
        BACKUP_PATH
    )

    print("[OK] Backup created")

else:

    print("[OK] Backup already exists")


# New importer code

new_code = r'''
import csv
from quant_platform.database.database import get_connection


def import_market_csv(filepath):

    conn = get_connection()
    cursor = conn.cursor()

    count = 0

    with open(filepath, "r") as file:

        reader = csv.DictReader(file)

        for row in reader:

            symbol = (
                row.get("symbol")
                or row.get("Symbol")
                or row.get("ticker")
                or row.get("Ticker")
                or "UNKNOWN"
            )

            date = (
                row.get("date")
                or row.get("Date")
            )

            open_price = (
                row.get("open")
                or row.get("Open")
            )

            high_price = (
                row.get("high")
                or row.get("High")
            )

            low_price = (
                row.get("low")
                or row.get("Low")
            )

            close_price = (
                row.get("close")
                or row.get("Close")
            )

            volume = (
                row.get("volume")
                or row.get("Volume")
                or 0
            )


            cursor.execute(
                """
                INSERT INTO market_data
                (
                symbol,
                date,
                open,
                high,
                low,
                close,
                volume
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                symbol,
                date,
                open_price,
                high_price,
                low_price,
                close_price,
                volume
                )
            )

            count += 1


    conn.commit()
    conn.close()

    return count
'''


# Write repair

with open(
    IMPORTER_PATH,
    "w"
) as file:

    file.write(new_code)


print()
print("[OK] csv_importer.py repaired")
print("[OK] import_market_csv() added")
print("[OK] Backup preserved")
print()
print("Next command:")
print("python mobile_runner.py")


input("Press Enter to exit...")
