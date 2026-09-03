from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from qpx_bot.broker_account_provider import (
    BrokerAccountProvider,
    BrokerAccountProviderRegistry,
    BrokerAccountSnapshot,
    BrokerPosition,
    DUMMY_PROVIDER_IDENTITY,
    ProviderSelection,
    build_broker_account_provider,
    load_provider_selection,
    write_dummy_broker_account_state,
)
from qpx_bot.pr50_iex_forward_research_paper import (
    BROKER_PROVIDER_CONFIG_ENV,
    broker_reconciliation_enabled,
    configured_broker_account_provider,
)


ROOT = Path(__file__).resolve().parents[1]


class BrokerAccountProviderTests(unittest.TestCase):
    observed = datetime(2026, 9, 2, 14, 0, tzinfo=timezone.utc)

    @staticmethod
    def state(cash: str, positions: list[dict]) -> dict:
        return {
            "schema_version": 1,
            "provider_identity": "DUMMY",
            "account_identity": "operator-configured-dummy-account",
            "account_status": "ACTIVE",
            "cash": cash,
            "equity": cash,
            "portfolio_value": cash,
            "buying_power": cash,
            "currency": "USD",
            "positions": positions,
            "trading_blocked": False,
            "account_blocked": False,
            "restriction_flags": [],
        }

    @staticmethod
    def selection(path: Path) -> ProviderSelection:
        return ProviderSelection(
            schema_version=1,
            market_data_provider="ALPACA_IEX",
            broker_account_provider="DUMMY",
            order_execution_provider="SIMULATED",
            broker_account_configuration={"state_path": str(path)},
        )

    def test_dummy_cash_and_positions_come_only_from_external_state(self):
        with tempfile.TemporaryDirectory() as folder:
            state_path = Path(folder) / "dummy_account.json"
            write_dummy_broker_account_state(state_path, self.state("1400", []))
            provider = build_broker_account_provider(self.selection(state_path))
            first = provider.observe(self.observed)
            self.assertEqual(first.cash, Decimal("1400"))
            self.assertEqual(first.positions, ())

            arbitrary = self.state("24.416625", [
                {
                    "symbol": "QDTE",
                    "side": "long",
                    "quantity": "50",
                    "average_entry_price": "28.9116675",
                    "cost_basis": "1445.583375",
                    "market_value": "1500",
                    "current_price": "30",
                    "asset_class": "us_equity",
                }
            ])
            arbitrary["equity"] = "1524.416625"
            arbitrary["portfolio_value"] = "1524.416625"
            write_dummy_broker_account_state(state_path, arbitrary)
            second = provider.observe(self.observed)
            self.assertEqual(second.cash, Decimal("24.416625"))
            self.assertEqual(second.positions[0].symbol, "QDTE")
            self.assertEqual(second.positions[0].quantity, Decimal("50"))

    def test_provider_selection_keeps_three_roles_independent(self):
        with tempfile.TemporaryDirectory() as folder:
            folder_path = Path(folder)
            state_path = folder_path / "account.json"
            config_path = folder_path / "providers.json"
            write_dummy_broker_account_state(state_path, self.state("900", []))
            config_path.write_text(json.dumps({
                "schema_version": 1,
                "market_data_provider": "ALPACA_IEX",
                "broker_account_provider": "DUMMY",
                "order_execution_provider": "SIMULATED",
                "broker_account_configuration": {
                    "state_path": "account.json",
                },
            }), encoding="utf-8")
            selection = load_provider_selection(config_path)
            provider = build_broker_account_provider(selection)
            self.assertEqual(selection.market_data_provider, "ALPACA_IEX")
            self.assertEqual(selection.broker_account_provider, "DUMMY")
            self.assertEqual(selection.order_execution_provider, "SIMULATED")
            self.assertEqual(provider.provider_identity, DUMMY_PROVIDER_IDENTITY)
            self.assertEqual(provider.observe(self.observed).cash, Decimal("900"))

    def test_clean_v2_provider_selection_is_configuration_driven_and_opt_in(self):
        with tempfile.TemporaryDirectory() as folder:
            folder_path = Path(folder)
            state_path = folder_path / "account.json"
            config_path = folder_path / "providers.json"
            write_dummy_broker_account_state(state_path, self.state("654.32", []))
            config_path.write_text(json.dumps({
                "schema_version": 1,
                "market_data_provider": "ALPACA_IEX",
                "broker_account_provider": "DUMMY",
                "order_execution_provider": "SIMULATED",
                "broker_account_configuration": {"state_path": "account.json"},
            }), encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                self.assertFalse(broker_reconciliation_enabled())
            with patch.dict(
                os.environ,
                {BROKER_PROVIDER_CONFIG_ENV: str(config_path)},
                clear=True,
            ):
                self.assertTrue(broker_reconciliation_enabled())
                selection, provider = configured_broker_account_provider()
            self.assertEqual(selection.market_data_provider, "ALPACA_IEX")
            self.assertEqual(selection.broker_account_provider, "DUMMY")
            self.assertEqual(selection.order_execution_provider, "SIMULATED")
            self.assertEqual(provider.observe(self.observed).cash, Decimal("654.32"))

    def test_snapshot_is_canonical_and_contains_no_dummy_native_payload(self):
        with tempfile.TemporaryDirectory() as folder:
            state_path = Path(folder) / "account.json"
            write_dummy_broker_account_state(state_path, self.state("777.25", []))
            snapshot = build_broker_account_provider(
                self.selection(state_path)
            ).observe(self.observed)
            self.assertIsInstance(snapshot, BrokerAccountSnapshot)
            self.assertIsInstance(snapshot, object)
            self.assertEqual(snapshot.provider_identity, "DUMMY")
            self.assertEqual(len(snapshot.account_identity_fingerprint), 64)
            self.assertNotIn("account_identity", snapshot.as_dict())
            self.assertEqual(snapshot.as_dict()["cash"], "777.25")

    def test_future_schwab_adapter_satisfies_same_registry_contract(self):
        class FutureSchwabAdapter:
            provider_identity = "SCHWAB"

            def observe(self, observed_at: datetime) -> BrokerAccountSnapshot:
                return BrokerAccountSnapshot(
                    provider_identity=self.provider_identity,
                    account_identity_fingerprint="a" * 64,
                    account_status="ACTIVE",
                    cash=Decimal("4321.09"),
                    currency="USD",
                    positions=(BrokerPosition(
                        symbol="EXAMPLE",
                        side="long",
                        quantity=Decimal("2"),
                        average_entry_price=Decimal("10"),
                    ),),
                    observed_at_utc=observed_at,
                )

        selection = ProviderSelection(
            schema_version=1,
            market_data_provider="ALPACA_IEX",
            broker_account_provider="SCHWAB",
            order_execution_provider="SIMULATED",
            broker_account_configuration={"account_alias": "future"},
        )
        registry = BrokerAccountProviderRegistry()
        registry.register("SCHWAB", lambda _selection: FutureSchwabAdapter())
        provider = registry.build(selection)
        self.assertIsInstance(provider, BrokerAccountProvider)
        self.assertEqual(provider.observe(self.observed).cash, Decimal("4321.09"))
        self.assertEqual(selection.market_data_provider, "ALPACA_IEX")
        self.assertEqual(selection.order_execution_provider, "SIMULATED")

    def test_clean_v2_deployment_selects_dummy_without_sharing_strategy_runtime(self):
        config = (
            ROOT
            / "deploy/qpx-pr50-iex-forward-research-paper-clean-v2-dummy-provider.json"
        )
        selection = load_provider_selection(config)
        self.assertEqual(selection.market_data_provider, "ALPACA_IEX")
        self.assertEqual(selection.broker_account_provider, "DUMMY")
        self.assertEqual(selection.order_execution_provider, "SIMULATED")
        state_path = Path(selection.broker_account_configuration["state_path"])
        self.assertNotIn("runtime/qpx_pr50_iex", str(state_path))
        unit = (
            ROOT / "deploy/qpx-pr50-iex-forward-research-paper-clean-v2.service"
        ).read_text(encoding="utf-8")
        self.assertIn(f"Environment={BROKER_PROVIDER_CONFIG_ENV}={config}", unit)


if __name__ == "__main__":
    unittest.main()
