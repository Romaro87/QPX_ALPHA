from types import SimpleNamespace
import unittest

from qpx_bot.actual_two_year_15m_six import (
    _position_size_rejection_diagnostic,
    _reconcile_net_realized_tax_reserve,
)
from qpx_bot.config import BotConfig
from qpx_bot.portfolio import Portfolio, reconcile_net_realized_tax_reserve_balances


class NetRealizedTaxReserveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = BotConfig(annual_tax_reserve_rate=0.25)

    def test_profit_loss_negative_and_equity_preservation(self):
        portfolio = Portfolio(1_000.0)
        portfolio.cash = 975.0
        portfolio.tax_reserve_cash = 25.0
        portfolio.realized_pnl = 100.0
        self.assertEqual(
            _reconcile_net_realized_tax_reserve(portfolio=portfolio, config=self.config),
            0.0,
        )

        total_before = portfolio.cash + portfolio.tax_reserve_cash
        portfolio.realized_pnl = 40.0
        released = _reconcile_net_realized_tax_reserve(
            portfolio=portfolio, config=self.config
        )
        self.assertEqual(released, 15.0)
        self.assertEqual(portfolio.cash, 990.0)
        self.assertEqual(portfolio.tax_reserve_cash, 10.0)
        self.assertEqual(portfolio.cash + portfolio.tax_reserve_cash, total_before)

        portfolio.realized_pnl = -1.0
        released = _reconcile_net_realized_tax_reserve(
            portfolio=portfolio, config=self.config
        )
        self.assertEqual(released, 10.0)
        self.assertEqual(portfolio.cash, 1_000.0)
        self.assertEqual(portfolio.tax_reserve_cash, 0.0)
        self.assertEqual(portfolio.cash + portfolio.tax_reserve_cash, total_before)

    def test_reconciliation_is_idempotent(self):
        balances = reconcile_net_realized_tax_reserve_balances(
            cash=900.0,
            tax_reserve_cash=100.0,
            realized_pnl=200.0,
            reserve_rate=0.25,
        )
        self.assertEqual(balances, (950.0, 50.0, 50.0))
        self.assertEqual(
            reconcile_net_realized_tax_reserve_balances(
                cash=balances[0],
                tax_reserve_cash=balances[1],
                realized_pnl=200.0,
                reserve_rate=0.25,
            ),
            (950.0, 50.0, 0.0),
        )

    def test_existing_sizing_diagnostic_distinguishes_each_constraint(self):
        generic = {
            "blocked_reason": "Risk budget or cash is too small for one share.",
            "entry_fill": 10.0,
            "risk_per_share": 1.0,
            "risk_fraction": 0.01,
        }
        self.assertEqual(
            _position_size_rejection_diagnostic(
                account_equity=1_000.0,
                available_cash=0.0,
                active_risk=0.0,
                sizing=SimpleNamespace(**generic),
                config=self.config,
            ),
            "CASH_BELOW_ONE_SHARE",
        )
        self.assertEqual(
            _position_size_rejection_diagnostic(
                account_equity=50.0,
                available_cash=1_000.0,
                active_risk=0.0,
                sizing=SimpleNamespace(**generic),
                config=self.config,
            ),
            "BASE_RISK_BUDGET_BELOW_ONE_SHARE",
        )
        self.assertEqual(
            _position_size_rejection_diagnostic(
                account_equity=1_000.0,
                available_cash=1_000.0,
                active_risk=99.5,
                sizing=SimpleNamespace(**generic),
                config=self.config,
            ),
            "ACTIVE_RISK_CAP_BELOW_ONE_SHARE",
        )


if __name__ == "__main__":
    unittest.main()
