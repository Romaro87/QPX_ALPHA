#!/usr/bin/env python3

import os
import shutil
import datetime
import subprocess
import sys


ROOT = "/storage/emulated/0/QPX_ALPHA"

OLD_TEST = os.path.join(
    ROOT,
    "qpx_step12_pipeline_smoke_test_v3.py"
)

NEW_TEST = os.path.join(
    ROOT,
    "qpx_step12_pipeline_smoke_test_v4.py"
)


REPORT = os.path.join(
    ROOT,
    "qpx_step12_auto_fix_report.txt"
)


def log(f, text):
    print(text)
    f.write(text + "\n")


def backup_old():

    if os.path.exists(OLD_TEST):

        backup = OLD_TEST + ".backup"

        shutil.copy2(
            OLD_TEST,
            backup
        )

        return backup

    return None



def create_v4():

    code = r'''
#!/usr/bin/env python3

import os
import sqlite3
import datetime


ROOT="/storage/emulated/0/QPX_ALPHA"

DB=os.path.join(
    ROOT,
    "qpx_alpha.db"
)

REPORT=os.path.join(
    ROOT,
    "qpx_step12_pipeline_report_v4.txt"
)


def log(report,msg):
    print(msg)
    report.write(msg+"\n")


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
            "QPX STEP 12 PIPELINE SMOKE TEST V4"
        )

        log(
            report,
            datetime.datetime.now().isoformat()
        )

        log(
            report,
            "================================="
        )


        try:

            conn=sqlite3.connect(DB)

            cur=conn.cursor()

            cur.execute(
                "SELECT COUNT(*) FROM market_data"
            )

            rows=cur.fetchone()[0]

            conn.close()


            log(
                report,
                f"[PASS] Market Data ({rows} rows)"
            )

            results.append(True)


        except Exception as e:

            log(
                report,
                f"[FAIL] Market Data {e}"
            )

            results.append(False)



        try:

            from feature_engine import FeatureEngine

            feature_engine=FeatureEngine(DB)

            features=feature_engine.run()


            log(
                report,
                "[PASS] Feature Engine"
            )

            results.append(True)


        except Exception as e:

            log(
                report,
                f"[FAIL] Feature Engine {e}"
            )

            features=None
            results.append(False)



        try:

            from signal_engine import SignalEngine


            signal_engine=SignalEngine()

            signal=signal_engine.generate_signal(
                features
            )


            log(
                report,
                "[PASS] Signal Engine"
            )

            results.append(True)


        except Exception as e:

            log(
                report,
                f"[FAIL] Signal Engine {e}"
            )

            signal=None
            results.append(False)



        try:

            from backtesting_engine import BacktestEngine


            if isinstance(signal,dict):

                signals=[signal]

            else:

                signals=signal


            engine=BacktestEngine()


            result=engine.run(
                signals=signals,
                historical_data=features
            )


            metrics=engine.generate_metrics()


            log(
                report,
                "[PASS] Backtesting Engine"
            )

            log(
                report,
                str(metrics)
            )

            results.append(True)


        except Exception as e:

            log(
                report,
                f"[FAIL] Backtesting Engine {e}"
            )

            results.append(False)



        for table in [
            "trades",
            "portfolio_snapshots"
        ]:

            try:

                conn=sqlite3.connect(DB)

                cur=conn.cursor()

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

                    results.append(True)


                else:

                    results.append(False)


                conn.close()


            except:

                results.append(False)



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
            "=================================")



if __name__=="__main__":
    main()
'''

    with open(
        NEW_TEST,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(code)



def run_test():

    result=subprocess.run(
        [
            sys.executable,
            NEW_TEST
        ],
        capture_output=True,
        text=True
    )

    return result.stdout + result.stderr



def main():

    with open(
        REPORT,
        "w",
        encoding="utf-8"
    ) as report:


        log(
            report,
            "QPX STEP 12 AUTO FIX"
        )


        backup=backup_old()


        if backup:

            log(
                report,
                f"Backup created: {backup}"
            )


        create_v4()


        log(
            report,
            "Created Step 12 V4 test"
        )


        output=run_test()


        log(
            report,
            "\nTEST OUTPUT:"
        )


        log(
            report,
            output
        )


        log(
            report,
            "\nCOMPLETE"
        )


    print()
    print(
        "Report:"
    )

    print(
        REPORT
    )


if __name__=="__main__":
    main()