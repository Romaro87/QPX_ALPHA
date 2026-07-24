
class MobileReport:


    def summary(self,metrics):

        return {

        "Return":metrics.get("return"),

        "Sharpe":metrics.get("sharpe"),

        "Drawdown":metrics.get("drawdown")

        }
