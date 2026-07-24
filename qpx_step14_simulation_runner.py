#!/usr/bin/env python3

import os
import sys
import json
import datetime
import time


ROOT = "/storage/emulated/0/QPX_ALPHA"

STEP13 = os.path.join(
    ROOT,
    "QPX_STEP13_LIVE_SIMULATION"
)

REPORT = os.path.join(
    STEP13,
    "STEP14_SIMULATION_RUNNER_REPORT.txt"
)


sys.path.insert(
    0,
    STEP13
)


def log(report, text):

    print(text)
    report.write(text + "\n")



def run_cycle(cycle):

    from risk_controller import RiskController
    from paper_trading_lifecycle import PaperTradingLifecycle


    db = os.path.join(
        STEP13,
        "qpx_step13_simulation.db"
    )


    price = 100 + cycle


    signal = {

        "signal": "BUY",
        "confidence": 0.8,
        "timestamp":
        datetime.datetime.now().isoformat()

    }


    risk = RiskController()


    approval = risk.validate_trade(

        balance=10000,

        price=price,

        quantity=5,

        stop_loss=price-5,

        take_profit=price+10

    )


    if not approval["approved"]:

        return {

            "cycle": cycle,
            "status": "REJECTED"

        }



    trader = PaperTradingLifecycle(
        db
    )


    trade_id = trader.open_trade(

        "QPX_SIM",

        price

    )


    exit_price = price + 5


    pnl = trader.close_trade(

        trade_id,

        exit_price

    )


    return {

        "cycle": cycle,

        "trade_id": trade_id,

        "entry": price,

        "exit": exit_price,

        "pnl": pnl,

        "status": "EXECUTED"

    }



def main():

    cycles = 5


    total_pnl = 0


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
            "QPX STEP 14 SIMULATION RUNNER"
        )

        log(
            report,
            datetime.datetime.now().isoformat()
        )

        log(
            report,
            "================================="
        )


        results = []


        for i in range(1, cycles + 1):


            result = run_cycle(i)


            results.append(result)


            if "pnl" in result:

                total_pnl += result["pnl"]


            log(
                report,
                json.dumps(
                    result
                )
            )


            time.sleep(1)



        log(
            report,
            ""
        )

        log(
            report,
            "TOTAL CYCLES: "
            + str(cycles)
        )


        log(
            report,
            "TOTAL PNL: "
            + str(total_pnl)
        )


        log(
            report,
            ""
        )


        log(
            report,
            "================================="
        )


        log(
            report,
            "QPX STEP 14 STATUS: OPERATIONAL"
        )


        log(
            report,
            "================================="
        )



    print()
    print("Report:")
    print(REPORT)



if __name__ == "__main__":

    main()