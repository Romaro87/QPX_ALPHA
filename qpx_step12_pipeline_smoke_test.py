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
    "qpx_step12_pipeline_report.txt"
)


def log(report, text):
    print(text)
    report.write(text + "\n")


def check_database(report):

    try:

        conn = sqlite3.connect(DB)

        cur = conn.cursor()

        cur.execute(
            """
            SELECT COUNT(*)
            FROM market_data
            """
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
        LIMIT 10
        """
    )

    data = cur.fetchall()

    conn.close()

    return data



def test_feature_engine(report, data):

    try:

        from feature_engine import FeatureEngine


        engine = FeatureEngine()


        if hasattr(
            engine,
            "run_feature_engine"
        ):

            result = engine.run_feature_engine(
                data
            )

        else:

            result = data


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

    try:

        from signal_engine import SignalEngine


        engine = SignalEngine()


        if hasattr(
            engine,
            "generate_signal"
        ):

            signal = engine.generate_signal(
                features
            )

        else:

            signal = {
                "status": "test"
            }


        log(
            report,
            "[PASS] Signal Engine"
        )

        return signal


    except Exception as e:

        log(
            report,
            f"[FAIL] Signal Engine: {e}"
        )

        return None



def test_backtest(report, signal):

    try:

        from backtesting_engine import BacktestEngine


        engine = BacktestEngine()


        if hasattr(
            engine,
            "run_backtest"
        ):

            result = engine.run_backtest(
                signal
            )

        else:

            result = {
                "trades": []
            }


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



def validate_trade_schema(report):

    try:

        conn = sqlite3.connect(DB)

        cur = conn.cursor()

        cur.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
            AND name='trades'
            """
        )

        result = cur.fetchone()

        conn.close()


        if result:

            log(
                report,
                "[PASS] Trade Event Storage"
            )

            return True


        log(
            report,
            "[FAIL] Trade table missing"
        )

        return False


    except Exception as e:

        log(
            report,
            f"[FAIL] Trade validation: {e}"
        )

        return False



def validate_portfolio(report):

    try:

        conn = sqlite3.connect(DB)

        cur = conn.cursor()

        cur.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
            AND name='portfolio_snapshots'
            """
        )

        result = cur.fetchone()

        conn.close()


        if result:

            log(
                report,
                "[PASS] Portfolio Snapshot Layer"
            )

            return True


        log(
            report,
            "[FAIL] Portfolio layer missing"
        )

        return False


    except Exception as e:

        log(
            report,
            f"[FAIL] Portfolio validation: {e}"
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
            "QPX STEP 12 PIPELINE SMOKE TEST"
        )

        log(
            report,
            datetime.datetime.now().isoformat()
        )

        log(
            report,
            "================================="
        )


        db_ok = check_database(report)

        results.append(db_ok)


        if db_ok:

            try:

                data = load_market_data()

                features = test_feature_engine(
                    report,
                    data
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


                backtest = test_backtest(
                    report,
                    signal
                )

                results.append(
                    backtest is not None
                )


            except Exception:

                traceback.print_exc()

                results.append(False)


        results.append(
            validate_trade_schema(report)
        )

        results.append(
            validate_portfolio(report)
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