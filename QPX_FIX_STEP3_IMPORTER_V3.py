import os
import shutil

print("==============================")
print(" QPX Alpha Importer Repair V3")
print("==============================")

target = None

for root, dirs, files in os.walk("."):
    for file in files:
        if file == "csv_importer.py":
            target = os.path.join(root, file)
            break

    if target:
        break


if not target:
    print("[ERROR] csv_importer.py not found")
    exit()


print("[OK] Found:")
print(target)


backup = target + ".backup_v3"

shutil.copy(target, backup)

print("[OK] Backup created:")
print(backup)


new_code = r'''
import csv
import os


def import_market_csv(csv_file, connection):

    imported = 0

    with open(csv_file, "r") as file:

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
                or row.get("timestamp")
                or ""
            )

            open_price = (
                row.get("open")
                or row.get("Open")
                or 0
            )

            high = (
                row.get("high")
                or row.get("High")
                or 0
            )

            low = (
                row.get("low")
                or row.get("Low")
                or 0
            )

            close = (
                row.get("close")
                or row.get("Close")
                or 0
            )

            volume = (
                row.get("volume")
                or row.get("Volume")
                or 0
            )


            connection.execute(
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
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                symbol,
                date,
                open_price,
                high,
                low,
                close,
                volume
                )
            )

            imported += 1


    connection.commit()

    print(f"[OK] Imported {imported} market records")

    return imported
'''

with open(target,"w") as f:
    f.write(new_code)


print("[OK] csv_importer.py repaired")
print("==============================")
print("Run:")
print("python mobile_runner.py")
print("==============================")
