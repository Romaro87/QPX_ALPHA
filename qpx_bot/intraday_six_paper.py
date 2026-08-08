"""Restart-safe configurable-symbol 15-minute paper engine."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date, datetime, time as clock_time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from qpx_bot.allocation import rebalance_income_allocation
from qpx_bot.config import BotConfig
from qpx_bot.data_loader import Candle
from qpx_bot.indicators import calculate_indicators
from qpx_bot.market_calendar import NEW_YORK, is_market_session
from qpx_bot.paper_state import StateStore
from qpx_bot.portfolio import ClosedTrade, Portfolio, Position, contribution_allocation
from qpx_bot.risk import buy_fill, calculate_position_size
from qpx_bot.strategy import evaluate_entry, evaluate_exit
from qpx_bot.symbol_config import load_symbol_config
from qpx_bot.time_rules import elapsed_complete_years
from qpx_bot.yahoo_data import YAHOO_HOSTS


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
DEFAULT_POLICY = PACKAGE_DIR / "intraday_six_policy.json"
DEFAULT_RUNTIME = PACKAGE_DIR / "intraday_six_runtime"
DEFAULT_LEGACY_RUNTIME = PACKAGE_DIR / "paper_runtime"
DEFAULT_REPORTS = PROJECT_ROOT / "reports" / "qpx_intraday_six"
STATE_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class IntradayPolicy:
    schema_version: int
    interval: str
    history_range: str
    market_timezone: str
    regular_session_open: str
    first_scan_time: str
    regular_session_close: str
    maximum_concurrent_positions: int
    maximum_gap_atr_multiple: float
    candidates: tuple[str, ...]
    tradable_symbols: tuple[str, ...]
    income_symbol: str
    volatility_symbol: str
    rankings_enabled: bool
    signal_evaluation: str
    signal_execution: str
    simultaneous_signal_tiebreak: str
    extended_hours_enabled: bool
    live_broker_enabled: bool

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError("Unsupported intraday policy schema.")

        if self.interval != "15m":
            raise ValueError("The active paper interval must be 15m.")

        if self.history_range != "60d":
            raise ValueError("The 15-minute history range must be 60d.")

        if self.market_timezone != "America/New_York":
            raise ValueError("The market timezone must be America/New_York.")

        if self.maximum_concurrent_positions <= 0:
            raise ValueError(
                "Maximum concurrent positions must be positive."
            )

        if (
            not self.candidates
            or len(set(self.candidates)) != len(self.candidates)
        ):
            raise ValueError(
                "Candidate symbols must be non-empty and unique."
            )

        if (
            not self.tradable_symbols
            or len(set(self.tradable_symbols))
            != len(self.tradable_symbols)
        ):
            raise ValueError(
                "Tradable symbols must be non-empty and unique."
            )

        if not set(self.tradable_symbols).issubset(
            self.candidates
        ):
            raise ValueError(
                "Every tradable symbol must also be a candidate."
            )

        if not self.income_symbol.strip():
            raise ValueError("Income symbol cannot be empty.")

        if not self.volatility_symbol.strip():
            raise ValueError("Volatility symbol cannot be empty.")

        if self.rankings_enabled:
            raise ValueError("Rankings must remain disabled.")

        if self.signal_evaluation != "all_candidates_each_completed_15m_bar":
            raise ValueError("All configured candidates must be evaluated each bar.")

        if self.signal_execution != "next_completed_15m_bar_open":
            raise ValueError("Signals must execute at the next 15-minute open.")

        if (
            self.simultaneous_signal_tiebreak
            != "sha256_of_signal_bar_and_symbol"
        ):
            raise ValueError("Unexpected simultaneous-signal tie-break.")

        if self.maximum_gap_atr_multiple <= 0:
            raise ValueError("The opening-gap limit must be positive.")

        if self.extended_hours_enabled:
            raise ValueError("Extended-hours scanning is prohibited.")

        if self.live_broker_enabled:
            raise ValueError("Live brokerage must remain disabled.")


@dataclass(frozen=True, slots=True)
class IntradayBar:
    start: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True, slots=True)
class PendingSignal:
    symbol: str
    signal_bar: str
    signal_atr: float
    prior_close: float
    tie_key: str


@dataclass(slots=True)
class PaperAccount:
    account_id: str
    start_date: date
    starting_total_capital: float
    swing_cash: float
    tax_reserve_cash: float
    total_contributions: float
    realized_pnl: float
    income_shares: float
    income_cost: float
    dividends_received: float
    last_contribution_month: str | None
    last_allocation_years: int
    last_processed_bar: str | None
    processed_dividend_keys: list[str]
    positions: dict[str, Position]
    pending: dict[str, PendingSignal]
    closed_trades: list[ClosedTrade]
    trade_results_r: list[float]
    revision: int = 0
    schema_version: int = STATE_SCHEMA_VERSION

    def validate(
        self,
        policy: IntradayPolicy,
    ) -> None:
        if self.schema_version != STATE_SCHEMA_VERSION:
            raise ValueError("Unsupported 15-minute state schema.")

        if not self.account_id.strip():
            raise ValueError("Account ID cannot be empty.")

        if len(self.positions) > policy.maximum_concurrent_positions:
            raise ValueError("Open-position count exceeds the six-slot limit.")

        if (
            len(self.positions)
            + len(self.pending)
            > policy.maximum_concurrent_positions
        ):
            raise ValueError("Positions plus pending entries exceed six slots.")

        if set(self.positions).intersection(self.pending):
            raise ValueError("A symbol cannot be both open and pending.")

        if any(value < -1e-9 for value in (
            self.starting_total_capital,
            self.swing_cash,
            self.tax_reserve_cash,
            self.total_contributions,
            self.income_shares,
            self.income_cost,
            self.dividends_received,
        )):
            raise ValueError("Paper-account balances cannot be negative.")

        if self.last_allocation_years < 0 or self.revision < 0:
            raise ValueError("Paper-account counters cannot be negative.")


def load_policy(
    filename: str | Path = DEFAULT_POLICY,
) -> IntradayPolicy:
    payload = json.loads(
        Path(filename).read_text(encoding="utf-8")
    )
    symbols = load_symbol_config()
    policy = IntradayPolicy(
        schema_version=int(payload["schema_version"]),
        interval=str(payload["interval"]),
        history_range=str(payload["history_range"]),
        market_timezone=str(payload["market_timezone"]),
        regular_session_open=str(payload["regular_session_open"]),
        first_scan_time=str(payload["first_scan_time"]),
        regular_session_close=str(payload["regular_session_close"]),
        maximum_concurrent_positions=int(
            payload["maximum_concurrent_positions"]
        ),
        maximum_gap_atr_multiple=float(
            payload["maximum_gap_atr_multiple"]
        ),
        candidates=symbols.candidate_symbols,
        tradable_symbols=symbols.tradable_symbols,
        income_symbol=symbols.income_symbol,
        volatility_symbol=symbols.volatility_symbol,
        rankings_enabled=bool(payload["rankings_enabled"]),
        signal_evaluation=str(payload["signal_evaluation"]),
        signal_execution=str(payload["signal_execution"]),
        simultaneous_signal_tiebreak=str(
            payload["simultaneous_signal_tiebreak"]
        ),
        extended_hours_enabled=bool(
            payload["extended_hours_enabled"]
        ),
        live_broker_enabled=bool(
            payload["live_broker_enabled"]
        ),
    )
    policy.validate()
    return policy


def _parse_clock(value: str) -> clock_time:
    hour, minute = value.split(":", 1)
    return clock_time(int(hour), int(minute))


def scan_window_open(
    now_market: datetime,
    policy: IntradayPolicy,
) -> bool:
    local = now_market.astimezone(NEW_YORK)
    wall = local.time().replace(tzinfo=None)

    return (
        is_market_session(local.date())
        and _parse_clock(policy.first_scan_time)
        <= wall
        <= _parse_clock(policy.regular_session_close)
    )


def _chart_url(
    host: str,
    symbol: str,
    *,
    interval: str,
    range_name: str,
) -> str:
    encoded = urllib.parse.quote(symbol, safe="")
    query = urllib.parse.urlencode(
        {
            "range": range_name,
            "interval": interval,
            "events": "div,splits",
            "includePrePost": "false",
            "includeAdjustedClose": "true",
        }
    )
    return (
        f"https://{host}/v8/finance/chart/"
        f"{encoded}?{query}"
    )


def _open_json(
    url: str,
    *,
    timeout_seconds: float = 20.0,
) -> Mapping[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 14) "
                "AppleWebKit/537.36 QPXBot/1.22"
            ),
            "Accept": "application/json,text/plain,*/*",
            "Accept-Encoding": "identity",
            "Connection": "close",
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=timeout_seconds,
    ) as response:
        payload = json.loads(
            response.read().decode("utf-8")
        )

    chart = payload.get("chart")

    if not isinstance(chart, Mapping) or chart.get("error"):
        raise RuntimeError("Yahoo chart response is invalid.")

    results = chart.get("result")

    if not isinstance(results, list) or not results:
        raise RuntimeError("Yahoo chart result is empty.")

    result = results[0]

    if not isinstance(result, Mapping):
        raise RuntimeError("Yahoo chart result is malformed.")

    return result


def fetch_intraday(
    symbol: str,
    policy: IntradayPolicy,
    *,
    now_market: datetime,
) -> list[IntradayBar]:
    last_error: Exception | None = None

    for host in YAHOO_HOSTS:
        try:
            result = _open_json(
                _chart_url(
                    host,
                    symbol,
                    interval=policy.interval,
                    range_name=policy.history_range,
                )
            )
            timestamps = result.get("timestamp")
            indicators = result.get("indicators")
            quotes = (
                indicators.get("quote")
                if isinstance(indicators, Mapping)
                else None
            )

            if (
                not isinstance(timestamps, list)
                or not isinstance(quotes, list)
                or not quotes
                or not isinstance(quotes[0], Mapping)
            ):
                raise RuntimeError(
                    f"Intraday arrays are missing for {symbol}."
                )

            quote = quotes[0]
            opens = quote.get("open")
            highs = quote.get("high")
            lows = quote.get("low")
            closes = quote.get("close")
            volumes = quote.get("volume")

            arrays = (
                timestamps,
                opens,
                highs,
                lows,
                closes,
                volumes,
            )

            if not all(isinstance(value, list) for value in arrays):
                raise RuntimeError(
                    f"Intraday arrays are incomplete for {symbol}."
                )

            bars: list[IntradayBar] = []
            session_open = _parse_clock(policy.regular_session_open)
            session_close = _parse_clock(policy.regular_session_close)
            now_local = now_market.astimezone(NEW_YORK)

            for index, raw_timestamp in enumerate(timestamps):
                try:
                    start = datetime.fromtimestamp(
                        int(raw_timestamp),
                        tz=timezone.utc,
                    ).astimezone(NEW_YORK)
                    values = (
                        float(opens[index]),
                        float(highs[index]),
                        float(lows[index]),
                        float(closes[index]),
                    )
                    volume = int(volumes[index] or 0)
                except (TypeError, ValueError, IndexError):
                    continue

                if not all(
                    math.isfinite(value) and value > 0
                    for value in values
                ):
                    continue

                wall = start.time().replace(tzinfo=None)

                if not (
                    session_open <= wall < session_close
                    and is_market_session(start.date())
                ):
                    continue

                if (
                    start + timedelta(minutes=15)
                    > now_local
                ):
                    continue

                bars.append(
                    IntradayBar(
                        start=start,
                        open=values[0],
                        high=values[1],
                        low=values[2],
                        close=values[3],
                        volume=max(0, volume),
                    )
                )

            deduplicated = {
                bar.start.isoformat(): bar
                for bar in bars
            }
            result_bars = sorted(
                deduplicated.values(),
                key=lambda bar: bar.start,
            )

            if len(result_bars) < 220:
                raise RuntimeError(
                    f"Only {len(result_bars)} completed "
                    f"15-minute bars were returned for {symbol}."
                )

            return result_bars
        except (
            OSError,
            RuntimeError,
            urllib.error.URLError,
            json.JSONDecodeError,
        ) as exc:
            last_error = exc

    raise RuntimeError(
        f"Unable to download valid 15-minute data for {symbol}: "
        f"{last_error}"
    )


def fetch_income_dividends(income_symbol: str) -> list[tuple[str, date, float]]:
    last_error: Exception | None = None

    for host in YAHOO_HOSTS:
        try:
            result = _open_json(
                _chart_url(
                    host,
                    income_symbol,
                    interval="1d",
                    range_name="1y",
                )
            )
            events = result.get("events")
            dividends = (
                events.get("dividends")
                if isinstance(events, Mapping)
                else None
            )

            if not isinstance(dividends, Mapping):
                return []

            rows: list[tuple[str, date, float]] = []

            for key, raw in dividends.items():
                if not isinstance(raw, Mapping):
                    continue

                amount = float(raw.get("amount", 0.0))
                raw_date = raw.get("date")

                if amount <= 0 or raw_date is None:
                    continue

                event_date = datetime.fromtimestamp(
                    int(raw_date),
                    tz=timezone.utc,
                ).date()
                rows.append(
                    (
                        str(key),
                        event_date,
                        amount,
                    )
                )

            return sorted(rows, key=lambda item: item[1])
        except (
            OSError,
            RuntimeError,
            urllib.error.URLError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ) as exc:
            last_error = exc

    raise RuntimeError(
        f"Unable to download income-symbol dividends: {last_error}"
    )


def common_completed_times(
    histories: Mapping[str, Sequence[IntradayBar]],
) -> list[datetime]:
    common: set[datetime] | None = None

    for bars in histories.values():
        times = {bar.start for bar in bars}
        common = times if common is None else common.intersection(times)

    return sorted(common or set())


def choose_without_ranking(
    *,
    signal_bar: datetime,
    qualifying: Sequence[str],
    available_slots: int,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if available_slots < 0:
        raise ValueError("Available slots cannot be negative.")

    ordered = sorted(
        {
            symbol.strip().upper()
            for symbol in qualifying
            if symbol.strip()
        },
        key=lambda symbol: (
            hashlib.sha256(
                (
                    signal_bar.isoformat()
                    + "|"
                    + symbol
                ).encode("utf-8")
            ).hexdigest(),
            symbol,
        ),
    )
    return (
        tuple(ordered[:available_slots]),
        tuple(ordered[available_slots:]),
    )


def _position_to_dict(position: Position) -> dict[str, Any]:
    payload = asdict(position)
    payload["entry_date"] = position.entry_date.isoformat()
    return payload


def _position_from_dict(payload: Mapping[str, Any]) -> Position:
    return Position(
        symbol=str(payload["symbol"]),
        shares=int(payload["shares"]),
        entry_date=date.fromisoformat(str(payload["entry_date"])),
        entry_price=float(payload["entry_price"]),
        entry_atr=float(payload["entry_atr"]),
        stop_price=float(payload["stop_price"]),
        target_price=float(payload["target_price"]),
        highest_price=float(payload["highest_price"]),
    )


def _trade_to_dict(trade: ClosedTrade) -> dict[str, Any]:
    payload = asdict(trade)
    payload["entry_date"] = trade.entry_date.isoformat()
    payload["exit_date"] = trade.exit_date.isoformat()
    return payload


def _trade_from_dict(payload: Mapping[str, Any]) -> ClosedTrade:
    return ClosedTrade(
        symbol=str(payload["symbol"]),
        entry_date=date.fromisoformat(str(payload["entry_date"])),
        exit_date=date.fromisoformat(str(payload["exit_date"])),
        shares=int(payload["shares"]),
        entry_price=float(payload["entry_price"]),
        exit_price=float(payload["exit_price"]),
        pnl=float(payload["pnl"]),
        tax_reserved=float(payload["tax_reserved"]),
        reason=str(payload["reason"]),
        result_r=float(payload["result_r"]),
    )


def account_to_dict(account: PaperAccount) -> dict[str, Any]:
    return {
        "schema_version": account.schema_version,
        "account_id": account.account_id,
        "start_date": account.start_date.isoformat(),
        "starting_total_capital": account.starting_total_capital,
        "swing_cash": account.swing_cash,
        "tax_reserve_cash": account.tax_reserve_cash,
        "total_contributions": account.total_contributions,
        "realized_pnl": account.realized_pnl,
        "income_shares": account.income_shares,
        "income_cost": account.income_cost,
        "dividends_received": account.dividends_received,
        "last_contribution_month": account.last_contribution_month,
        "last_allocation_years": account.last_allocation_years,
        "last_processed_bar": account.last_processed_bar,
        "processed_dividend_keys": list(
            account.processed_dividend_keys
        ),
        "positions": {
            symbol: _position_to_dict(position)
            for symbol, position in account.positions.items()
        },
        "pending": {
            symbol: asdict(signal)
            for symbol, signal in account.pending.items()
        },
        "closed_trades": [
            _trade_to_dict(trade)
            for trade in account.closed_trades[-500:]
        ],
        "trade_results_r": list(account.trade_results_r[-500:]),
        "revision": account.revision,
    }


def account_from_dict(payload: Mapping[str, Any]) -> PaperAccount:
    return PaperAccount(
        schema_version=int(
            payload.get(
                "schema_version",
                STATE_SCHEMA_VERSION,
            )
        ),
        account_id=str(payload["account_id"]),
        start_date=date.fromisoformat(str(payload["start_date"])),
        starting_total_capital=float(
            payload["starting_total_capital"]
        ),
        swing_cash=float(payload["swing_cash"]),
        tax_reserve_cash=float(payload["tax_reserve_cash"]),
        total_contributions=float(payload["total_contributions"]),
        realized_pnl=float(payload["realized_pnl"]),
        income_shares=float(payload["income_shares"]),
        income_cost=float(payload["income_cost"]),
        dividends_received=float(payload["dividends_received"]),
        last_contribution_month=(
            str(payload["last_contribution_month"])
            if payload.get("last_contribution_month")
            else None
        ),
        last_allocation_years=int(
            payload.get("last_allocation_years", 0)
        ),
        last_processed_bar=(
            str(payload["last_processed_bar"])
            if payload.get("last_processed_bar")
            else None
        ),
        processed_dividend_keys=[
            str(value)
            for value in payload.get(
                "processed_dividend_keys",
                [],
            )
        ],
        positions={
            str(symbol): _position_from_dict(raw)
            for symbol, raw in dict(
                payload.get("positions", {})
            ).items()
        },
        pending={
            str(symbol): PendingSignal(
                symbol=str(raw["symbol"]),
                signal_bar=str(raw["signal_bar"]),
                signal_atr=float(raw["signal_atr"]),
                prior_close=float(raw["prior_close"]),
                tie_key=str(raw["tie_key"]),
            )
            for symbol, raw in dict(
                payload.get("pending", {})
            ).items()
        },
        closed_trades=[
            _trade_from_dict(raw)
            for raw in payload.get("closed_trades", [])
        ],
        trade_results_r=[
            float(value)
            for value in payload.get("trade_results_r", [])
        ],
        revision=int(payload.get("revision", 0)),
    )


class AccountStore:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory).expanduser().resolve()
        self.state_path = self.directory / "paper_state.json"
        self.checksum_path = self.directory / "paper_state.sha256"
        self.audit_path = self.directory / "paper_audit.jsonl"
        self.lock_path = self.directory / "paper.lock"

    def exists(self) -> bool:
        return self.state_path.exists()

    @contextmanager
    def locked(self) -> Iterator[None]:
        self.directory.mkdir(parents=True, exist_ok=True)
        descriptor: int | None = None

        for _ in range(120):
            try:
                descriptor = os.open(
                    self.lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                os.write(
                    descriptor,
                    (
                        f"{os.getpid()}|"
                        f"{datetime.now(timezone.utc).isoformat()}"
                    ).encode("utf-8"),
                )
                break
            except FileExistsError:
                time.sleep(0.25)

        if descriptor is None:
            raise RuntimeError(
                "The 15-minute paper runtime is already locked."
            )

        try:
            yield
        finally:
            os.close(descriptor)
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass

    def save(
        self,
        account: PaperAccount,
        policy: IntradayPolicy,
    ) -> None:
        account.validate(policy)
        encoded = (
            json.dumps(
                account_to_dict(account),
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        checksum = hashlib.sha256(encoded).hexdigest()
        state_temp = self.state_path.with_suffix(".json.tmp")
        checksum_temp = self.checksum_path.with_suffix(".sha256.tmp")
        state_temp.write_bytes(encoded)
        checksum_temp.write_text(
            checksum + "\n",
            encoding="utf-8",
        )
        state_temp.replace(self.state_path)
        checksum_temp.replace(self.checksum_path)

    def load(
        self,
        policy: IntradayPolicy,
    ) -> PaperAccount:
        encoded = self.state_path.read_bytes()
        expected = self.checksum_path.read_text(
            encoding="utf-8"
        ).strip()
        actual = hashlib.sha256(encoded).hexdigest()

        if actual != expected:
            raise RuntimeError(
                "The 15-minute paper-state checksum is invalid."
            )

        account = account_from_dict(
            json.loads(encoded.decode("utf-8"))
        )
        account.validate(policy)
        return account

    def event(
        self,
        event_type: str,
        bar_time: datetime,
        details: Mapping[str, Any],
    ) -> None:
        record = {
            "timestamp_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "event_type": event_type,
            "bar_time_market": bar_time.isoformat(),
            "details": dict(details),
        }

        with self.audit_path.open(
            "a",
            encoding="utf-8",
        ) as file:
            file.write(
                json.dumps(
                    record,
                    sort_keys=True,
                )
                + "\n"
            )


def _portfolio(account: PaperAccount) -> Portfolio:
    portfolio = Portfolio(0.0)
    portfolio.cash = account.swing_cash
    portfolio.tax_reserve_cash = account.tax_reserve_cash
    portfolio.total_contributions = account.total_contributions
    portfolio.realized_pnl = account.realized_pnl
    portfolio.positions = {
        symbol: position
        for symbol, position in account.positions.items()
    }
    portfolio.closed_trades = list(account.closed_trades)
    return portfolio


def _sync(
    account: PaperAccount,
    portfolio: Portfolio,
) -> None:
    account.swing_cash = portfolio.cash
    account.tax_reserve_cash = portfolio.tax_reserve_cash
    account.realized_pnl = portfolio.realized_pnl
    account.positions = {
        symbol: position
        for symbol, position in portfolio.positions.items()
    }
    account.closed_trades = list(portfolio.closed_trades[-500:])
    account.trade_results_r = [
        trade.result_r
        for trade in account.closed_trades[-500:]
    ]


def _fresh_account(
    *,
    income_price: float,
    first_bar: datetime,
    config: BotConfig,
) -> PaperAccount:
    fill = buy_fill(
        income_price,
        config.slippage_rate,
    )
    income_shares = config.starting_cash / fill
    account_id = (
        "qpx-15m-"
        + hashlib.sha256(
            first_bar.isoformat().encode("utf-8")
        ).hexdigest()[:20]
    )
    account = PaperAccount(
        account_id=account_id,
        start_date=first_bar.date(),
        starting_total_capital=config.total_starting_capital,
        swing_cash=config.starting_swing_cash,
        tax_reserve_cash=0.0,
        total_contributions=config.total_starting_capital,
        realized_pnl=0.0,
        income_shares=income_shares,
        income_cost=config.starting_cash,
        dividends_received=0.0,
        last_contribution_month=(
            f"{first_bar.year:04d}-{first_bar.month:02d}"
        ),
        last_allocation_years=0,
        last_processed_bar=None,
        processed_dividend_keys=[],
        positions={},
        pending={},
        closed_trades=[],
        trade_results_r=[],
    )
    _rebalance(
        account=account,
        portfolio=_portfolio(account),
        income_price=income_price,
        position_prices={},
        target_income_weight=(
            config.dividend_allocation_years_1_2
        ),
        config=config,
    )
    return account


def _migrate_legacy(
    *,
    legacy_directory: Path,
    latest_bar: datetime,
    policy: IntradayPolicy,
) -> PaperAccount | None:
    legacy = StateStore(legacy_directory)

    if not legacy.exists():
        return None

    with legacy.locked():
        state = legacy.load()

    positions: dict[str, Position] = {}

    if state.position is not None:
        position = state.position
        positions[position.symbol] = Position(
            symbol=position.symbol,
            shares=position.shares,
            entry_date=position.entry_date,
            entry_price=position.entry_price,
            entry_atr=position.entry_atr,
            stop_price=position.stop_price,
            target_price=position.target_price,
            highest_price=position.highest_price,
        )

    account = PaperAccount(
        account_id=(
            state.state_id
            + "-15m6"
        ),
        start_date=state.start_date,
        starting_total_capital=state.starting_cash,
        swing_cash=state.swing_cash,
        tax_reserve_cash=state.tax_reserve_cash,
        total_contributions=state.total_contributions,
        realized_pnl=state.realized_pnl,
        income_shares=state.income_shares,
        income_cost=state.income_cost,
        dividends_received=state.dividends_received,
        last_contribution_month=state.last_contribution_month,
        last_allocation_years=elapsed_complete_years(
            state.start_date,
            latest_bar.date(),
        ),
        last_processed_bar=None,
        processed_dividend_keys=list(
            state.processed_dividend_keys
        ),
        positions=positions,
        pending={},
        closed_trades=[],
        trade_results_r=list(state.trade_results_r),
        revision=state.revision,
    )
    account.validate(policy)
    return account


def _rebalance(
    *,
    account: PaperAccount,
    portfolio: Portfolio,
    income_price: float,
    position_prices: Mapping[str, float],
    target_income_weight: float,
    config: BotConfig,
) -> None:
    swing_market_value = portfolio.market_value(
        position_prices
    )
    result = rebalance_income_allocation(
        income_shares=account.income_shares,
        income_cost=account.income_cost,
        swing_cash=portfolio.cash,
        swing_market_value=swing_market_value,
        income_price=income_price,
        target_income_weight=target_income_weight,
        slippage_rate=config.slippage_rate,
        tax_reserve_rate=config.annual_tax_reserve_rate,
        tolerance=config.allocation_rebalance_tolerance,
        minimum_trade=config.minimum_rebalance_trade,
    )
    account.income_shares = result.shares_after
    account.income_cost = result.income_cost_after
    portfolio.cash = result.swing_cash_after
    portfolio.tax_reserve_cash += result.tax_reserved
    portfolio.realized_pnl += result.realized_pnl
    _sync(account, portfolio)


def _bar_maps(
    histories: Mapping[str, Sequence[IntradayBar]],
) -> dict[str, dict[datetime, IntradayBar]]:
    return {
        symbol: {
            bar.start: bar
            for bar in bars
        }
        for symbol, bars in histories.items()
    }


def _candles(
    histories: Mapping[str, Sequence[IntradayBar]],
) -> dict[str, list[Candle]]:
    return {
        symbol: [
            Candle(
                date=bar.start.date(),
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
            )
            for bar in bars
        ]
        for symbol, bars in histories.items()
    }


def run_cycle(
    *,
    now_market: datetime | None = None,
    policy_path: str | Path = DEFAULT_POLICY,
    runtime_directory: str | Path = DEFAULT_RUNTIME,
    legacy_runtime_directory: str | Path = DEFAULT_LEGACY_RUNTIME,
    report_directory: str | Path = DEFAULT_REPORTS,
) -> dict[str, Any]:
    policy = load_policy(policy_path)
    config = BotConfig()
    config.validate()

    if (
        config.maximum_swing_positions
        < policy.maximum_concurrent_positions
    ):
        raise RuntimeError(
            "BotConfig maximum_swing_positions is below "
            "the active policy maximum."
        )

    now_market = (
        now_market.astimezone(NEW_YORK)
        if now_market is not None
        else datetime.now(tz=NEW_YORK)
    )

    if not scan_window_open(now_market, policy):
        return {
            "status": "OUTSIDE_REGULAR_SCAN_WINDOW",
            "market_time": now_market.isoformat(),
            "rankings_enabled": False,
            "maximum_positions": policy.maximum_concurrent_positions,
            "live_broker_enabled": False,
        }

    symbols = tuple(
        dict.fromkeys(
            (
                *policy.candidates,
                policy.income_symbol,
                policy.volatility_symbol,
            )
        )
    )
    histories = {
        symbol: fetch_intraday(
            symbol,
            policy,
            now_market=now_market,
        )
        for symbol in symbols
    }
    common_times = common_completed_times(histories)

    if not common_times:
        raise RuntimeError(
            "The configured intraday histories have no common bar."
        )

    maps = _bar_maps(histories)
    latest = common_times[-1]
    store = AccountStore(runtime_directory)
    report_dir = Path(report_directory).expanduser().resolve()
    report_dir.mkdir(parents=True, exist_ok=True)

    with store.locked():
        if store.exists():
            account = store.load(policy)
            initialized = False
            migration = "EXISTING_15M_STATE"
        else:
            account = _migrate_legacy(
                legacy_directory=Path(
                    legacy_runtime_directory
                ).expanduser().resolve(),
                latest_bar=latest,
                policy=policy,
            )
            migration = "LEGACY_STATE_SNAPSHOT"

            if account is None:
                account = _fresh_account(
                    income_price=maps[policy.income_symbol][latest].close,
                    first_bar=latest,
                    config=config,
                )
                migration = "FRESH_15M_ACCOUNT"

            initialized = True
            account.last_processed_bar = (
                common_times[-2].isoformat()
                if len(common_times) >= 2
                else latest.isoformat()
            )
            store.event(
                "ACCOUNT_INITIALIZED",
                latest,
                {
                    "source": migration,
                    "legacy_state_unchanged": True,
                    "maximum_positions": policy.maximum_concurrent_positions,
                    "rankings_enabled": False,
                },
            )

        last_processed = (
            datetime.fromisoformat(account.last_processed_bar)
            if account.last_processed_bar
            else common_times[-2]
        )
        new_times = [
            value
            for value in common_times
            if value > last_processed
        ]

        if not new_times:
            return {
                "status": "NO_NEW_COMPLETED_15M_BAR",
                "market_time": now_market.isoformat(),
                "latest_completed_bar": latest.isoformat(),
                "open_positions": len(account.positions),
                "pending_entries": len(account.pending),
                "maximum_positions": policy.maximum_concurrent_positions,
                "rankings_enabled": False,
                "live_broker_enabled": False,
            }

        candle_sets = _candles(histories)
        indicators = {
            symbol: calculate_indicators(
                candle_sets[symbol],
                config,
            )
            for symbol in policy.candidates
        }
        index_maps = {
            symbol: {
                bar.start: index
                for index, bar in enumerate(histories[symbol])
            }
            for symbol in policy.candidates
        }
        dividends = fetch_qdte_dividends()
        processed_dividends = set(
            account.processed_dividend_keys
        )

        if initialized:
            processed_dividends.update(
                key
                for key, event_date, _ in dividends
                if event_date <= latest.date()
            )
            account.processed_dividend_keys = sorted(
                processed_dividends
            )

        events: list[dict[str, Any]] = []
        evaluations = 0
        qualifying_count = 0
        filled = 0
        closed = 0
        rejected_gap = 0
        rejected_risk = 0
        deferred_capacity = 0
        tradable_symbols = set(policy.tradable_symbols)

        for bar_time in new_times:
            income_bar = maps[policy.income_symbol][bar_time]
            portfolio = _portfolio(account)

            for key, event_date, amount in dividends:
                if (
                    key not in processed_dividends
                    and event_date <= bar_time.date()
                ):
                    cash = account.income_shares * amount
                    portfolio.cash += cash
                    account.dividends_received += cash
                    processed_dividends.add(key)
                    store.event(
                        "INCOME_DISTRIBUTION",
                        bar_time,
                        {
                            "event_key": key,
                            "event_date": event_date.isoformat(),
                            "amount_per_share": amount,
                            "cash": cash,
                        },
                    )

            account.processed_dividend_keys = sorted(
                processed_dividends
            )
            month_key = (
                f"{bar_time.year:04d}-{bar_time.month:02d}"
            )
            allocation_years = elapsed_complete_years(
                account.start_date,
                bar_time.date(),
            )
            month_changed = (
                account.last_contribution_month != month_key
            )
            phase_changed = (
                allocation_years != account.last_allocation_years
            )

            position_open_prices = {
                symbol: maps[symbol][bar_time].open
                for symbol in portfolio.positions
            }

            if month_changed:
                portfolio.deposit(
                    config.monthly_contribution
                )
                account.total_contributions += (
                    config.monthly_contribution
                )
                account.last_contribution_month = month_key
                store.event(
                    "MONTHLY_CONTRIBUTION",
                    bar_time,
                    {
                        "amount": config.monthly_contribution,
                        "month": month_key,
                    },
                )

            if month_changed or phase_changed:
                target, _ = contribution_allocation(
                    allocation_years,
                    config,
                )
                _rebalance(
                    account=account,
                    portfolio=portfolio,
                    income_price=income_bar.open,
                    position_prices=position_open_prices,
                    target_income_weight=target,
                    config=config,
                )
                store.event(
                    (
                        "MONTHLY_ALLOCATION_REBALANCE"
                        if month_changed
                        else "ALLOCATION_PHASE_REBALANCE"
                    ),
                    bar_time,
                    {
                        "target_income_weight": target,
                        "allocation_years": allocation_years,
                    },
                )

            account.last_allocation_years = allocation_years
            portfolio = _portfolio(account)

            pending_items = sorted(
                account.pending.values(),
                key=lambda item: (
                    item.tie_key,
                    item.symbol,
                ),
            )
            account.pending = {}

            for signal in pending_items:
                signal_time = datetime.fromisoformat(
                    signal.signal_bar
                )

                if bar_time <= signal_time:
                    account.pending[signal.symbol] = signal
                    continue

                if (
                    len(portfolio.positions)
                    >= policy.maximum_concurrent_positions
                ):
                    deferred_capacity += 1
                    store.event(
                        "ENTRY_CANCELLED_CAPACITY",
                        bar_time,
                        {"symbol": signal.symbol},
                    )
                    continue

                bar = maps[signal.symbol][bar_time]
                gap_atr = (
                    abs(bar.open - signal.prior_close)
                    / signal.signal_atr
                )

                if gap_atr > policy.maximum_gap_atr_multiple:
                    rejected_gap += 1
                    store.event(
                        "ENTRY_REJECTED_GAP",
                        bar_time,
                        {
                            "symbol": signal.symbol,
                            "gap_atr": gap_atr,
                        },
                    )
                    continue

                open_prices = {
                    symbol: maps[symbol][bar_time].open
                    for symbol in portfolio.positions
                }
                total_equity = (
                    portfolio.equity(open_prices)
                    + account.income_shares * income_bar.open
                )
                sizing = calculate_position_size(
                    account_equity=total_equity,
                    available_cash=portfolio.cash,
                    entry_price=bar.open,
                    atr=signal.signal_atr,
                    active_risk=portfolio.active_risk(),
                    config=config,
                    trade_results_r=account.trade_results_r,
                )

                if not sizing.is_tradeable:
                    rejected_risk += 1
                    store.event(
                        "ENTRY_REJECTED_RISK",
                        bar_time,
                        {
                            "symbol": signal.symbol,
                            "reason": sizing.blocked_reason,
                        },
                    )
                    continue

                portfolio.open_position(
                    symbol=signal.symbol,
                    sizing=sizing,
                    entry_date=bar_time.date(),
                    entry_atr=signal.signal_atr,
                )
                filled += 1
                store.event(
                    "ENTRY_FILLED_15M",
                    bar_time,
                    {
                        "symbol": signal.symbol,
                        "shares": sizing.shares,
                        "fill_price": sizing.entry_fill,
                        "planned_risk": sizing.planned_risk,
                    },
                )

            for position in list(
                portfolio.positions.values()
            ):
                symbol = position.symbol
                index = index_maps[symbol][bar_time]
                atr = indicators[symbol].atr[index]

                if atr is None or atr <= 0:
                    continue

                bar = maps[symbol][bar_time]
                evaluation = evaluate_exit(
                    position=position,
                    candle=Candle(
                        date=bar_time.date(),
                        open=bar.open,
                        high=bar.high,
                        low=bar.low,
                        close=bar.close,
                        volume=bar.volume,
                    ),
                    current_atr=atr,
                    config=config,
                )

                if evaluation.should_exit:
                    trade = portfolio.close_position(
                        symbol=symbol,
                        exit_price=float(
                            evaluation.exit_price
                        ),
                        exit_date=bar_time.date(),
                        reason=(
                            evaluation.reason
                            or "EXIT"
                        ),
                        config=config,
                    )
                    closed += 1
                    store.event(
                        "POSITION_CLOSED_15M",
                        bar_time,
                        {
                            "symbol": symbol,
                            "pnl": trade.pnl,
                            "reason": trade.reason,
                            "result_r": trade.result_r,
                        },
                    )
                else:
                    position.stop_price = (
                        evaluation.next_stop_price
                    )
                    position.highest_price = (
                        evaluation.highest_price
                    )

            qualifying: list[str] = []
            open_symbols = set(portfolio.positions)
            pending_symbols = set(account.pending)

            for symbol in policy.candidates:
                index = index_maps[symbol][bar_time]
                evaluation = evaluate_entry(
                    candles=candle_sets[symbol],
                    indicators=indicators[symbol],
                    index=index,
                    vix=maps[policy.volatility_symbol][bar_time].close,
                    config=config,
                )
                evaluations += 1

                if (
                    evaluation.should_enter
                    and symbol in tradable_symbols
                    and symbol not in open_symbols
                    and symbol not in pending_symbols
                ):
                    qualifying.append(symbol)
                    qualifying_count += 1

                events.append(
                    {
                        "bar_time": bar_time.isoformat(),
                        "symbol": symbol,
                        "should_enter": evaluation.should_enter,
                        "triggers": list(evaluation.triggers),
                        "failed_checks": list(
                            evaluation.failed_checks
                        ),
                    }
                )

            available_slots = max(
                0,
                policy.maximum_concurrent_positions
                - len(portfolio.positions)
                - len(account.pending),
            )
            accepted, deferred = choose_without_ranking(
                signal_bar=bar_time,
                qualifying=qualifying,
                available_slots=available_slots,
            )
            deferred_capacity += len(deferred)

            for symbol in accepted:
                index = index_maps[symbol][bar_time]
                atr = indicators[symbol].atr[index]

                if atr is None or atr <= 0:
                    continue

                bar = maps[symbol][bar_time]
                tie_key = hashlib.sha256(
                    (
                        bar_time.isoformat()
                        + "|"
                        + symbol
                    ).encode("utf-8")
                ).hexdigest()
                account.pending[symbol] = PendingSignal(
                    symbol=symbol,
                    signal_bar=bar_time.isoformat(),
                    signal_atr=atr,
                    prior_close=bar.close,
                    tie_key=tie_key,
                )
                store.event(
                    "ENTRY_STAGED_15M",
                    bar_time,
                    {
                        "symbol": symbol,
                        "next_bar_execution": True,
                    },
                )

            _sync(account, portfolio)
            account.last_processed_bar = bar_time.isoformat()
            account.revision += 1

        account.validate(policy)
        store.save(account, policy)

        latest_prices = {
            symbol: maps[symbol][latest].close
            for symbol in account.positions
        }
        portfolio = _portfolio(account)
        swing_equity = portfolio.equity(latest_prices)
        income_value = (
            account.income_shares
            * maps[policy.income_symbol][latest].close
        )
        summary = {
            "schema_version": 1,
            "generated_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "status": "PROCESSED",
            "market_time": now_market.isoformat(),
            "latest_completed_bar": latest.isoformat(),
            "bars_processed": len(new_times),
            "symbol_evaluations": evaluations,
            "candidate_symbols": list(policy.candidates),
            "tradable_symbols": list(policy.tradable_symbols),
            "income_symbol": policy.income_symbol,
            "volatility_symbol": policy.volatility_symbol,
            "qualifying_signals": qualifying_count,
            "filled_entries": filled,
            "closed_positions": closed,
            "gap_rejections": rejected_gap,
            "risk_rejections": rejected_risk,
            "capacity_deferred": deferred_capacity,
            "open_positions": len(account.positions),
            "pending_entries": len(account.pending),
            "maximum_positions": policy.maximum_concurrent_positions,
            "position_symbols": sorted(account.positions),
            "swing_equity": swing_equity,
            "income_value": income_value,
            "total_equity": swing_equity + income_value,
            "total_contributions": account.total_contributions,
            "rankings_enabled": False,
            "interval": "15m",
            "extended_hours_enabled": False,
            "live_broker_enabled": False,
            "migration": migration,
            "initialized_this_cycle": initialized,
        }
        report_path = (
            report_dir
            / "latest_15m_paper_status.json"
        )
        temporary = report_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(
                summary,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(report_path)

        diagnostics_path = (
            report_dir
            / "latest_15m_entry_diagnostics.json"
        )
        diagnostics_temp = diagnostics_path.with_suffix(".json.tmp")
        diagnostics_temp.write_text(
            json.dumps(
                {
                    "generated_at_utc": summary[
                        "generated_at_utc"
                    ],
                    "bars": events,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        diagnostics_temp.replace(diagnostics_path)
        return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate configured candidates on every completed "
            "regular-session 15-minute bar and paper-trade "
            "up to the configured position limit."
        )
    )
    parser.add_argument(
        "--policy",
        default=str(DEFAULT_POLICY),
    )
    parser.add_argument(
        "--runtime-dir",
        default=str(DEFAULT_RUNTIME),
    )
    parser.add_argument(
        "--legacy-runtime-dir",
        default=str(DEFAULT_LEGACY_RUNTIME),
    )
    parser.add_argument(
        "--report-dir",
        default=str(DEFAULT_REPORTS),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    summary = run_cycle(
        policy_path=args.policy,
        runtime_directory=args.runtime_dir,
        legacy_runtime_directory=args.legacy_runtime_dir,
        report_directory=args.report_dir,
    )
    print("=" * 78)
    print(
        "QPX BOT — CONFIGURABLE-SYMBOL "
        "15-MINUTE PAPER ENGINE"
    )
    print("=" * 78)

    for key, value in summary.items():
        print(f"{key:<28}: {value}")

    print("Rankings                    : REMOVED")
    print("Live brokerage              : DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
