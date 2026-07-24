#!/usr/bin/env python3

import os
import sqlite3
import datetime


ROOT = "/storage/emulated/0/QPX_ALPHA"

DB = os.path.join(
    ROOT,
    "qpx_alpha.db"
)

REPORT = os.path.join(
    ROOT,
    "qpx_step12_pipeline_report_v3.txt"
)


def log(report, text):
    print(text)
    report.write(text + "\n")


def check_database(report):

    conn = sqlite3.connect(DB)

    cur = conn.cursor()

    cur.execute(
        "SELECT COUNT(*) FROM market_data"
    )

    count = cur.fetchone()[0]

    conn.close()

    log(
        report,
        f"[PASS] Market Data ({count} rows)"
    )

    return count > 0



def run_feature_engine(report):

    try:

        from feature_engine import FeatureEngine


        engine = FeatureEngine(DB)


        features = engine.run()


        log(
            report,
            "[PASS] Feature Engine"
        )


        return features


    except Exception as e:

        log(
            report,
            f"[FAIL] Feature Engine: {e}"
        )

        return None



def run_signal_engine(report, features):

    try:

        from signal_engine import SignalEngine


        engine = SignalEngine()


        signals = engine.generate_signal(
            features
        )


        log(
            report,
            "[PASS] Signal Engine"
        )


        return signals


    except Exception as e:

        log(
            report,
            f"[FAIL] Signal Engine: {e}"
        )

        return None



def run_backtest(report, signals):

    try:

        from backtesting_engine import BacktestEngine


        engine = BacktestEngine()


        result = engine.run(
            signals=signals
        )


        metrics = engine.generate_metrics()


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



def check_tables(report):

    conn = sqlite3.connect(DB)

    cur = conn.cursor()


    required = [
        "trades",
        "portfolio_snapshots"
    ]


    result=True


    for table in required:

        cur.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
            AND name=?
            """,
            (table,)
        )


        if cur.fetchone():

            log(
                report,
                f"[PASS] {table}"
            )

        else:

            log(
                report,
                f"[FAIL] Missing {table}"
            )

            result=False


    conn.close()

    return result



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
            "QPX STEP 12 PIPELINE SMOKE TEST V3"
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


        features = run_feature_engine(
            report
        )

        results.append(
            features is not None
        )


        signals = run_signal_engine(
            report,
            features
        )

        results.append(
            signals is not None
        )


        backtest = run_backtest(
            report,
            signals
        )

        results.append(
            backtest is not None
        )


        results.append(
            check_tables(report)
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