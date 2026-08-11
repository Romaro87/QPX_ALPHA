from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from qpx_bot.causal_dividends import (
    CausalDividendEvent,
    CausalDividendLedger,
    IncompleteDividendMetadata,
    load_causal_dividends,
)


class CausalDividendTests(unittest.TestCase):
    def event(
        self,
        *,
        payable: date | None = date(2025, 1, 10),
        process: date | None = date(2025, 1, 13),
    ) -> CausalDividendEvent:
        return CausalDividendEvent(
            event_id="event-1",
            ex_date=date(2025, 1, 6),
            record_date=date(2025, 1, 6),
            payable_date=payable,
            process_date=process,
            cash_amount=0.25,
        )

    def test_entitlement_uses_shares_owned_on_ex_date(self) -> None:
        ledger = CausalDividendLedger([self.event()])
        self.assertEqual(
            ledger.process_open(
                current_date=date(2025, 1, 6),
                income_shares=100.0,
            ),
            0.0,
        )
        self.assertEqual(ledger.entitlement_count, 1)
        self.assertEqual(
            ledger.process_open(
                current_date=date(2025, 1, 13),
                income_shares=5.0,
            ),
            25.0,
        )

    def test_cash_is_not_available_on_ex_or_payable_date_before_process(self) -> None:
        ledger = CausalDividendLedger([self.event()])
        self.assertEqual(
            ledger.process_open(
                current_date=date(2025, 1, 6),
                income_shares=100.0,
            ),
            0.0,
        )
        self.assertEqual(
            ledger.process_open(
                current_date=date(2025, 1, 10),
                income_shares=100.0,
            ),
            0.0,
        )
        self.assertEqual(
            ledger.process_open(
                current_date=date(2025, 1, 13),
                income_shares=100.0,
            ),
            25.0,
        )
        self.assertEqual(
            ledger.process_open(
                current_date=date(2025, 1, 14),
                income_shares=100.0,
            ),
            0.0,
        )

    def test_first_market_open_after_non_trading_settlement_receives_cash(self) -> None:
        event = self.event(
            payable=date(2025, 1, 11),
            process=None,
        )
        ledger = CausalDividendLedger([event])
        ledger.process_open(
            current_date=date(2025, 1, 6),
            income_shares=8.0,
        )
        self.assertEqual(
            ledger.process_open(
                current_date=date(2025, 1, 13),
                income_shares=8.0,
            ),
            2.0,
        )

    def test_no_lookahead_entitlement_before_ex_date(self) -> None:
        ledger = CausalDividendLedger([self.event()])
        self.assertEqual(
            ledger.process_open(
                current_date=date(2025, 1, 3),
                income_shares=100.0,
            ),
            0.0,
        )
        self.assertEqual(ledger.entitlement_count, 0)
        self.assertEqual(
            ledger.process_open(
                current_date=date(2025, 1, 13),
                income_shares=100.0,
            ),
            0.0,
        )

    def test_incomplete_settlement_metadata_fails_closed(self) -> None:
        with self.assertRaises(IncompleteDividendMetadata):
            CausalDividendLedger([
                self.event(payable=None, process=None)
            ])

    def test_loader_preserves_all_corporate_action_dates(self) -> None:
        contents = (
            "EventId,ExDividendDate,RecordDate,PayableDate,"
            "ProcessDate,CashAmount\n"
            "event-1,2025-01-06,2025-01-06,2025-01-10,"
            "2025-01-13,0.25\n"
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "dividends.csv"
            path.write_text(contents, encoding="utf-8")
            event = load_causal_dividends(path)[0]
        self.assertEqual(event.ex_date, date(2025, 1, 6))
        self.assertEqual(event.record_date, date(2025, 1, 6))
        self.assertEqual(event.payable_date, date(2025, 1, 10))
        self.assertEqual(event.process_date, date(2025, 1, 13))
        self.assertEqual(event.cash_available_date, date(2025, 1, 13))

    def test_legacy_three_column_cache_is_rejected_for_strict_replay(self) -> None:
        contents = (
            "EventId,ExDividendDate,CashAmount\n"
            "event-1,2025-01-06,0.25\n"
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "dividends.csv"
            path.write_text(contents, encoding="utf-8")
            with self.assertRaises(IncompleteDividendMetadata):
                load_causal_dividends(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
