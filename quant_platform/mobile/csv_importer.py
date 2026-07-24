
import csv
import sqlite3
import os


DB_PATH = "/storage/emulated/0/QPX_ALPHA/qpx_alpha.db"


def _resolve_db():
    return DB_PATH


def import_csv(csv_file):

    if not os.path.exists(csv_file):
        raise FileNotFoundError(csv_file)

    db = _resolve_db()

    conn = sqlite3.connect(db)

    inserted = 0

    try:
        cur = conn.cursor()

        with open(csv_file, "r", newline="") as f:

            reader = csv.DictReader(f)

            for row in reader:

                timestamp = (
                    row.get("timestamp")
                    or row.get("date")
                    or row.get("time")
                )

                if timestamp is None:
                    continue


                symbol = (
                    row.get("symbol")
                    or row.get("ticker")
                    or ""
                )


                cur.execute(
                    """
                    INSERT INTO market_data
                    (
                        timestamp,
                        symbol,
                        open,
                        high,
                        low,
                        close,
                        volume
                    )
                    VALUES
                    (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        timestamp,
                        symbol,
                        row.get("open"),
                        row.get("high"),
                        row.get("low"),
                        row.get("close"),
                        row.get("volume"),
                    )
                )

                inserted += 1


        conn.commit()


    finally:
        conn.close()


    print("[IMPORT] Rows inserted:", inserted)

    if inserted == 0:
        raise RuntimeError(
            "Importer executed but inserted zero market_data rows"
        )

    return inserted



def import_market_data(csv_file):
    return import_csv(csv_file)



def import_market_csv(csv_file, connection=None):

    if connection is not None:

        cur = connection.cursor()

        inserted = 0

        with open(csv_file, "r", newline="") as f:

            reader = csv.DictReader(f)

            for row in reader:

                cur.execute(
                    """
                    INSERT INTO market_data
                    (
                        timestamp,
                        symbol,
                        open,
                        high,
                        low,
                        close,
                        volume
                    )
                    VALUES
                    (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row.get("timestamp"),
                        row.get("symbol"),
                        row.get("open"),
                        row.get("high"),
                        row.get("low"),
                        row.get("close"),
                        row.get("volume"),
                    )
                )

                inserted += 1


        connection.commit()

        return inserted


    return import_csv(csv_file)

