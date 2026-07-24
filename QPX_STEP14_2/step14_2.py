
import os
import datetime
import sqlite3


ROOT = "/storage/emulated/0/QPX_ALPHA"

DB = os.path.join(
    ROOT,
    "QPX_STEP13_LIVE_SIMULATION",
    "qpx_step13_simulation.db"
)

REPORT = os.path.join(
    ROOT,
    "QPX_STEP14_2",
    "STEP14_2_REPORT.txt"
)


def main():

    with open(
        REPORT,
        "w",
        encoding="utf-8"
    ) as f:

        f.write("===============================\n")
        f.write("QPX STEP 14.2 VALIDATION\n")
        f.write(
            datetime.datetime.now().isoformat()
            + "\n"
        )
        f.write("===============================\n\n")


        if os.path.exists(DB):

            f.write(
                "Database: OK\n"
            )

            try:

                conn = sqlite3.connect(DB)

                cur = conn.cursor()

                cur.execute(
                    "SELECT COUNT(*) FROM lifecycle_trades"
                )

                count = cur.fetchone()[0]

                conn.close()


                f.write(
                    "Lifecycle trades: "
                    + str(count)
                    + "\n"
                )

                f.write(
                    "STATUS: OPERATIONAL\n"
                )

            except Exception as e:

                f.write(
                    "Database check failed\n"
                )

                f.write(
                    str(e)
                )

        else:

            f.write(
                "Database missing\n"
            )


if __name__ == "__main__":
    main()
