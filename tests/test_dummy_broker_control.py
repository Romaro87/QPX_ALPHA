from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from qpx_bot.broker_account_provider import load_provider_selection
from qpx_bot.dummy_broker_control import main


class DummyBrokerControlTests(unittest.TestCase):
    @staticmethod
    def config(folder: Path) -> Path:
        path = folder / "providers.json"
        path.write_text(json.dumps({
            "schema_version": 1,
            "market_data_provider": "ALPACA_IEX",
            "broker_account_provider": "DUMMY",
            "order_execution_provider": "SIMULATED",
            "broker_account_configuration": {
                "state_path": "external/account.json",
                "checksum_path": "external/account.sha256",
            },
        }), encoding="utf-8")
        return path

    @staticmethod
    def run_control(*arguments: str) -> dict:
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(list(arguments))
        if result != 0:
            raise AssertionError(f"Control returned {result}.")
        return json.loads(output.getvalue())

    def test_initialize_and_change_arbitrary_cash_and_position_without_source_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            config = self.config(folder)
            first = self.run_control(
                "--provider-config", str(config),
                "--initialize",
                "--set-account-identity", "operator-account",
                "--set-account-status", "ACTIVE",
                "--set-currency", "USD",
                "--set-cash", "321.09",
            )
            self.assertEqual(first["cash"], "321.09")
            self.assertEqual(first["positions"], [])

            second = self.run_control(
                "--provider-config", str(config),
                "--set-cash", "18.125",
                "--set-position", "ARBITRARY",
                "--side", "long",
                "--quantity", "7.5",
                "--average-entry-price", "12.25",
                "--cost-basis", "91.875",
                "--current-price", "13",
                "--market-value", "97.5",
                "--asset-class", "us_equity",
            )
            self.assertEqual(second["cash"], "18.125")
            self.assertEqual(second["positions"][0]["symbol"], "ARBITRARY")
            self.assertEqual(second["positions"][0]["quantity"], "7.5")
            self.assertEqual(second["positions"][0]["asset_class"], "us_equity")
            self.assertEqual(
                second["account_identity_fingerprint"],
                first["account_identity_fingerprint"],
            )

            third = self.run_control(
                "--provider-config", str(config),
                "--set-cash", "875.50",
                "--clear-positions",
            )
            self.assertEqual(third["cash"], "875.5")
            self.assertEqual(third["positions"], [])
            self.assertEqual(
                third["account_identity_fingerprint"],
                first["account_identity_fingerprint"],
            )

    def test_malformed_change_fails_before_publishing_new_state_or_checksum(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            config = self.config(folder)
            self.run_control(
                "--provider-config", str(config),
                "--initialize",
                "--set-account-identity", "stable-account",
                "--set-account-status", "ACTIVE",
                "--set-currency", "USD",
                "--set-cash", "25",
            )
            selection = load_provider_selection(config)
            state = Path(selection.broker_account_configuration["state_path"])
            if not state.is_absolute():
                state = config.parent / state
            checksum = Path(selection.broker_account_configuration["checksum_path"])
            if not checksum.is_absolute():
                checksum = config.parent / checksum
            state_before = state.read_bytes()
            checksum_before = checksum.read_bytes()
            with self.assertRaisesRegex(ValueError, "quantity"):
                self.run_control(
                    "--provider-config", str(config),
                    "--set-position", "BROKEN",
                    "--side", "long",
                    "--quantity", "not-a-number",
                    "--average-entry-price", "10",
                )
            self.assertEqual(state.read_bytes(), state_before)
            self.assertEqual(checksum.read_bytes(), checksum_before)

    def test_status_is_read_only_and_does_not_expose_raw_account_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            config = self.config(folder)
            self.run_control(
                "--provider-config", str(config),
                "--initialize",
                "--set-account-identity", "private-dummy-name",
                "--set-account-status", "ACTIVE",
                "--set-currency", "USD",
                "--set-cash", "10",
            )
            status = self.run_control(
                "--provider-config", str(config),
                "--status",
            )
            self.assertEqual(status["status"], "DUMMY_BROKER_ACCOUNT_VALID")
            self.assertNotIn("account_identity", status)
            self.assertEqual(len(status["account_identity_fingerprint"]), 64)

    def test_requested_intervention_is_valid_atomic_external_change_only(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            config = self.config(folder)
            self.run_control(
                "--provider-config", str(config),
                "--initialize",
                "--set-account-identity", "intervention-test",
                "--set-account-status", "ACTIVE",
                "--set-currency", "USD",
                "--set-cash", "17",
            )
            result = self.run_control(
                "--provider-config", str(config),
                "--set-cash", "1400.00",
                "--clear-positions",
            )
            self.assertEqual(result["cash"], "1400")
            self.assertEqual(result["positions"], [])
            self.assertEqual(result["mutation"]["before"]["cash"], "17")
            self.assertEqual(result["mutation"]["after"]["cash"], "1400")
            self.assertEqual(result["mutation"]["after"]["positions"], [])
            self.assertTrue(result["mutation"]["executed_at_utc"].endswith("+00:00"))
            self.assertNotIn("runtime", result["state_path"])

    def test_dated_one_shot_units_are_exact_and_do_not_touch_qpx_runtime(self):
        root = Path(__file__).resolve().parents[1]
        service = (
            root / "deploy/qpx-clean-v2-dummy-intervention-20260903.service"
        ).read_text(encoding="utf-8")
        timer = (
            root / "deploy/qpx-clean-v2-dummy-intervention-20260903.timer"
        ).read_text(encoding="utf-8")
        expected = (
            "/usr/bin/python3 -u /home/ron/QPX_ALPHA/"
            "QPX_CONTROL_DUMMY_BROKER_ACCOUNT.py --provider-config "
            "/home/ron/QPX_ALPHA/deploy/"
            "qpx-pr50-iex-forward-research-paper-clean-v2-dummy-provider.json "
            "--set-cash 1400.00 --clear-positions"
        )
        self.assertIn("Type=oneshot", service)
        self.assertIn("ExecStart=" + expected, service)
        self.assertNotIn("QPX_RUN_PR50", service)
        self.assertNotIn("systemctl", service)
        self.assertIn("OnCalendar=2026-09-03 11:00:00 America/New_York", timer)
        self.assertIn("AccuracySec=1s", timer)
        self.assertIn("Persistent=false", timer)
        self.assertIn(
            "Unit=qpx-clean-v2-dummy-intervention-20260903.service",
            timer,
        )


if __name__ == "__main__":
    unittest.main()
