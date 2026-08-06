"""Regular-session-only execution for staged QPX paper instructions."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date, datetime, time as clock_time, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from qpx_bot.config import BotConfig
from qpx_bot.market_calendar import (
    NEW_YORK,
    is_market_session,
    next_market_session,
)
from qpx_bot.paper_state import (
    AuditEvent,
    PaperState,
    PersistentPosition,
    StateStore,
)
from qpx_bot.real_data import load_market_csv
from qpx_bot.risk import calculate_position_size
from qpx_bot.yahoo_data import YAHOO_HOSTS


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
DEFAULT_CONFIG_PATH = (
    PACKAGE_DIR / "session_execution_config.json"
)
DEFAULT_PAPER_RUNTIME = PACKAGE_DIR / "paper_runtime"
DEFAULT_INPUT_DIR = PACKAGE_DIR / "data_inputs"
DEFAULT_REPORT_DIR = (
    PROJECT_ROOT / "reports" / "qpx_session_execution"
)


@dataclass(frozen=True, slots=True)
class SessionExecutionConfig:
    schema_version: int
    market_timezone: str
    regular_session_open: str
    opening_window_start: str
    opening_window_end: str
    regular_session_close: str
    intraday_interval: str
    intraday_range: str
    maximum_gap_atr_multiple: float
    maximum_quote_attempts: int
    quote_timeout_seconds: float
    extended_hours_enabled: bool

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError(
                "Unsupported session-execution configuration."
            )

        if self.market_timezone != "America/New_York":
            raise ValueError(
                "Session execution requires America/New_York."
            )

        session_open = _parse_time(
            self.regular_session_open
        )
        window_start = _parse_time(
            self.opening_window_start
        )
        window_end = _parse_time(
            self.opening_window_end
        )
        session_close = _parse_time(
            self.regular_session_close
        )

        if not (
            session_open
            <= window_start
            < window_end
            < session_close
        ):
            raise ValueError(
                "Opening-window times are inconsistent."
            )

        if self.intraday_interval != "1m":
            raise ValueError(
                "The paper opening model requires one-minute bars."
            )

        if self.intraday_range != "1d":
            raise ValueError(
                "The opening quote range must be one day."
            )

        if self.maximum_gap_atr_multiple <= 0:
            raise ValueError(
                "Maximum opening gap must be positive."
            )

        if self.maximum_quote_attempts < 1:
            raise ValueError(
                "Maximum quote attempts must be positive."
            )

        if self.quote_timeout_seconds <= 0:
            raise ValueError(
                "Quote timeout must be positive."
            )

        if self.extended_hours_enabled:
            raise ValueError(
                "Extended-hours execution is prohibited."
            )


@dataclass(frozen=True, slots=True)
class OpeningQuote:
    symbol: str
    session_date: date
    bar_time_market: datetime
    observed_at_utc: str
    open_price: float
    source: str
    extended_hours: bool = False

    def validate(
        self,
        config: SessionExecutionConfig,
    ) -> None:
        if not self.symbol.strip():
            raise ValueError(
                "Opening quote symbol cannot be empty."
            )

        if self.open_price <= 0:
            raise ValueError(
                "Opening quote price must be positive."
            )

        if self.extended_hours:
            raise ValueError(
                "Extended-hours quotes cannot execute QPX orders."
            )

        local = self.bar_time_market.astimezone(
            NEW_YORK
        )
        session_open = _parse_time(
            config.regular_session_open
        )
        session_close = _parse_time(
            config.regular_session_close
        )
        wall_clock = local.time().replace(
            tzinfo=None
        )

        if local.date() != self.session_date:
            raise ValueError(
                "Opening quote date and timestamp disagree."
            )

        if not (
            session_open
            <= wall_clock
            < session_close
        ):
            raise ValueError(
                "Opening quote is outside regular hours."
            )


@dataclass(frozen=True, slots=True)
class EntryOutcome:
    status: str
    message: str
    events: tuple[AuditEvent, ...]
    quote_price: float
    gap_atr_multiple: float
    fill_price: float | None
    shares: int
    stop_price: float | None
    target_price: float | None


@dataclass(frozen=True, slots=True)
class SessionExecutionReport:
    generated_at_utc: str
    market_time: str
    status: str
    message: str
    market_phase: str
    expected_session: str | None
    signal_date: str | None
    pending_order_id: str | None
    symbol: str | None
    quote_source: str | None
    opening_price: float | None
    opening_gap_atr: float | None
    fill_price: float | None
    shares: int
    stop_price: float | None
    target_price: float | None
    extended_hours: bool
    mode: str


QuoteProvider = Callable[
    [str, datetime, SessionExecutionConfig],
    OpeningQuote,
]


def _parse_time(value: str) -> clock_time:
    try:
        hour_text, minute_text = value.split(
            ":",
            1,
        )
        return clock_time(
            int(hour_text),
            int(minute_text),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Session time must use HH:MM."
        ) from exc


def load_session_execution_config(
    filename: str | Path = DEFAULT_CONFIG_PATH,
) -> SessionExecutionConfig:
    path = Path(filename).expanduser().resolve()
    payload = json.loads(
        path.read_text(encoding="utf-8")
    )

    if not isinstance(payload, Mapping):
        raise ValueError(
            "Session configuration must be an object."
        )

    config = SessionExecutionConfig(
        schema_version=int(payload["schema_version"]),
        market_timezone=str(
            payload["market_timezone"]
        ),
        regular_session_open=str(
            payload["regular_session_open"]
        ),
        opening_window_start=str(
            payload["opening_window_start"]
        ),
        opening_window_end=str(
            payload["opening_window_end"]
        ),
        regular_session_close=str(
            payload["regular_session_close"]
        ),
        intraday_interval=str(
            payload["intraday_interval"]
        ),
        intraday_range=str(
            payload["intraday_range"]
        ),
        maximum_gap_atr_multiple=float(
            payload["maximum_gap_atr_multiple"]
        ),
        maximum_quote_attempts=int(
            payload["maximum_quote_attempts"]
        ),
        quote_timeout_seconds=float(
            payload["quote_timeout_seconds"]
        ),
        extended_hours_enabled=bool(
            payload["extended_hours_enabled"]
        ),
    )
    config.validate()
    return config


def _market_now(
    current: datetime | None,
) -> datetime:
    moment = current or datetime.now(tz=NEW_YORK)

    if moment.tzinfo is None:
        return moment.replace(tzinfo=NEW_YORK)

    return moment.astimezone(NEW_YORK)


def session_phase(
    current: datetime,
    config: SessionExecutionConfig,
) -> str:
    moment = _market_now(current)

    if not is_market_session(moment.date()):
        return "NON_SESSION"

    wall_clock = moment.time().replace(
        tzinfo=None
    )
    session_open = _parse_time(
        config.regular_session_open
    )
    window_start = _parse_time(
        config.opening_window_start
    )
    window_end = _parse_time(
        config.opening_window_end
    )
    session_close = _parse_time(
        config.regular_session_close
    )

    if wall_clock < session_open:
        return "PRE_MARKET"

    if wall_clock < window_start:
        return "OPENING_DELAY"

    if wall_clock <= window_end:
        return "OPENING_WINDOW"

    if wall_clock < session_close:
        return "REGULAR_SESSION"

    return "AFTER_HOURS"


def _atomic_json(
    path: Path,
    payload: Mapping[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(
        path.suffix + ".tmp"
    )
    temporary.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _report_text(
    report: SessionExecutionReport,
) -> str:
    lines = [
        "=" * 78,
        "QPX BOT v1.13 — REGULAR-SESSION EXECUTION",
        "=" * 78,
        f"Status                : {report.status}",
        f"Message               : {report.message}",
        f"Market time           : {report.market_time}",
        f"Market phase          : {report.market_phase}",
        f"Expected session      : {report.expected_session}",
        f"Signal date           : {report.signal_date}",
        f"Pending order         : {report.pending_order_id}",
        f"Symbol                : {report.symbol}",
        f"Quote source          : {report.quote_source}",
        f"Opening price         : {report.opening_price}",
        f"Opening gap / ATR     : {report.opening_gap_atr}",
        f"Fill price            : {report.fill_price}",
        f"Shares                : {report.shares}",
        f"Stop price            : {report.stop_price}",
        f"Target price          : {report.target_price}",
        f"Extended hours        : {report.extended_hours}",
        f"Mode                  : {report.mode}",
        "=" * 78,
        (
            "After-close analysis cannot fill entries. "
            "Simulation only; no brokerage connection."
        ),
    ]
    return "\n".join(lines)


def write_session_report(
    report: SessionExecutionReport,
    report_directory: str | Path,
) -> dict[str, Path]:
    directory = Path(
        report_directory
    ).expanduser().resolve()
    directory.mkdir(
        parents=True,
        exist_ok=True,
    )
    json_path = (
        directory / "latest_session_execution.json"
    )
    text_path = (
        directory / "latest_session_execution.txt"
    )
    payload = asdict(report)
    _atomic_json(json_path, payload)
    text_path.write_text(
        _report_text(report) + "\n",
        encoding="utf-8",
    )
    return {
        "json": json_path,
        "text": text_path,
    }


def _event_id(
    state: PaperState,
    event_type: str,
    order_id: str,
) -> str:
    raw = (
        f"{state.state_id}|{event_type}|"
        f"{order_id}"
    )
    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()[:32]


def _entry_event(
    *,
    state: PaperState,
    event_type: str,
    event_date: date,
    order_id: str,
    details: Mapping[str, Any],
) -> AuditEvent:
    return AuditEvent(
        event_id=_event_id(
            state,
            event_type,
            order_id,
        ),
        event_type=event_type,
        event_date=event_date,
        details=dict(details),
    )


def _complete_pending_key(
    state: PaperState,
    order_id: str,
) -> None:
    if order_id not in state.completed_order_keys:
        state.completed_order_keys.append(order_id)


def cancel_pending_instruction(
    state: PaperState,
    *,
    event_date: date,
    event_type: str,
    reason: str,
) -> tuple[AuditEvent, ...]:
    pending = state.pending_entry

    if pending is None:
        return ()

    order_id = pending.order_id
    details = {
        "order_id": order_id,
        "symbol": pending.symbol,
        "signal_date": pending.signal_date.isoformat(),
        "reason": reason,
        "execution_session": "NONE",
        "extended_hours": False,
        "instruction_source": (
            "AFTER_CLOSE_DAILY_SIGNAL"
        ),
    }
    _complete_pending_key(
        state,
        order_id,
    )
    state.pending_entry = None
    state.revision += 1
    state.validate()
    return (
        _entry_event(
            state=state,
            event_type=event_type,
            event_date=event_date,
            order_id=order_id,
            details=details,
        ),
    )


def apply_pending_entry_regular_session(
    state: PaperState,
    *,
    quote: OpeningQuote,
    prior_close: float,
    income_price: float,
    bot_config: BotConfig,
    execution_config: SessionExecutionConfig,
) -> EntryOutcome:
    bot_config.validate()
    execution_config.validate()
    state.validate()
    quote.validate(execution_config)

    pending = state.pending_entry

    if pending is None:
        raise ValueError(
            "No staged entry instruction exists."
        )

    if state.position is not None:
        raise ValueError(
            "A pending entry cannot coexist with a position."
        )

    expected_session = next_market_session(
        pending.signal_date
    )

    if quote.session_date != expected_session:
        raise ValueError(
            "Opening quote is not from the instruction's "
            "next market session."
        )

    if quote.symbol.strip().upper() != pending.symbol:
        raise ValueError(
            "Opening quote symbol does not match instruction."
        )

    if prior_close <= 0 or income_price <= 0:
        raise ValueError(
            "Reference prices must be positive."
        )

    order_id = pending.order_id
    gap_atr = (
        abs(quote.open_price - prior_close)
        / pending.signal_atr
    )

    common_details = {
        "order_id": order_id,
        "symbol": pending.symbol,
        "signal_date": (
            pending.signal_date.isoformat()
        ),
        "scheduled_session": (
            quote.session_date.isoformat()
        ),
        "opening_reference_price": (
            quote.open_price
        ),
        "prior_close": prior_close,
        "opening_gap_atr": gap_atr,
        "quote_source": quote.source,
        "market_bar_time": (
            quote.bar_time_market.isoformat()
        ),
        "recorded_at_utc": (
            quote.observed_at_utc
        ),
        "execution_session": "REGULAR_SESSION",
        "extended_hours": False,
        "instruction_source": (
            "AFTER_CLOSE_DAILY_SIGNAL"
        ),
    }

    if (
        gap_atr
        > execution_config.maximum_gap_atr_multiple
    ):
        event_type = "ENTRY_REJECTED_OPENING_GAP"
        details = {
            **common_details,
            "reason": (
                "opening gap exceeded configured ATR limit"
            ),
            "maximum_gap_atr": (
                execution_config.maximum_gap_atr_multiple
            ),
        }
        _complete_pending_key(
            state,
            order_id,
        )
        state.pending_entry = None
        state.revision += 1
        state.validate()
        event = _entry_event(
            state=state,
            event_type=event_type,
            event_date=quote.session_date,
            order_id=order_id,
            details=details,
        )
        return EntryOutcome(
            status="REJECTED_GAP",
            message=details["reason"],
            events=(event,),
            quote_price=quote.open_price,
            gap_atr_multiple=gap_atr,
            fill_price=None,
            shares=0,
            stop_price=None,
            target_price=None,
        )

    combined_equity = state.equity(
        swing_price=quote.open_price,
        income_price=income_price,
    )
    sizing = calculate_position_size(
        account_equity=combined_equity,
        available_cash=state.swing_cash,
        entry_price=quote.open_price,
        atr=pending.signal_atr,
        active_risk=0.0,
        config=bot_config,
        trade_results_r=state.trade_results_r,
    )

    if sizing.is_tradeable:
        cost = sizing.entry_fill * sizing.shares
        state.swing_cash -= cost
        state.position = PersistentPosition(
            symbol=state.swing_symbol,
            shares=sizing.shares,
            entry_date=quote.session_date,
            entry_price=sizing.entry_fill,
            entry_atr=pending.signal_atr,
            stop_price=sizing.stop_price,
            target_price=sizing.target_price,
            highest_price=sizing.entry_fill,
        )
        event_type = (
            "ENTRY_FILLED_REGULAR_SESSION"
        )
        details = {
            **common_details,
            "shares": sizing.shares,
            "fill_price": sizing.entry_fill,
            "cost": cost,
            "stop_price": sizing.stop_price,
            "target_price": sizing.target_price,
            "planned_risk": sizing.planned_risk,
            "protection_policy": (
                "PAPER_OHLC_RECONCILIATION;"
                "FUTURE_LIVE_MODE_REQUIRES_BROKER_OCO"
            ),
        }
        status = "FILLED"
        message = (
            "Staged instruction filled from the first "
            "regular-session minute bar."
        )
        fill_price = sizing.entry_fill
        shares = sizing.shares
        stop_price = sizing.stop_price
        target_price = sizing.target_price
    else:
        event_type = (
            "ENTRY_REJECTED_POSITION_SIZING"
        )
        details = {
            **common_details,
            "reason": sizing.blocked_reason,
            "available_cash": state.swing_cash,
            "combined_equity": combined_equity,
        }
        status = "REJECTED_RISK"
        message = (
            sizing.blocked_reason
            or "Position sizing rejected the instruction."
        )
        fill_price = None
        shares = 0
        stop_price = None
        target_price = None

    _complete_pending_key(
        state,
        order_id,
    )
    state.pending_entry = None
    state.revision += 1
    state.validate()
    event = _entry_event(
        state=state,
        event_type=event_type,
        event_date=quote.session_date,
        order_id=order_id,
        details=details,
    )
    return EntryOutcome(
        status=status,
        message=message,
        events=(event,),
        quote_price=quote.open_price,
        gap_atr_multiple=gap_atr,
        fill_price=fill_price,
        shares=shares,
        stop_price=stop_price,
        target_price=target_price,
    )


def _intraday_url(
    host: str,
    symbol: str,
    config: SessionExecutionConfig,
) -> str:
    encoded = urllib.parse.quote(
        symbol,
        safe="",
    )
    query = urllib.parse.urlencode(
        {
            "range": config.intraday_range,
            "interval": config.intraday_interval,
            "includePrePost": "false",
            "events": "div,splits",
        }
    )
    return (
        f"https://{host}/v8/finance/chart/"
        f"{encoded}?{query}"
    )


def _open_intraday_json(
    url: str,
    timeout_seconds: float,
) -> Mapping[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 14) "
                "AppleWebKit/537.36 QPXBot/1.13"
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

    if not isinstance(chart, Mapping):
        raise RuntimeError(
            "Intraday chart response is missing."
        )

    if chart.get("error"):
        raise RuntimeError(
            f"Intraday provider error: {chart['error']}"
        )

    results = chart.get("result")

    if not isinstance(results, list) or not results:
        raise RuntimeError(
            "Intraday provider returned no result."
        )

    result = results[0]

    if not isinstance(result, Mapping):
        raise RuntimeError(
            "Intraday provider result is invalid."
        )

    return result


def _as_sequence(value: Any) -> Sequence[Any]:
    if (
        isinstance(value, Sequence)
        and not isinstance(
            value,
            (str, bytes),
        )
    ):
        return value

    return ()


def _extract_first_regular_open(
    result: Mapping[str, Any],
    *,
    symbol: str,
    session_date: date,
    current: datetime,
    config: SessionExecutionConfig,
) -> OpeningQuote:
    timestamps = _as_sequence(
        result.get("timestamp")
    )
    indicators = result.get("indicators")

    if not isinstance(indicators, Mapping):
        raise RuntimeError(
            "Intraday indicators are missing."
        )

    quotes = indicators.get("quote")

    if not isinstance(quotes, list) or not quotes:
        raise RuntimeError(
            "Intraday quote arrays are missing."
        )

    quote_payload = quotes[0]

    if not isinstance(quote_payload, Mapping):
        raise RuntimeError(
            "Intraday quote payload is invalid."
        )

    opens = _as_sequence(
        quote_payload.get("open")
    )
    session_open = _parse_time(
        config.regular_session_open
    )
    session_close = _parse_time(
        config.regular_session_close
    )
    current_market = _market_now(current)

    candidates: list[
        tuple[datetime, float]
    ] = []

    for index, raw_timestamp in enumerate(
        timestamps
    ):
        if (
            raw_timestamp is None
            or index >= len(opens)
            or opens[index] is None
        ):
            continue

        market_time = datetime.fromtimestamp(
            float(raw_timestamp),
            tz=timezone.utc,
        ).astimezone(NEW_YORK)
        wall_clock = market_time.time().replace(
            tzinfo=None
        )

        if market_time.date() != session_date:
            continue

        if market_time > current_market:
            continue

        if not (
            session_open
            <= wall_clock
            < session_close
        ):
            continue

        price = float(opens[index])

        if price > 0:
            candidates.append(
                (market_time, price)
            )

    if not candidates:
        raise RuntimeError(
            "The first regular-session minute bar "
            "is not available yet."
        )

    candidates.sort(
        key=lambda item: item[0]
    )
    bar_time, price = candidates[0]
    quote = OpeningQuote(
        symbol=symbol.strip().upper(),
        session_date=session_date,
        bar_time_market=bar_time,
        observed_at_utc=datetime.now(
            timezone.utc
        ).isoformat(),
        open_price=price,
        source=(
            "YAHOO_FIRST_1M_REGULAR_SESSION_BAR"
        ),
        extended_hours=False,
    )
    quote.validate(config)
    return quote


def fetch_opening_quote(
    symbol: str,
    current: datetime,
    config: SessionExecutionConfig,
) -> OpeningQuote:
    normalized = symbol.strip().upper()

    if not normalized:
        raise ValueError(
            "Quote symbol cannot be empty."
        )

    current_market = _market_now(current)
    errors: list[str] = []

    for attempt in range(
        1,
        config.maximum_quote_attempts + 1,
    ):
        host = YAHOO_HOSTS[
            (attempt - 1) % len(YAHOO_HOSTS)
        ]
        url = _intraday_url(
            host,
            normalized,
            config,
        )

        try:
            result = _open_intraday_json(
                url,
                config.quote_timeout_seconds,
            )
            return _extract_first_regular_open(
                result,
                symbol=normalized,
                session_date=current_market.date(),
                current=current_market,
                config=config,
            )
        except (
            RuntimeError,
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            errors.append(
                f"attempt {attempt} via {host}: "
                f"{type(exc).__name__}: {exc}"
            )

            if (
                attempt
                < config.maximum_quote_attempts
            ):
                time.sleep(
                    min(6.0, float(attempt))
                )

    raise RuntimeError(
        "Unable to obtain the first regular-session "
        f"bar for {normalized}.\n"
        + "\n".join(errors)
    )


def _latest_price_on_or_before(
    candles,
    day: date,
) -> float:
    selected = None

    for candle in candles:
        if candle.date > day:
            break
        selected = candle

    if selected is None:
        raise RuntimeError(
            f"No market price exists on or before {day}."
        )

    return float(selected.close)


def _build_report(
    *,
    current: datetime,
    status: str,
    message: str,
    phase: str,
    state: PaperState | None,
    expected_session: date | None,
    quote: OpeningQuote | None = None,
    outcome: EntryOutcome | None = None,
) -> SessionExecutionReport:
    pending = (
        state.pending_entry
        if state is not None
        else None
    )
    return SessionExecutionReport(
        generated_at_utc=datetime.now(
            timezone.utc
        ).isoformat(),
        market_time=_market_now(
            current
        ).isoformat(),
        status=status,
        message=message,
        market_phase=phase,
        expected_session=(
            expected_session.isoformat()
            if expected_session
            else None
        ),
        signal_date=(
            pending.signal_date.isoformat()
            if pending
            else None
        ),
        pending_order_id=(
            pending.order_id
            if pending
            else None
        ),
        symbol=(
            (
                quote.symbol
                if quote
                else state.swing_symbol
            )
            if state
            else None
        ),
        quote_source=(
            quote.source
            if quote
            else None
        ),
        opening_price=(
            quote.open_price
            if quote
            else None
        ),
        opening_gap_atr=(
            outcome.gap_atr_multiple
            if outcome
            else None
        ),
        fill_price=(
            outcome.fill_price
            if outcome
            else None
        ),
        shares=(
            outcome.shares
            if outcome
            else 0
        ),
        stop_price=(
            outcome.stop_price
            if outcome
            else None
        ),
        target_price=(
            outcome.target_price
            if outcome
            else None
        ),
        extended_hours=False,
        mode="SIMULATED_REGULAR_SESSION_ONLY",
    )


def execute_regular_session(
    *,
    config: SessionExecutionConfig,
    paper_runtime: str | Path,
    input_directory: str | Path,
    report_directory: str | Path,
    current: datetime | None = None,
    check_only: bool = False,
    quote_provider: QuoteProvider = fetch_opening_quote,
) -> tuple[int, SessionExecutionReport]:
    moment = _market_now(current)
    phase = session_phase(
        moment,
        config,
    )
    store = StateStore(paper_runtime)
    report_path = Path(
        report_directory
    ).expanduser().resolve()

    with store.locked():
        if store.kill_switch_active():
            report = _build_report(
                current=moment,
                status="PAUSED",
                message=(
                    "Paper kill switch is active."
                ),
                phase=phase,
                state=(
                    store.load()
                    if store.exists()
                    else None
                ),
                expected_session=None,
            )
            write_session_report(
                report,
                report_path,
            )
            return 4, report

        if not store.exists():
            report = _build_report(
                current=moment,
                status="NO_ACCOUNT",
                message=(
                    "Persistent paper account does not exist."
                ),
                phase=phase,
                state=None,
                expected_session=None,
            )
            write_session_report(
                report,
                report_path,
            )
            return 0, report

        state = store.load()
        store.verify_journal()
        pending = state.pending_entry
        expected_session = (
            next_market_session(
                pending.signal_date
            )
            if pending
            else None
        )

        if check_only:
            report = _build_report(
                current=moment,
                status="CHECK_ONLY",
                message=(
                    "Regular-session execution snapshot "
                    "completed without mutation."
                ),
                phase=phase,
                state=state,
                expected_session=expected_session,
            )
            write_session_report(
                report,
                report_path,
            )
            return 0, report

        if pending is None:
            report = _build_report(
                current=moment,
                status="NO_PENDING",
                message=(
                    "No staged entry instruction exists."
                ),
                phase=phase,
                state=state,
                expected_session=None,
            )
            write_session_report(
                report,
                report_path,
            )
            return 0, report

        assert expected_session is not None

        if moment.date() < expected_session:
            report = _build_report(
                current=moment,
                status="WAITING",
                message=(
                    "Instruction is waiting for its next "
                    "market session."
                ),
                phase=phase,
                state=state,
                expected_session=expected_session,
            )
            write_session_report(
                report,
                report_path,
            )
            return 0, report

        if moment.date() > expected_session:
            order_id = pending.order_id
            events = cancel_pending_instruction(
                state,
                event_date=moment.date(),
                event_type=(
                    "ENTRY_CANCELLED_STALE_SESSION"
                ),
                reason=(
                    "instruction was not executed during "
                    "its scheduled market session"
                ),
            )
            store.append_events(
                list(events)
            )
            store.save(state)
            report = _build_report(
                current=moment,
                status="CANCELLED_STALE",
                message=(
                    "Stale staged instruction was cancelled."
                ),
                phase=phase,
                state=state,
                expected_session=expected_session,
            )
            report = SessionExecutionReport(
                **{
                    **asdict(report),
                    "pending_order_id": order_id,
                }
            )
            write_session_report(
                report,
                report_path,
            )
            return 0, report

        if phase in {
            "PRE_MARKET",
            "OPENING_DELAY",
        }:
            report = _build_report(
                current=moment,
                status="WAITING",
                message=(
                    "Waiting for the regular-session "
                    "opening execution window."
                ),
                phase=phase,
                state=state,
                expected_session=expected_session,
            )
            write_session_report(
                report,
                report_path,
            )
            return 0, report

        if phase != "OPENING_WINDOW":
            order_id = pending.order_id
            events = cancel_pending_instruction(
                state,
                event_date=moment.date(),
                event_type=(
                    "ENTRY_CANCELLED_MISSED_WINDOW"
                ),
                reason=(
                    "regular-session opening window expired; "
                    "after-hours backfill is prohibited"
                ),
            )
            store.append_events(
                list(events)
            )
            store.save(state)
            report = _build_report(
                current=moment,
                status="CANCELLED_EXPIRED",
                message=(
                    "Missed opening-window instruction "
                    "was cancelled instead of backfilled."
                ),
                phase=phase,
                state=state,
                expected_session=expected_session,
            )
            report = SessionExecutionReport(
                **{
                    **asdict(report),
                    "pending_order_id": order_id,
                }
            )
            write_session_report(
                report,
                report_path,
            )
            return 0, report

        try:
            quote = quote_provider(
                pending.symbol,
                moment,
                config,
            )
            quote.validate(config)
            input_path = Path(
                input_directory
            ).expanduser().resolve()
            swing = load_market_csv(
                input_path / "SWING.csv"
            )
            income = load_market_csv(
                input_path / "QDTE.csv"
            )
            prior_close = (
                _latest_price_on_or_before(
                    swing,
                    pending.signal_date,
                )
            )
            income_price = (
                _latest_price_on_or_before(
                    income,
                    moment.date(),
                )
            )
            outcome = (
                apply_pending_entry_regular_session(
                    state,
                    quote=quote,
                    prior_close=prior_close,
                    income_price=income_price,
                    bot_config=BotConfig(),
                    execution_config=config,
                )
            )
        except Exception as exc:
            report = _build_report(
                current=moment,
                status="QUOTE_RETRY",
                message=(
                    f"{type(exc).__name__}: {exc}"
                ),
                phase=phase,
                state=state,
                expected_session=expected_session,
            )
            write_session_report(
                report,
                report_path,
            )
            return 5, report

        store.append_events(
            list(outcome.events)
        )
        store.save(state)
        report = _build_report(
            current=moment,
            status=outcome.status,
            message=outcome.message,
            phase=phase,
            state=state,
            expected_session=expected_session,
            quote=quote,
            outcome=outcome,
        )
        report = SessionExecutionReport(
            **{
                **asdict(report),
                "signal_date": (
                    pending.signal_date.isoformat()
                ),
                "pending_order_id": (
                    pending.order_id
                ),
            }
        )
        write_session_report(
            report,
            report_path,
        )
        return 0, report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Execute staged QPX paper entries only during "
            "the next regular-session opening window."
        )
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
    )
    parser.add_argument(
        "--paper-runtime-dir",
        default=str(DEFAULT_PAPER_RUNTIME),
    )
    parser.add_argument(
        "--input-dir",
        default=str(DEFAULT_INPUT_DIR),
    )
    parser.add_argument(
        "--report-dir",
        default=str(DEFAULT_REPORT_DIR),
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = load_session_execution_config(
        args.config
    )
    code, report = execute_regular_session(
        config=config,
        paper_runtime=args.paper_runtime_dir,
        input_directory=args.input_dir,
        report_directory=args.report_dir,
        check_only=args.check_only,
    )
    print(_report_text(report))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
