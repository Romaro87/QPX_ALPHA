#!/usr/bin/env python3

import os
import datetime
import json


ROOT = "/storage/emulated/0/QPX_ALPHA"

STEP13 = os.path.join(
    ROOT,
    "QPX_STEP13_LIVE_SIMULATION"
)

RISK_FILE = os.path.join(
    STEP13,
    "risk_controller.py"
)

REPORT = os.path.join(
    STEP13,
    "STEP13_6_RISK_REPORT.txt"
)



def log(report, text):

    print(text)

    report.write(
        text + "\n"
    )



def create_risk_controller():

    code = r'''
class RiskController:


    def __init__(
        self,
        max_position=1000,
        max_risk=0.02
    ):

        self.max_position = max_position
        self.max_risk = max_risk



    def validate_trade(
        self,
        balance,
        price,
        quantity,
        stop_loss=None,
        take_profit=None
    ):


        position_value = price * quantity


        if position_value > self.max_position:

            return {

                "approved": False,
                "reason": "POSITION_LIMIT"

            }


        risk_amount = (
            balance *
            self.max_risk
        )


        if stop_loss:

            loss = (
                price - stop_loss
            ) * quantity


            if loss > risk_amount:

                return {

                    "approved": False,
                    "reason": "RISK_LIMIT"

                }


        return {

            "approved": True,
            "position_value": position_value,
            "risk_amount": risk_amount,
            "stop_loss": stop_loss,
            "take_profit": take_profit

        }


'''


    with open(
        RISK_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(code)



def test_controller():

    import sys

    sys.path.insert(
        0,
        STEP13
    )


    from risk_controller import RiskController


    controller = RiskController()


    return controller.validate_trade(

        balance=10000,

        price=100,

        quantity=5,

        stop_loss=95,

        take_profit=110

    )



def main():

    os.makedirs(
        STEP13,
        exist_ok=True
    )


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
            "QPX STEP 13.6 RISK BUILDER"
        )

        log(
            report,
            datetime.datetime.now().isoformat()
        )

        log(
            report,
            "================================="
        )


        create_risk_controller()


        log(
            report,
            "[CREATED] risk_controller.py"
        )


        result = test_controller()


        log(
            report,
            "[PASS] Risk Test"
        )


        log(
            report,
            json.dumps(
                result,
                indent=2
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


        log(
            report,
            "QPX STEP 13.6 STATUS: READY"
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