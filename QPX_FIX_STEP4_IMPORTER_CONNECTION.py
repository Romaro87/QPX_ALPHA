import os
import shutil
from datetime import datetime


TARGET = "/storage/emulated/0/mobile_runner.py"


OLD_CALL = '''csv_importer.import_market_csv(
    "sample_market.csv"
)'''


NEW_CALL = '''csv_importer.import_market_csv(
    "sample_market.csv",
    db.connection
)'''


def create_backup(path):

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    backup = (
        path
        +
        ".backup_"
        +
        timestamp
    )

    shutil.copy2(
        path,
        backup
    )

    print("[OK] Backup created:")
    print(backup)

    return backup


def repair_file(path):

    if not os.path.exists(path):
        print("[ERROR] File not found:")
        print(path)
        return False


    with open(
        path,
        "r",
        encoding="utf-8"
    ) as f:

        content = f.read()


    matches = content.count(
        OLD_CALL
    )


    print("[INFO] Importer call matches found:", matches)


    if matches == 0:

        print("[STOP]")
        print("Importer call pattern not found.")
        print("No changes made.")
        return False


    if matches > 1:

        print("[STOP]")
        print("Ambiguous importer calls detected.")
        print("No changes made.")
        return False


    create_backup(path)


    repaired = content.replace(
        OLD_CALL,
        NEW_CALL
    )


    with open(
        path,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(repaired)


    print("[OK] mobile_runner.py repaired")
    print("[OK] SQLite connection passed to CSV importer")

    return True



if __name__ == "__main__":

    print("==============================")
    print(" QPX STEP 4 IMPORTER REPAIR ")
    print("==============================")


    success = repair_file(
        TARGET
    )


    if success:

        print()
        print("Next test:")
        print("Run mobile_runner.py")
        print()
        print("Expected:")
        print("[OK] Imported X market records")

