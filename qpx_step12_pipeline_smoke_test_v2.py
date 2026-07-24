#!/usr/bin/env python3

import os
import sqlite3
import datetime
import traceback


ROOT = "/storage/emulated/0/QPX_ALPHA"

DB = os.path.join(
    ROOT,
    "qpx_alpha.db"
)

REPORT = os.path.join(
    ROOT,
    "qpx_step12_pipeline_report_v2.txt"
)


def log(report, text):
    print(text)
    report.write(text + "\n")


def check_database(report):

    try:

        conn = sqlite3.connect(DB)

        cur = conn.cursor()

        cur.execute(
            "SELECT COUNT(*) FROM market_data"
        )

        rows = cur.fetchone()[0]

        conn.close()

        log(
            report,
            f"[PASS] Market Data ({rows} rows)"
        )

        return True

    except Exception as e:

        log(
            report,
            f"[FAIL] Database: {e}"
        )

        return False



def load_market_data():

    conn = sqlite3.connect(DB)

    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM market_data
        ORDER BY rowid
        """
    )

    data = cur.fetchall()

    conn.close()

    return data



def test_feature_engine(report):

    try:

        from feature_engine import FeatureEngine

        engine = FeatureEngine(DB)

        result = engine.run_feature_engine()


        log(
            report,
            "[PASS] Feature Engine"
        )


        return result


    except Exception as e:

        log(
            report,
            f"[FAIL] Feature Engine: {e}"
        )

        return None



def test_signal_engine(report, features):

    if features is None:

        log(
            report,
            "[FAIL] Signal Engine: Feature input unavailable"
        )

        return None


    try:

        from signal_engine import SignalEngine

        engine = SignalEngine()

        result = engine.generate_signal(
            features
        )


        log(
            report,
            "[PASS] Signal Engine"
        )


        return result


    except Exception as e:

        log(
            report,
            f"[FAIL] Signal Engine: {e}"
        )

        return None



def test_backtesting(report, signal):

    try:

        from backtesting_engine import BacktestEngine

        engine = BacktestEngine()

        result = engine.run_backtest(
            signal
        )


        log(
            report,
            "[PASS] Backtesting Engine"
        )


        return result


    except Exception as e:

        log(
            report,
            f"[FAIL] Backtesting Engine: {e}"
        )

        return None



def check_table(report, table):

    try:

        conn = sqlite3.connect(DB)

        cur = conn.cursor()

        cur.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
            AND name=?
            """,
            (table,)
        )

        result = cur.fetchone()

        conn.close()


        if result:

            log(
                report,
                f"[PASS] {table}"
            )

            return True


        log(
            report,
            f"[FAIL] Missing table {table}"
        )

        return False


    except Exception as e:

        log(
            report,
            f"[FAIL] {table}: {e}"
        )

        return False



def main():

    results=[]


    with open(
        REPORT,
        "w",
        encoding="utf-8"
    ) as report:


        log(
            report,
            "================================="
        )

        log(
            report,
            "QPX STEP 12 PIPELINE SMOKE TEST V2"
        )

        log(
            report,
            datetime.datetime.now().isoformat()
        )

        log(
            report,
            "================================="
        )


        results.append(
            check_database(report)
        )


        features = None
        signal = None


        if results[0]:

            features = test_feature_engine(
                report
            )

            results.append(
                features is not None
            )


            signal = test_signal_engine(
                report,
                features
            )

            results.append(
                signal is not None
            )


            backtest = test_backtesting(
                report,
                signal
            )

            results.append(
                backtest is not None
            )


        results.append(
            check_table(
                report,
                "trades"
            )
        )


        results.append(
            check_table(
                report,
                "portfolio_snapshots"
            )
        )


        log(
            report,
            ""
        )

        log(
            report,
            "================================="
        )


        if all(results):

            log(
                report,
                "QPX PIPELINE STATUS: OPERATIONAL"
            )

        else:

            log(
                report,
                "QPX PIPELINE STATUS: NEEDS REVIEW"
            )


        log(
            report,
            "================================="
        )



    print()
    print(
        "Report:"
    )
    print(
        REPORT
    )



if __name__ == "__main__":
    main()