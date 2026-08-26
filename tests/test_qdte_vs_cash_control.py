from __future__ import annotations

import ast
from datetime import date
import inspect
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import QPX_RUN_QDTE_VS_CASH_CONTROL as experiment
from qpx_bot.causal_dividends import CausalDividendEvent
from qpx_bot.portfolio import Portfolio


class QDTEVersusCashHarnessTests(unittest.TestCase):
    def config(self):
        return SimpleNamespace(
            allocation_rebalance_tolerance=0.0025,
            minimum_rebalance_trade=1.0,
        )

    def rebalance(self, controller, portfolio, price=1.0):
        return controller.rebalance(
            portfolio=portfolio,
            income_shares=0.0,
            income_cost=0.0,
            qdte_price=price,
            position_prices={},
            target_income_weight=0.125,
            config=self.config(),
        )

    # 1
    def test_01_initial_cash_boundary(self):
        controller = experiment.CashSleeveController()
        portfolio = Portfolio(0.0)
        shares, cost, result = self.rebalance(controller, portfolio, 999.0)
        self.assertEqual((shares, cost), (0.0, 0.0))
        self.assertAlmostEqual(controller.reserved_cash, 162.5)
        self.assertAlmostEqual(portfolio.cash, 1137.5)
        self.assertEqual(result.realized_pnl, 0.0)

    # 2
    def test_02_reserved_cash_not_swing_cash(self):
        controller = experiment.CashSleeveController()
        portfolio = Portfolio(0.0)
        self.rebalance(controller, portfolio)
        self.assertEqual(portfolio.cash, 1137.5)
        self.assertEqual(controller.reserved_cash, 162.5)
        self.assertLess(portfolio.cash, 1300.0)

    # 3
    def test_03_nonzero_qdte_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "QDTE shares"):
            experiment.CashSleeveController().rebalance(
                portfolio=Portfolio(0.0),
                income_shares=0.01,
                income_cost=0.0,
                qdte_price=1.0,
                position_prices={},
                target_income_weight=0.125,
                config=self.config(),
            )

    # 4
    def test_04_controller_deterministic(self):
        outputs = []
        for _ in range(2):
            controller = experiment.CashSleeveController()
            portfolio = Portfolio(0.0)
            self.rebalance(controller, portfolio, 50.0)
            outputs.append((controller.reserved_cash, portfolio.cash))
        self.assertEqual(outputs[0], outputs[1])

    # 5
    def test_05_control_validator(self):
        result = {
            "ending_equity": 17370.70,
            "flow_adjusted_cagr": 1.9337,
            "maximum_drawdown": 0.3866,
            "sharpe_ratio": 2.1671,
            "sortino_ratio": 4.2198,
            "closed_trades": 1994,
            "qdte_distributions_received": 552.01,
        }
        experiment._validate_control({"result": result})
        with self.assertRaisesRegex(RuntimeError, "did not reproduce"):
            experiment._validate_control({"result": {**result, "closed_trades": 1}})

    # 6
    def test_06_delta_direction(self):
        names = (
            "ending_equity", "net_profit", "total_return", "maximum_drawdown",
            "realized_income_dividends", "cagr", "sharpe_ratio", "sortino_ratio",
        )
        self.assertEqual(
            experiment._delta(
                {name: 3.0 for name in names},
                {name: 1.0 for name in names},
            ),
            {name: 2.0 for name in names},
        )

    # 7
    def test_07_zero_qdte_attribution(self):
        value = experiment._qdte_attribution([], 0.0, False)
        self.assertEqual(value["maximum_shares_held"], 0.0)
        self.assertEqual(value["price_trading_contribution"], 0.0)

    # 8
    def test_08_import_boundary(self):
        experiment._assert_wrapper_boundaries()
        tree = ast.parse(inspect.getsource(experiment))
        direct = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        self.assertEqual(
            direct & {"QPX_RUN_FROZEN_TOP100_STRICT_CAUSAL"},
            {"QPX_RUN_FROZEN_TOP100_STRICT_CAUSAL"},
        )

    # 9
    def test_09_initial_capital_equality(self):
        identity = {"x": 1}
        experiment.validate_run_pair(
            {"starting_capital": 1300.0, "protected_identity": identity},
            {"starting_capital": 1300.0, "protected_identity": identity},
        )
        with self.assertRaisesRegex(RuntimeError, "starting capital"):
            experiment.validate_run_pair(
                {"starting_capital": 1300.0, "protected_identity": identity},
                {"starting_capital": 1301.0, "protected_identity": identity},
            )

    # 10
    def test_10_zero_yield_multiple_rebalances(self):
        controller = experiment.CashSleeveController()
        portfolio = Portfolio(0.0)
        for _ in range(3):
            before = controller.reserved_cash + portfolio.cash
            self.rebalance(controller, portfolio)
            self.assertAlmostEqual(controller.reserved_cash + portfolio.cash, before)
        self.assertEqual(controller.conservation_checks, 3)

    # 11
    def test_11_cash_conservation_with_deposit_and_transfer(self):
        controller = experiment.CashSleeveController()
        portfolio = Portfolio(0.0)
        self.rebalance(controller, portfolio)
        portfolio.deposit(100.0)
        before = controller.reserved_cash + portfolio.cash
        self.rebalance(controller, portfolio)
        self.assertAlmostEqual(controller.reserved_cash + portfolio.cash, before)

    # 12
    def test_12_reserved_excluded_from_sizing(self):
        controller = experiment.CashSleeveController()
        portfolio = Portfolio(25.0)
        controller.observe_equity(portfolio)
        controller.validate_sizing_cash(25.0)
        with self.assertRaisesRegex(RuntimeError, "leaked"):
            controller.validate_sizing_cash(1325.0)

    # 13
    def test_13_reserved_included_in_equity(self):
        instrumentation = experiment.RunInstrumentation()
        portfolio = Portfolio(25.0)
        with experiment._cash_intervention(instrumentation):
            self.assertEqual(experiment.qualified.Portfolio.equity(portfolio, {}), 1325.0)

    # 14
    def test_14_qdte_price_cannot_change_cash_equity(self):
        outcomes = []
        for price in (1.0, 9999.0):
            controller = experiment.CashSleeveController()
            portfolio = Portfolio(0.0)
            self.rebalance(controller, portfolio, price)
            outcomes.append(controller.reserved_cash + portfolio.cash)
        self.assertEqual(outcomes, [1300.0, 1300.0])

    # 15
    def test_15_qdte_dividend_cannot_change_cash(self):
        event = CausalDividendEvent(
            event_id="x",
            ex_date=date(2025, 1, 2),
            payable_date=date(2025, 1, 3),
            cash_amount=1.0,
        )
        ledger = experiment.qualified.CausalDividendLedger([event])
        ledger.process_open(current_date=date(2025, 1, 2), income_shares=0.0)
        self.assertEqual(
            ledger.process_open(current_date=date(2025, 1, 3), income_shares=0.0),
            0.0,
        )

    # 16
    def test_16_control_a_dividend_timing_untouched(self):
        original = experiment.qualified.CausalDividendLedger.process_open
        with experiment._cash_intervention(experiment.RunInstrumentation()):
            self.assertIs(experiment.qualified.CausalDividendLedger.process_open, original)
        self.assertIs(experiment.qualified.CausalDividendLedger.process_open, original)

    # 17
    def test_17_control_a_intervention_free(self):
        original = experiment.qualified.qpx._apply_rebalance
        with tempfile.TemporaryDirectory() as folder:
            def fake_run():
                self.assertIs(experiment.qualified.qpx._apply_rebalance, original)
                return {}, {}
            with mock.patch.object(experiment, "REPORT_ROOT", Path(folder)), mock.patch.object(
                experiment.qualified, "run_strict", fake_run
            ), mock.patch.object(
                experiment, "protected_identity", return_value={"id": 1}
            ), mock.patch.object(experiment, "_summarize_run", return_value={"ok": True}):
                self.assertEqual(experiment._run_variant("control", "control"), {"ok": True})

    # 18
    def test_18_noop_restores_patches(self):
        original = experiment.qualified.qpx._apply_rebalance
        with experiment._instrument_rebalances(experiment.RunInstrumentation()):
            self.assertIsNot(experiment.qualified.qpx._apply_rebalance, original)
        self.assertIs(experiment.qualified.qpx._apply_rebalance, original)

    # 19
    def test_19_cash_restores_after_success(self):
        originals = self.global_identities()
        with experiment._cash_intervention(experiment.RunInstrumentation()):
            pass
        self.assertEqual(self.global_identities(), originals)

    # 20
    def test_20_cash_restores_after_exception(self):
        originals = self.global_identities()
        with self.assertRaisesRegex(RuntimeError, "injected"):
            with experiment._cash_intervention(experiment.RunInstrumentation()):
                raise RuntimeError("injected")
        self.assertEqual(self.global_identities(), originals)

    def global_identities(self):
        return (
            experiment.qualified.qpx._apply_rebalance,
            experiment.qualified.Portfolio.equity,
            experiment.qualified.qpx.EquityPoint,
            experiment.qualified.buy_fill,
            experiment.qualified.calculate_position_size,
        )

    # 21
    def test_21_output_redirection_restores(self):
        original = experiment.qualified.REPORT_ROOT
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "new"
            with experiment._redirect_outputs(target):
                self.assertEqual(experiment.qualified.REPORT_ROOT, target)
        self.assertEqual(experiment.qualified.REPORT_ROOT, original)

    # 22
    def test_22_existing_destination_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(FileExistsError):
                with experiment._redirect_outputs(Path(folder)):
                    pass

    # 23
    def test_23_protected_scope_complete(self):
        paths = set(experiment.PROTECTED_PATHS)
        for required in (
            "qpx_bot/research_universes/alpaca_top100_qdte1300_thursday_v1.json",
            "qpx_bot/candidate_v1_causal.py",
            "qpx_bot/causal_replay.py",
            "qpx_bot/portfolio.py",
            "qpx_bot/causal_dividends.py",
            "qpx_bot/qualification_provenance.json",
        ):
            self.assertIn(required, paths)

    # 24
    def test_24_dataset_selection_config_identity(self):
        identity = {"dataset": "a", "selection": "b", "config": "c"}
        experiment.validate_identity_pair(identity, dict(identity))

    # 25
    def test_25_frozen_top100_identity(self):
        identity = experiment.protected_identity()
        self.assertEqual(len(identity["frozen_top100"]), 100)
        self.assertEqual(len(set(identity["frozen_top100"])), 100)
        selection = json.loads(
            experiment.qualified.baseline.SELECTION_PATH.read_text(encoding="utf-8")
        )
        self.assertEqual(identity["frozen_top100"], tuple(selection["top100"]))

    # 26
    def test_26_maximum_shares_includes_final_purchase(self):
        rows = [
            experiment.RebalanceObservation("BUY", 2.0, 5.0, 5.0, 3.0, 3.0, 0.0)
        ]
        value = experiment._qdte_attribution(rows, 5.0, True)
        self.assertEqual(value["maximum_shares_held"], 5.0)
        self.assertEqual(value["ending_shares"], 5.0)

    # 27
    def test_27_incorrect_slippage_attribution_removed(self):
        value = experiment._qdte_attribution([], 0.0, True)
        self.assertNotIn("estimated_slippage", value)

    # 28
    def test_28_equity_fingerprint_deterministic(self):
        rows = [{"time": "a", "equity": "1"}]
        self.assertEqual(
            experiment._canonical_fingerprint(rows),
            experiment._canonical_fingerprint(list(rows)),
        )

    # 29
    def test_29_allocation_fingerprint_deterministic(self):
        rows = [{"action": "NONE", "cash": "1"}]
        self.assertEqual(
            experiment._canonical_fingerprint(rows),
            experiment._canonical_fingerprint(list(rows)),
        )

    # 30
    def test_30_reserved_path_fingerprint_deterministic(self):
        path = {"2026-01-01T00:00:00Z": 162.5}
        self.assertEqual(
            experiment._canonical_fingerprint(path),
            experiment._canonical_fingerprint(dict(path)),
        )

    # 31
    def test_31_report_classification_and_nonclaims(self):
        self.assertEqual(
            experiment.EVIDENCE_CLASSIFICATION,
            "CAUSAL ECONOMIC RESEARCH CONDITIONAL ON THE FROZEN DISCOVERY UNIVERSE",
        )
        self.assertEqual(len(experiment.NON_CLAIMS), 8)
        source = inspect.getsource(experiment.main)
        self.assertIn("EVIDENCE_CLASSIFICATION", source)
        self.assertIn("NON_CLAIMS", source)

    # 32
    def test_32_natural_trade_divergence_allowed(self):
        identity = {"same": True}
        control = {
            "starting_capital": 1300.0,
            "protected_identity": identity,
            "trade_decision_keys": ["A"],
        }
        cash = {**control, "trade_decision_keys": ["B"]}
        experiment.validate_run_pair(control, cash)

    # 33
    def test_33_strategy_identity_change_fails(self):
        with self.assertRaisesRegex(RuntimeError, "candidate_config_fingerprint"):
            experiment.validate_identity_pair(
                {"candidate_config_fingerprint": "a"},
                {"candidate_config_fingerprint": "b"},
            )

    # 34
    def test_34_no_discovery_selector_or_qualification_state(self):
        tree = ast.parse(inspect.getsource(experiment))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
        for forbidden in experiment.FORBIDDEN_IMPORT_PREFIXES:
            self.assertFalse(any(name == forbidden or name.startswith(forbidden + ".") for name in names))

    # 35
    def test_35_no_network_or_future_data_api(self):
        tree = ast.parse(inspect.getsource(experiment))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".", 1)[0])
        self.assertTrue(imports.isdisjoint(experiment.FORBIDDEN_NETWORK_MODULES))
        experiment._assert_wrapper_boundaries()


if __name__ == "__main__":
    unittest.main()
