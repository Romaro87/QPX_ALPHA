import sys

sys.path.append("/storage/emulated/0")

from quant_platform.data.sqlite.database import SQLiteDatabase
from quant_platform.data.sqlite.schema import create_tables

from quant_platform.data.sqlite.database import SQLiteDatabase
from quant_platform.data.sqlite.schema import create_tables


def start():

    print("==============================")
    print(" QPX Alpha v0.8 Mobile Core ")
    print("==============================")


    db = SQLiteDatabase(
        "qpx_mobile.db"
    )

    db.connect()

    create_tables(db)


    print("[OK] SQLite initialized")


    tables = db.fetch_all(
        """
        SELECT name 
        FROM sqlite_master
        WHERE type='table'
        """
    )


    print("[OK] Tables:")
    for table in tables:
        print(" -", table[0])


    print()
    print("QPX Alpha Mobile Core READY")


    db.close()



if __name__ == "__main__":
    start()


from quant_platform.mobile import csv_importer

print("[OK] Mobile CSV importer connected")

csv_importer.import_market_csv(
    "sample_market.csv"
)

