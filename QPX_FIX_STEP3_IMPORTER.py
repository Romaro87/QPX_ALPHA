from pathlib import Path

print("==============================")
print(" QPX Alpha v0.8 Step 3 Fix")
print(" CSV Importer Repair Tool")
print("==============================")


# Location of mobile importer
file_path = Path("quant_platform/mobile/csv_importer.py")


if not file_path.exists():
    print("[ERROR] csv_importer.py not found")
    print("Check that you are running this inside the QPX Alpha folder")
    exit()


new_code = '''

import csv
import sqlite3


DATABASE_PATH = "qpx_alpha.db"


def import_market_csv(csv_file):

    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    imported = 0

    with open(csv_file, "r") as file:

        reader = csv.DictReader(file)

        for row in reader:

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
                    row["symbol"],
                    row["date"],
                    row["open"],
                    row["high"],
                    row["low"],
                    row["close"],
                    row["volume"]
                )
            )

            imported += 1


    conn.commit()
    conn.close()

    return imported

'''


with open(file_path, "w") as file:
    file.write(new_code)


print("[OK] csv_importer.py repaired")
print("[OK] import_market_csv() added")
print("")
print("Run next:")
print("python mobile_runner.py")
print("==============================")
