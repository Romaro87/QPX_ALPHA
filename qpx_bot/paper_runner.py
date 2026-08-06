"""Command-line operations for persistent QPX paper trading."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Sequence

from qpx_bot.config import BotConfig
from qpx_bot.dividends import load_dividend_csv
from qpx_bot.indicators import calculate_indicators
from qpx_bot.paper_engine import (
    create_initial_state,
    process_paper_day,
    reconcile_state,
)
from qpx_bot.paper_state import AuditEvent, StateStore
from qpx_bot.real_data import (
    align_vix_to_candles,
    load_market_csv,
    load_vix_csv,
)
from qpx_bot.run_real_backtest import (
    DEFAULT_INPUT_DIR,
    required_input_paths,
)
from qpx_bot.yahoo_data import download_real_dataset


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
DEFAULT_RUNTIME_DIR = PACKAGE_DIR / "paper_runtime"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "reports" / "qpx_paper"


def _latest_income_price(
    income_candles,
    current_date,
):
    selected = None

    for candle in income_candles:
        if candle.date > current_date:
            break
        selected = candle

    if selected is None:
        raise ValueError(
            "Income history does not cover the latest swing date."
        )

    return selected


def _status_payload(
    state,
    *,
    swing_price: float,
    income_price: float,
    journal_records: int,
    kill_switch: bool,
):
    payload = reconcile_state(
        state,
        swing_price=swing_price,
        income_price=income_price,
    )
    payload.update(
        {
            "swing_symbol": state.swing_symbol,
            "income_symbol": state.income_symbol,
            "income_shares": state.income_shares,
            "income_cost": state.income_cost,
            "journal_records": journal_records,
            "kill_switch": kill_switch,
            "mode": "SIMULATED_ONLY",
        }
    )
    return payload


def _format_status(payload) -> str:
    money = lambda value: f"${float(value):,.2f}"
    lines = [
        "=" * 76,
        "QPX BOT v1.10 — PERSISTENT PAPER ACCOUNT",
        "=" * 76,
        f"Mode                  : {payload['mode']}",
        f"State ID              : {payload['state_id']}",
        f"Revision              : {payload['revision']}",
        (
            "Last processed bar    : "
            f"{payload['last_processed_date']}"
        ),
        (
            "Kill switch           : "
            f"{'ACTIVE' if payload['kill_switch'] else 'OFF'}"
        ),
        f"Swing cash            : {money(payload['swing_cash'])}",
        (
            "Tax reserve           : "
            f"{money(payload['tax_reserve_cash'])}"
        ),
        (
            "Swing market value    : "
            f"{money(payload['swing_market_value'])}"
        ),
        (
            "Income market value   : "
            f"{money(payload['income_market_value'])}"
        ),
        f"Total paper equity    : {money(payload['total_equity'])}",
        (
            "Total contributions   : "
            f"{money(payload['total_contributions'])}"
        ),
        f"Realized P/L          : {money(payload['realized_pnl'])}",
        (
            "Dividends received    : "
            f"{money(payload['dividends_received'])}"
        ),
        f"Open swing shares     : {payload['open_shares']}",
        f"Pending entry         : {payload['pending_entry']}",
        f"Audit records         : {payload['journal_records']}",
        "=" * 76,
        "No brokerage connection. No live orders. Simulation only.",
    ]
    return "\n".join(lines)


def _write_status(
    *,
    payload,
    report_directory: Path,
) -> None:
    report_directory.mkdir(parents=True, exist_ok=True)
    text = _format_status(payload)
    (report_directory / "paper_status.txt").write_text(
        text + "\n",
        encoding="utf-8",
    )
    (report_directory / "paper_status.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def _control_event(
    event_type: str,
    reason: str,
) -> AuditEvent:
    today = datetime.now().date()
    return AuditEvent(
        event_id=(
            f"{event_type.lower()}-"
            f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        ),
        event_type=event_type,
        event_date=today,
        details={"reason": reason},
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh daily data and advance the restart-safe "
            "QPX simulated paper account."
        )
    )
    parser.add_argument(
        "--symbol",
        default=None,
        help=(
            "Explicit swing ticker. The recommended "
            "auto runner selects one without a default."
        ),
    )
    parser.add_argument(
        "--input-dir",
        default=str(DEFAULT_INPUT_DIR),
    )
    parser.add_argument(
        "--runtime-dir",
        default=str(DEFAULT_RUNTIME_DIR),
    )
    parser.add_argument(
        "--report-dir",
        default=str(DEFAULT_REPORT_DIR),
    )
    parser.add_argument(
        "--no-refresh",
        action="store_true",
        help="Use the existing downloaded CSV files.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show saved account status without advancing it.",
    )
    parser.add_argument(
        "--kill",
        action="store_true",
        help="Activate the hard paper-order kill switch.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Remove the kill switch.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = BotConfig()
    store = StateStore(args.runtime_dir)
    report_directory = Path(
        args.report_dir
    ).expanduser().resolve()

    with store.locked():
        if args.kill:
            store.activate_kill_switch("manual CLI command")
            store.append_events(
                [_control_event("KILL_SWITCH_ON", "manual")]
            )
            print("QPX paper kill switch is ACTIVE.")
            return 0

        if args.resume:
            store.deactivate_kill_switch()
            store.append_events(
                [_control_event("KILL_SWITCH_OFF", "manual")]
            )
            print("QPX paper kill switch is OFF.")
            return 0

        if store.kill_switch_active():
            print("=" * 76)
            print("QPX PAPER KILL SWITCH: ACTIVE")
            print("No refresh, signal, order, or fill was attempted.")
            print("Resume with: python QPX_RUN_PAPER.py --resume")
            print("=" * 76)
            return 4

        if args.status:
            if not store.exists():
                print("No paper state exists yet.")
                return 2

            state = store.load()
            paths = required_input_paths(args.input_dir)
            swing = load_market_csv(paths["swing"])
            income = load_market_csv(paths["income"])
            latest_swing = swing[-1]
            latest_income = _latest_income_price(
                income,
                latest_swing.date,
            )
            _, _, records = store.verify_journal()
            payload = _status_payload(
                state,
                swing_price=latest_swing.close,
                income_price=latest_income.close,
                journal_records=records,
                kill_switch=False,
            )
            _write_status(
                payload=payload,
                report_directory=report_directory,
            )
            print(_format_status(payload))
            return 0

        if not args.symbol:
            print(
                "No swing symbol was supplied. Use "
                "QPX_RUN_AUTO_PAPER.py or --symbol TICKER."
            )
            return 2

        symbol = args.symbol.strip().upper()

        input_directory = Path(
            args.input_dir
        ).expanduser().resolve()

        if not args.no_refresh:
            backup = (
                PROJECT_ROOT
                / "backups"
                / "qpx_paper_market_data"
                / datetime.now().strftime("%Y%m%d_%H%M%S")
            )
            download_real_dataset(
                swing_symbol=symbol,
                input_directory=input_directory,
                backup_directory=backup,
            )

        paths = required_input_paths(input_directory)
        missing = [
            path
            for path in paths.values()
            if not path.exists()
        ]

        if missing:
            print("Missing required paper-data files:")
            for path in missing:
                print(f"  {path}")
            return 2

        swing = load_market_csv(paths["swing"])
        income = load_market_csv(paths["income"])
        vix_points = load_vix_csv(paths["vix"])
        dividends = load_dividend_csv(paths["dividends"])
        vix_values = align_vix_to_candles(
            swing,
            vix_points,
            maximum_gap_days=7,
        )
        indicators = calculate_indicators(swing, config)

        latest_index = len(swing) - 1
        latest_swing = swing[latest_index]
        latest_income = _latest_income_price(
            income,
            latest_swing.date,
        )

        if store.exists():
            state = store.load()

            if state.swing_symbol != symbol:
                raise RuntimeError(
                    "Saved paper symbol does not match --symbol. "
                    "Use the same symbol as the existing state."
                )

            new_indices = [
                index
                for index, candle in enumerate(swing)
                if (
                    state.last_processed_date is None
                    or candle.date > state.last_processed_date
                )
            ]
        else:
            state, initialization = create_initial_state(
                swing_symbol=symbol,
                income_symbol=config.dividend_symbol,
                start_date=latest_swing.date,
                income_price=latest_income.close,
                config=config,
            )
            store.append_events([initialization])
            store.save(state)
            new_indices = [latest_index]

        if not new_indices:
            _, _, records = store.verify_journal()
            payload = _status_payload(
                state,
                swing_price=latest_swing.close,
                income_price=latest_income.close,
                journal_records=records,
                kill_switch=False,
            )
            _write_status(
                payload=payload,
                report_directory=report_directory,
            )
            print(_format_status(payload))
            print()
            print("NO NEW DAILY BAR — account state was unchanged.")
            return 0

        processed = 0

        for index in new_indices:
            events = process_paper_day(
                state=state,
                swing_candles=swing,
                income_candles=income,
                dividends=dividends,
                indicators=indicators,
                vix_values=vix_values,
                index=index,
                config=config,
            )
            store.append_events(events)
            store.save(state)
            processed += 1

        reloaded = store.load()
        _, _, records = store.verify_journal()
        final_swing = swing[
            next(
                index
                for index in range(len(swing) - 1, -1, -1)
                if swing[index].date
                <= reloaded.last_processed_date
            )
        ]
        final_income = _latest_income_price(
            income,
            final_swing.date,
        )
        payload = _status_payload(
            reloaded,
            swing_price=final_swing.close,
            income_price=final_income.close,
            journal_records=records,
            kill_switch=False,
        )
        _write_status(
            payload=payload,
            report_directory=report_directory,
        )

        print(_format_status(payload))
        print()
        print(f"New daily bars processed: {processed}")
        print("=" * 76)
        print("QPX PERSISTENT PAPER RUN: COMPLETE")
        print("=" * 76)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
