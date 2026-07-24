
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


