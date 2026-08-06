#!/usr/bin/env python3
"""Install, test, push, and schedule regular-session execution."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap


def find_root() -> Path:
    for start in (
        Path(__file__).resolve().parent,
        Path.cwd().resolve(),
    ):
        for candidate in (
            start,
            *start.parents,
        ):
            if (
                (candidate / ".git").exists()
                and (candidate / "qpx_bot").exists()
                and (candidate / "tests").exists()
            ):
                return candidate

    raise RuntimeError(
        "QPX_ALPHA was not found. Save this installer inside "
        "/storage/emulated/0/QPX_ALPHA and run it again."
    )


ROOT = find_root()
STAMP = datetime.now().strftime(
    "%Y%m%d_%H%M%S"
)
BACKUP = (
    ROOT
    / "backups"
    / "qpx_regular_session_execution_v2"
    / STAMP
)

FILES = {
    "qpx_bot/__init__.py": '"""\nQPX Bot\n\nResearch and paper-trading bot for the Hybrid Dividend + Swing strategy.\n"""\n\n__version__ = "1.13.0"\n',
    "qpx_bot/session_execution_config.json": '{\n  "schema_version": 1,\n  "market_timezone": "America/New_York",\n  "regular_session_open": "09:30",\n  "opening_window_start": "09:35",\n  "opening_window_end": "10:30",\n  "regular_session_close": "16:00",\n  "intraday_interval": "1m",\n  "intraday_range": "1d",\n  "maximum_gap_atr_multiple": 1.5,\n  "maximum_quote_attempts": 4,\n  "quote_timeout_seconds": 20.0,\n  "extended_hours_enabled": false\n}\n',
    "qpx_bot/session_execution.py": '"""Regular-session-only execution for staged QPX paper instructions."""\n\nfrom __future__ import annotations\n\nimport argparse\nimport hashlib\nimport json\nimport time\nimport urllib.error\nimport urllib.parse\nimport urllib.request\nfrom dataclasses import asdict, dataclass\nfrom datetime import date, datetime, time as clock_time, timezone\nfrom pathlib import Path\nfrom typing import Any, Callable, Mapping, Sequence\n\nfrom qpx_bot.config import BotConfig\nfrom qpx_bot.market_calendar import (\n    NEW_YORK,\n    is_market_session,\n    next_market_session,\n)\nfrom qpx_bot.paper_state import (\n    AuditEvent,\n    PaperState,\n    PersistentPosition,\n    StateStore,\n)\nfrom qpx_bot.real_data import load_market_csv\nfrom qpx_bot.risk import calculate_position_size\nfrom qpx_bot.yahoo_data import YAHOO_HOSTS\n\n\nPACKAGE_DIR = Path(__file__).resolve().parent\nPROJECT_ROOT = PACKAGE_DIR.parent\nDEFAULT_CONFIG_PATH = (\n    PACKAGE_DIR / "session_execution_config.json"\n)\nDEFAULT_PAPER_RUNTIME = PACKAGE_DIR / "paper_runtime"\nDEFAULT_INPUT_DIR = PACKAGE_DIR / "data_inputs"\nDEFAULT_REPORT_DIR = (\n    PROJECT_ROOT / "reports" / "qpx_session_execution"\n)\n\n\n@dataclass(frozen=True, slots=True)\nclass SessionExecutionConfig:\n    schema_version: int\n    market_timezone: str\n    regular_session_open: str\n    opening_window_start: str\n    opening_window_end: str\n    regular_session_close: str\n    intraday_interval: str\n    intraday_range: str\n    maximum_gap_atr_multiple: float\n    maximum_quote_attempts: int\n    quote_timeout_seconds: float\n    extended_hours_enabled: bool\n\n    def validate(self) -> None:\n        if self.schema_version != 1:\n            raise ValueError(\n                "Unsupported session-execution configuration."\n            )\n\n        if self.market_timezone != "America/New_York":\n            raise ValueError(\n                "Session execution requires America/New_York."\n            )\n\n        session_open = _parse_time(\n            self.regular_session_open\n        )\n        window_start = _parse_time(\n            self.opening_window_start\n        )\n        window_end = _parse_time(\n            self.opening_window_end\n        )\n        session_close = _parse_time(\n            self.regular_session_close\n        )\n\n        if not (\n            session_open\n            <= window_start\n            < window_end\n            < session_close\n        ):\n            raise ValueError(\n                "Opening-window times are inconsistent."\n            )\n\n        if self.intraday_interval != "1m":\n            raise ValueError(\n                "The paper opening model requires one-minute bars."\n            )\n\n        if self.intraday_range != "1d":\n            raise ValueError(\n                "The opening quote range must be one day."\n            )\n\n        if self.maximum_gap_atr_multiple <= 0:\n            raise ValueError(\n                "Maximum opening gap must be positive."\n            )\n\n        if self.maximum_quote_attempts < 1:\n            raise ValueError(\n                "Maximum quote attempts must be positive."\n            )\n\n        if self.quote_timeout_seconds <= 0:\n            raise ValueError(\n                "Quote timeout must be positive."\n            )\n\n        if self.extended_hours_enabled:\n            raise ValueError(\n                "Extended-hours execution is prohibited."\n            )\n\n\n@dataclass(frozen=True, slots=True)\nclass OpeningQuote:\n    symbol: str\n    session_date: date\n    bar_time_market: datetime\n    observed_at_utc: str\n    open_price: float\n    source: str\n    extended_hours: bool = False\n\n    def validate(\n        self,\n        config: SessionExecutionConfig,\n    ) -> None:\n        if not self.symbol.strip():\n            raise ValueError(\n                "Opening quote symbol cannot be empty."\n            )\n\n        if self.open_price <= 0:\n            raise ValueError(\n                "Opening quote price must be positive."\n            )\n\n        if self.extended_hours:\n            raise ValueError(\n                "Extended-hours quotes cannot execute QPX orders."\n            )\n\n        local = self.bar_time_market.astimezone(\n            NEW_YORK\n        )\n        session_open = _parse_time(\n            config.regular_session_open\n        )\n        session_close = _parse_time(\n            config.regular_session_close\n        )\n        wall_clock = local.time().replace(\n            tzinfo=None\n        )\n\n        if local.date() != self.session_date:\n            raise ValueError(\n                "Opening quote date and timestamp disagree."\n            )\n\n        if not (\n            session_open\n            <= wall_clock\n            < session_close\n        ):\n            raise ValueError(\n                "Opening quote is outside regular hours."\n            )\n\n\n@dataclass(frozen=True, slots=True)\nclass EntryOutcome:\n    status: str\n    message: str\n    events: tuple[AuditEvent, ...]\n    quote_price: float\n    gap_atr_multiple: float\n    fill_price: float | None\n    shares: int\n    stop_price: float | None\n    target_price: float | None\n\n\n@dataclass(frozen=True, slots=True)\nclass SessionExecutionReport:\n    generated_at_utc: str\n    market_time: str\n    status: str\n    message: str\n    market_phase: str\n    expected_session: str | None\n    signal_date: str | None\n    pending_order_id: str | None\n    symbol: str | None\n    quote_source: str | None\n    opening_price: float | None\n    opening_gap_atr: float | None\n    fill_price: float | None\n    shares: int\n    stop_price: float | None\n    target_price: float | None\n    extended_hours: bool\n    mode: str\n\n\nQuoteProvider = Callable[\n    [str, datetime, SessionExecutionConfig],\n    OpeningQuote,\n]\n\n\ndef _parse_time(value: str) -> clock_time:\n    try:\n        hour_text, minute_text = value.split(\n            ":",\n            1,\n        )\n        return clock_time(\n            int(hour_text),\n            int(minute_text),\n        )\n    except (TypeError, ValueError) as exc:\n        raise ValueError(\n            "Session time must use HH:MM."\n        ) from exc\n\n\ndef load_session_execution_config(\n    filename: str | Path = DEFAULT_CONFIG_PATH,\n) -> SessionExecutionConfig:\n    path = Path(filename).expanduser().resolve()\n    payload = json.loads(\n        path.read_text(encoding="utf-8")\n    )\n\n    if not isinstance(payload, Mapping):\n        raise ValueError(\n            "Session configuration must be an object."\n        )\n\n    config = SessionExecutionConfig(\n        schema_version=int(payload["schema_version"]),\n        market_timezone=str(\n            payload["market_timezone"]\n        ),\n        regular_session_open=str(\n            payload["regular_session_open"]\n        ),\n        opening_window_start=str(\n            payload["opening_window_start"]\n        ),\n        opening_window_end=str(\n            payload["opening_window_end"]\n        ),\n        regular_session_close=str(\n            payload["regular_session_close"]\n        ),\n        intraday_interval=str(\n            payload["intraday_interval"]\n        ),\n        intraday_range=str(\n            payload["intraday_range"]\n        ),\n        maximum_gap_atr_multiple=float(\n            payload["maximum_gap_atr_multiple"]\n        ),\n        maximum_quote_attempts=int(\n            payload["maximum_quote_attempts"]\n        ),\n        quote_timeout_seconds=float(\n            payload["quote_timeout_seconds"]\n        ),\n        extended_hours_enabled=bool(\n            payload["extended_hours_enabled"]\n        ),\n    )\n    config.validate()\n    return config\n\n\ndef _market_now(\n    current: datetime | None,\n) -> datetime:\n    moment = current or datetime.now(tz=NEW_YORK)\n\n    if moment.tzinfo is None:\n        return moment.replace(tzinfo=NEW_YORK)\n\n    return moment.astimezone(NEW_YORK)\n\n\ndef session_phase(\n    current: datetime,\n    config: SessionExecutionConfig,\n) -> str:\n    moment = _market_now(current)\n\n    if not is_market_session(moment.date()):\n        return "NON_SESSION"\n\n    wall_clock = moment.time().replace(\n        tzinfo=None\n    )\n    session_open = _parse_time(\n        config.regular_session_open\n    )\n    window_start = _parse_time(\n        config.opening_window_start\n    )\n    window_end = _parse_time(\n        config.opening_window_end\n    )\n    session_close = _parse_time(\n        config.regular_session_close\n    )\n\n    if wall_clock < session_open:\n        return "PRE_MARKET"\n\n    if wall_clock < window_start:\n        return "OPENING_DELAY"\n\n    if wall_clock <= window_end:\n        return "OPENING_WINDOW"\n\n    if wall_clock < session_close:\n        return "REGULAR_SESSION"\n\n    return "AFTER_HOURS"\n\n\ndef _atomic_json(\n    path: Path,\n    payload: Mapping[str, Any],\n) -> None:\n    path.parent.mkdir(parents=True, exist_ok=True)\n    temporary = path.with_suffix(\n        path.suffix + ".tmp"\n    )\n    temporary.write_text(\n        json.dumps(\n            payload,\n            indent=2,\n            sort_keys=True,\n        )\n        + "\\n",\n        encoding="utf-8",\n    )\n    temporary.replace(path)\n\n\ndef _report_text(\n    report: SessionExecutionReport,\n) -> str:\n    lines = [\n        "=" * 78,\n        "QPX BOT v1.13 — REGULAR-SESSION EXECUTION",\n        "=" * 78,\n        f"Status                : {report.status}",\n        f"Message               : {report.message}",\n        f"Market time           : {report.market_time}",\n        f"Market phase          : {report.market_phase}",\n        f"Expected session      : {report.expected_session}",\n        f"Signal date           : {report.signal_date}",\n        f"Pending order         : {report.pending_order_id}",\n        f"Symbol                : {report.symbol}",\n        f"Quote source          : {report.quote_source}",\n        f"Opening price         : {report.opening_price}",\n        f"Opening gap / ATR     : {report.opening_gap_atr}",\n        f"Fill price            : {report.fill_price}",\n        f"Shares                : {report.shares}",\n        f"Stop price            : {report.stop_price}",\n        f"Target price          : {report.target_price}",\n        f"Extended hours        : {report.extended_hours}",\n        f"Mode                  : {report.mode}",\n        "=" * 78,\n        (\n            "After-close analysis cannot fill entries. "\n            "Simulation only; no brokerage connection."\n        ),\n    ]\n    return "\\n".join(lines)\n\n\ndef write_session_report(\n    report: SessionExecutionReport,\n    report_directory: str | Path,\n) -> dict[str, Path]:\n    directory = Path(\n        report_directory\n    ).expanduser().resolve()\n    directory.mkdir(\n        parents=True,\n        exist_ok=True,\n    )\n    json_path = (\n        directory / "latest_session_execution.json"\n    )\n    text_path = (\n        directory / "latest_session_execution.txt"\n    )\n    payload = asdict(report)\n    _atomic_json(json_path, payload)\n    text_path.write_text(\n        _report_text(report) + "\\n",\n        encoding="utf-8",\n    )\n    return {\n        "json": json_path,\n        "text": text_path,\n    }\n\n\ndef _event_id(\n    state: PaperState,\n    event_type: str,\n    order_id: str,\n) -> str:\n    raw = (\n        f"{state.state_id}|{event_type}|"\n        f"{order_id}"\n    )\n    return hashlib.sha256(\n        raw.encode("utf-8")\n    ).hexdigest()[:32]\n\n\ndef _entry_event(\n    *,\n    state: PaperState,\n    event_type: str,\n    event_date: date,\n    order_id: str,\n    details: Mapping[str, Any],\n) -> AuditEvent:\n    return AuditEvent(\n        event_id=_event_id(\n            state,\n            event_type,\n            order_id,\n        ),\n        event_type=event_type,\n        event_date=event_date,\n        details=dict(details),\n    )\n\n\ndef _complete_pending_key(\n    state: PaperState,\n    order_id: str,\n) -> None:\n    if order_id not in state.completed_order_keys:\n        state.completed_order_keys.append(order_id)\n\n\ndef cancel_pending_instruction(\n    state: PaperState,\n    *,\n    event_date: date,\n    event_type: str,\n    reason: str,\n) -> tuple[AuditEvent, ...]:\n    pending = state.pending_entry\n\n    if pending is None:\n        return ()\n\n    order_id = pending.order_id\n    details = {\n        "order_id": order_id,\n        "symbol": pending.symbol,\n        "signal_date": pending.signal_date.isoformat(),\n        "reason": reason,\n        "execution_session": "NONE",\n        "extended_hours": False,\n        "instruction_source": (\n            "AFTER_CLOSE_DAILY_SIGNAL"\n        ),\n    }\n    _complete_pending_key(\n        state,\n        order_id,\n    )\n    state.pending_entry = None\n    state.revision += 1\n    state.validate()\n    return (\n        _entry_event(\n            state=state,\n            event_type=event_type,\n            event_date=event_date,\n            order_id=order_id,\n            details=details,\n        ),\n    )\n\n\ndef apply_pending_entry_regular_session(\n    state: PaperState,\n    *,\n    quote: OpeningQuote,\n    prior_close: float,\n    income_price: float,\n    bot_config: BotConfig,\n    execution_config: SessionExecutionConfig,\n) -> EntryOutcome:\n    bot_config.validate()\n    execution_config.validate()\n    state.validate()\n    quote.validate(execution_config)\n\n    pending = state.pending_entry\n\n    if pending is None:\n        raise ValueError(\n            "No staged entry instruction exists."\n        )\n\n    if state.position is not None:\n        raise ValueError(\n            "A pending entry cannot coexist with a position."\n        )\n\n    expected_session = next_market_session(\n        pending.signal_date\n    )\n\n    if quote.session_date != expected_session:\n        raise ValueError(\n            "Opening quote is not from the instruction\'s "\n            "next market session."\n        )\n\n    if quote.symbol.strip().upper() != pending.symbol:\n        raise ValueError(\n            "Opening quote symbol does not match instruction."\n        )\n\n    if prior_close <= 0 or income_price <= 0:\n        raise ValueError(\n            "Reference prices must be positive."\n        )\n\n    order_id = pending.order_id\n    gap_atr = (\n        abs(quote.open_price - prior_close)\n        / pending.signal_atr\n    )\n\n    common_details = {\n        "order_id": order_id,\n        "symbol": pending.symbol,\n        "signal_date": (\n            pending.signal_date.isoformat()\n        ),\n        "scheduled_session": (\n            quote.session_date.isoformat()\n        ),\n        "opening_reference_price": (\n            quote.open_price\n        ),\n        "prior_close": prior_close,\n        "opening_gap_atr": gap_atr,\n        "quote_source": quote.source,\n        "market_bar_time": (\n            quote.bar_time_market.isoformat()\n        ),\n        "recorded_at_utc": (\n            quote.observed_at_utc\n        ),\n        "execution_session": "REGULAR_SESSION",\n        "extended_hours": False,\n        "instruction_source": (\n            "AFTER_CLOSE_DAILY_SIGNAL"\n        ),\n    }\n\n    if (\n        gap_atr\n        > execution_config.maximum_gap_atr_multiple\n    ):\n        event_type = "ENTRY_REJECTED_OPENING_GAP"\n        details = {\n            **common_details,\n            "reason": (\n                "opening gap exceeded configured ATR limit"\n            ),\n            "maximum_gap_atr": (\n                execution_config.maximum_gap_atr_multiple\n            ),\n        }\n        _complete_pending_key(\n            state,\n            order_id,\n        )\n        state.pending_entry = None\n        state.revision += 1\n        state.validate()\n        event = _entry_event(\n            state=state,\n            event_type=event_type,\n            event_date=quote.session_date,\n            order_id=order_id,\n            details=details,\n        )\n        return EntryOutcome(\n            status="REJECTED_GAP",\n            message=details["reason"],\n            events=(event,),\n            quote_price=quote.open_price,\n            gap_atr_multiple=gap_atr,\n            fill_price=None,\n            shares=0,\n            stop_price=None,\n            target_price=None,\n        )\n\n    combined_equity = state.equity(\n        swing_price=quote.open_price,\n        income_price=income_price,\n    )\n    sizing = calculate_position_size(\n        account_equity=combined_equity,\n        available_cash=state.swing_cash,\n        entry_price=quote.open_price,\n        atr=pending.signal_atr,\n        active_risk=0.0,\n        config=bot_config,\n        trade_results_r=state.trade_results_r,\n    )\n\n    if sizing.is_tradeable:\n        cost = sizing.entry_fill * sizing.shares\n        state.swing_cash -= cost\n        state.position = PersistentPosition(\n            symbol=state.swing_symbol,\n            shares=sizing.shares,\n            entry_date=quote.session_date,\n            entry_price=sizing.entry_fill,\n            entry_atr=pending.signal_atr,\n            stop_price=sizing.stop_price,\n            target_price=sizing.target_price,\n            highest_price=sizing.entry_fill,\n        )\n        event_type = (\n            "ENTRY_FILLED_REGULAR_SESSION"\n        )\n        details = {\n            **common_details,\n            "shares": sizing.shares,\n            "fill_price": sizing.entry_fill,\n            "cost": cost,\n            "stop_price": sizing.stop_price,\n            "target_price": sizing.target_price,\n            "planned_risk": sizing.planned_risk,\n            "protection_policy": (\n                "PAPER_OHLC_RECONCILIATION;"\n                "FUTURE_LIVE_MODE_REQUIRES_BROKER_OCO"\n            ),\n        }\n        status = "FILLED"\n        message = (\n            "Staged instruction filled from the first "\n            "regular-session minute bar."\n        )\n        fill_price = sizing.entry_fill\n        shares = sizing.shares\n        stop_price = sizing.stop_price\n        target_price = sizing.target_price\n    else:\n        event_type = (\n            "ENTRY_REJECTED_POSITION_SIZING"\n        )\n        details = {\n            **common_details,\n            "reason": sizing.blocked_reason,\n            "available_cash": state.swing_cash,\n            "combined_equity": combined_equity,\n        }\n        status = "REJECTED_RISK"\n        message = (\n            sizing.blocked_reason\n            or "Position sizing rejected the instruction."\n        )\n        fill_price = None\n        shares = 0\n        stop_price = None\n        target_price = None\n\n    _complete_pending_key(\n        state,\n        order_id,\n    )\n    state.pending_entry = None\n    state.revision += 1\n    state.validate()\n    event = _entry_event(\n        state=state,\n        event_type=event_type,\n        event_date=quote.session_date,\n        order_id=order_id,\n        details=details,\n    )\n    return EntryOutcome(\n        status=status,\n        message=message,\n        events=(event,),\n        quote_price=quote.open_price,\n        gap_atr_multiple=gap_atr,\n        fill_price=fill_price,\n        shares=shares,\n        stop_price=stop_price,\n        target_price=target_price,\n    )\n\n\ndef _intraday_url(\n    host: str,\n    symbol: str,\n    config: SessionExecutionConfig,\n) -> str:\n    encoded = urllib.parse.quote(\n        symbol,\n        safe="",\n    )\n    query = urllib.parse.urlencode(\n        {\n            "range": config.intraday_range,\n            "interval": config.intraday_interval,\n            "includePrePost": "false",\n            "events": "div,splits",\n        }\n    )\n    return (\n        f"https://{host}/v8/finance/chart/"\n        f"{encoded}?{query}"\n    )\n\n\ndef _open_intraday_json(\n    url: str,\n    timeout_seconds: float,\n) -> Mapping[str, Any]:\n    request = urllib.request.Request(\n        url,\n        headers={\n            "User-Agent": (\n                "Mozilla/5.0 (Linux; Android 14) "\n                "AppleWebKit/537.36 QPXBot/1.13"\n            ),\n            "Accept": "application/json,text/plain,*/*",\n            "Accept-Encoding": "identity",\n            "Connection": "close",\n        },\n    )\n\n    with urllib.request.urlopen(\n        request,\n        timeout=timeout_seconds,\n    ) as response:\n        payload = json.loads(\n            response.read().decode("utf-8")\n        )\n\n    chart = payload.get("chart")\n\n    if not isinstance(chart, Mapping):\n        raise RuntimeError(\n            "Intraday chart response is missing."\n        )\n\n    if chart.get("error"):\n        raise RuntimeError(\n            f"Intraday provider error: {chart[\'error\']}"\n        )\n\n    results = chart.get("result")\n\n    if not isinstance(results, list) or not results:\n        raise RuntimeError(\n            "Intraday provider returned no result."\n        )\n\n    result = results[0]\n\n    if not isinstance(result, Mapping):\n        raise RuntimeError(\n            "Intraday provider result is invalid."\n        )\n\n    return result\n\n\ndef _as_sequence(value: Any) -> Sequence[Any]:\n    if (\n        isinstance(value, Sequence)\n        and not isinstance(\n            value,\n            (str, bytes),\n        )\n    ):\n        return value\n\n    return ()\n\n\ndef _extract_first_regular_open(\n    result: Mapping[str, Any],\n    *,\n    symbol: str,\n    session_date: date,\n    current: datetime,\n    config: SessionExecutionConfig,\n) -> OpeningQuote:\n    timestamps = _as_sequence(\n        result.get("timestamp")\n    )\n    indicators = result.get("indicators")\n\n    if not isinstance(indicators, Mapping):\n        raise RuntimeError(\n            "Intraday indicators are missing."\n        )\n\n    quotes = indicators.get("quote")\n\n    if not isinstance(quotes, list) or not quotes:\n        raise RuntimeError(\n            "Intraday quote arrays are missing."\n        )\n\n    quote_payload = quotes[0]\n\n    if not isinstance(quote_payload, Mapping):\n        raise RuntimeError(\n            "Intraday quote payload is invalid."\n        )\n\n    opens = _as_sequence(\n        quote_payload.get("open")\n    )\n    session_open = _parse_time(\n        config.regular_session_open\n    )\n    session_close = _parse_time(\n        config.regular_session_close\n    )\n    current_market = _market_now(current)\n\n    candidates: list[\n        tuple[datetime, float]\n    ] = []\n\n    for index, raw_timestamp in enumerate(\n        timestamps\n    ):\n        if (\n            raw_timestamp is None\n            or index >= len(opens)\n            or opens[index] is None\n        ):\n            continue\n\n        market_time = datetime.fromtimestamp(\n            float(raw_timestamp),\n            tz=timezone.utc,\n        ).astimezone(NEW_YORK)\n        wall_clock = market_time.time().replace(\n            tzinfo=None\n        )\n\n        if market_time.date() != session_date:\n            continue\n\n        if market_time > current_market:\n            continue\n\n        if not (\n            session_open\n            <= wall_clock\n            < session_close\n        ):\n            continue\n\n        price = float(opens[index])\n\n        if price > 0:\n            candidates.append(\n                (market_time, price)\n            )\n\n    if not candidates:\n        raise RuntimeError(\n            "The first regular-session minute bar "\n            "is not available yet."\n        )\n\n    candidates.sort(\n        key=lambda item: item[0]\n    )\n    bar_time, price = candidates[0]\n    quote = OpeningQuote(\n        symbol=symbol.strip().upper(),\n        session_date=session_date,\n        bar_time_market=bar_time,\n        observed_at_utc=datetime.now(\n            timezone.utc\n        ).isoformat(),\n        open_price=price,\n        source=(\n            "YAHOO_FIRST_1M_REGULAR_SESSION_BAR"\n        ),\n        extended_hours=False,\n    )\n    quote.validate(config)\n    return quote\n\n\ndef fetch_opening_quote(\n    symbol: str,\n    current: datetime,\n    config: SessionExecutionConfig,\n) -> OpeningQuote:\n    normalized = symbol.strip().upper()\n\n    if not normalized:\n        raise ValueError(\n            "Quote symbol cannot be empty."\n        )\n\n    current_market = _market_now(current)\n    errors: list[str] = []\n\n    for attempt in range(\n        1,\n        config.maximum_quote_attempts + 1,\n    ):\n        host = YAHOO_HOSTS[\n            (attempt - 1) % len(YAHOO_HOSTS)\n        ]\n        url = _intraday_url(\n            host,\n            normalized,\n            config,\n        )\n\n        try:\n            result = _open_intraday_json(\n                url,\n                config.quote_timeout_seconds,\n            )\n            return _extract_first_regular_open(\n                result,\n                symbol=normalized,\n                session_date=current_market.date(),\n                current=current_market,\n                config=config,\n            )\n        except (\n            RuntimeError,\n            urllib.error.HTTPError,\n            urllib.error.URLError,\n            TimeoutError,\n            OSError,\n            UnicodeDecodeError,\n            json.JSONDecodeError,\n        ) as exc:\n            errors.append(\n                f"attempt {attempt} via {host}: "\n                f"{type(exc).__name__}: {exc}"\n            )\n\n            if (\n                attempt\n                < config.maximum_quote_attempts\n            ):\n                time.sleep(\n                    min(6.0, float(attempt))\n                )\n\n    raise RuntimeError(\n        "Unable to obtain the first regular-session "\n        f"bar for {normalized}.\\n"\n        + "\\n".join(errors)\n    )\n\n\ndef _latest_price_on_or_before(\n    candles,\n    day: date,\n) -> float:\n    selected = None\n\n    for candle in candles:\n        if candle.date > day:\n            break\n        selected = candle\n\n    if selected is None:\n        raise RuntimeError(\n            f"No market price exists on or before {day}."\n        )\n\n    return float(selected.close)\n\n\ndef _build_report(\n    *,\n    current: datetime,\n    status: str,\n    message: str,\n    phase: str,\n    state: PaperState | None,\n    expected_session: date | None,\n    quote: OpeningQuote | None = None,\n    outcome: EntryOutcome | None = None,\n) -> SessionExecutionReport:\n    pending = (\n        state.pending_entry\n        if state is not None\n        else None\n    )\n    return SessionExecutionReport(\n        generated_at_utc=datetime.now(\n            timezone.utc\n        ).isoformat(),\n        market_time=_market_now(\n            current\n        ).isoformat(),\n        status=status,\n        message=message,\n        market_phase=phase,\n        expected_session=(\n            expected_session.isoformat()\n            if expected_session\n            else None\n        ),\n        signal_date=(\n            pending.signal_date.isoformat()\n            if pending\n            else None\n        ),\n        pending_order_id=(\n            pending.order_id\n            if pending\n            else None\n        ),\n        symbol=(\n            (\n                quote.symbol\n                if quote\n                else state.swing_symbol\n            )\n            if state\n            else None\n        ),\n        quote_source=(\n            quote.source\n            if quote\n            else None\n        ),\n        opening_price=(\n            quote.open_price\n            if quote\n            else None\n        ),\n        opening_gap_atr=(\n            outcome.gap_atr_multiple\n            if outcome\n            else None\n        ),\n        fill_price=(\n            outcome.fill_price\n            if outcome\n            else None\n        ),\n        shares=(\n            outcome.shares\n            if outcome\n            else 0\n        ),\n        stop_price=(\n            outcome.stop_price\n            if outcome\n            else None\n        ),\n        target_price=(\n            outcome.target_price\n            if outcome\n            else None\n        ),\n        extended_hours=False,\n        mode="SIMULATED_REGULAR_SESSION_ONLY",\n    )\n\n\ndef execute_regular_session(\n    *,\n    config: SessionExecutionConfig,\n    paper_runtime: str | Path,\n    input_directory: str | Path,\n    report_directory: str | Path,\n    current: datetime | None = None,\n    check_only: bool = False,\n    quote_provider: QuoteProvider = fetch_opening_quote,\n) -> tuple[int, SessionExecutionReport]:\n    moment = _market_now(current)\n    phase = session_phase(\n        moment,\n        config,\n    )\n    store = StateStore(paper_runtime)\n    report_path = Path(\n        report_directory\n    ).expanduser().resolve()\n\n    with store.locked():\n        if store.kill_switch_active():\n            report = _build_report(\n                current=moment,\n                status="PAUSED",\n                message=(\n                    "Paper kill switch is active."\n                ),\n                phase=phase,\n                state=(\n                    store.load()\n                    if store.exists()\n                    else None\n                ),\n                expected_session=None,\n            )\n            write_session_report(\n                report,\n                report_path,\n            )\n            return 4, report\n\n        if not store.exists():\n            report = _build_report(\n                current=moment,\n                status="NO_ACCOUNT",\n                message=(\n                    "Persistent paper account does not exist."\n                ),\n                phase=phase,\n                state=None,\n                expected_session=None,\n            )\n            write_session_report(\n                report,\n                report_path,\n            )\n            return 0, report\n\n        state = store.load()\n        store.verify_journal()\n        pending = state.pending_entry\n        expected_session = (\n            next_market_session(\n                pending.signal_date\n            )\n            if pending\n            else None\n        )\n\n        if check_only:\n            report = _build_report(\n                current=moment,\n                status="CHECK_ONLY",\n                message=(\n                    "Regular-session execution snapshot "\n                    "completed without mutation."\n                ),\n                phase=phase,\n                state=state,\n                expected_session=expected_session,\n            )\n            write_session_report(\n                report,\n                report_path,\n            )\n            return 0, report\n\n        if pending is None:\n            report = _build_report(\n                current=moment,\n                status="NO_PENDING",\n                message=(\n                    "No staged entry instruction exists."\n                ),\n                phase=phase,\n                state=state,\n                expected_session=None,\n            )\n            write_session_report(\n                report,\n                report_path,\n            )\n            return 0, report\n\n        assert expected_session is not None\n\n        if moment.date() < expected_session:\n            report = _build_report(\n                current=moment,\n                status="WAITING",\n                message=(\n                    "Instruction is waiting for its next "\n                    "market session."\n                ),\n                phase=phase,\n                state=state,\n                expected_session=expected_session,\n            )\n            write_session_report(\n                report,\n                report_path,\n            )\n            return 0, report\n\n        if moment.date() > expected_session:\n            order_id = pending.order_id\n            events = cancel_pending_instruction(\n                state,\n                event_date=moment.date(),\n                event_type=(\n                    "ENTRY_CANCELLED_STALE_SESSION"\n                ),\n                reason=(\n                    "instruction was not executed during "\n                    "its scheduled market session"\n                ),\n            )\n            store.append_events(\n                list(events)\n            )\n            store.save(state)\n            report = _build_report(\n                current=moment,\n                status="CANCELLED_STALE",\n                message=(\n                    "Stale staged instruction was cancelled."\n                ),\n                phase=phase,\n                state=state,\n                expected_session=expected_session,\n            )\n            report = SessionExecutionReport(\n                **{\n                    **asdict(report),\n                    "pending_order_id": order_id,\n                }\n            )\n            write_session_report(\n                report,\n                report_path,\n            )\n            return 0, report\n\n        if phase in {\n            "PRE_MARKET",\n            "OPENING_DELAY",\n        }:\n            report = _build_report(\n                current=moment,\n                status="WAITING",\n                message=(\n                    "Waiting for the regular-session "\n                    "opening execution window."\n                ),\n                phase=phase,\n                state=state,\n                expected_session=expected_session,\n            )\n            write_session_report(\n                report,\n                report_path,\n            )\n            return 0, report\n\n        if phase != "OPENING_WINDOW":\n            order_id = pending.order_id\n            events = cancel_pending_instruction(\n                state,\n                event_date=moment.date(),\n                event_type=(\n                    "ENTRY_CANCELLED_MISSED_WINDOW"\n                ),\n                reason=(\n                    "regular-session opening window expired; "\n                    "after-hours backfill is prohibited"\n                ),\n            )\n            store.append_events(\n                list(events)\n            )\n            store.save(state)\n            report = _build_report(\n                current=moment,\n                status="CANCELLED_EXPIRED",\n                message=(\n                    "Missed opening-window instruction "\n                    "was cancelled instead of backfilled."\n                ),\n                phase=phase,\n                state=state,\n                expected_session=expected_session,\n            )\n            report = SessionExecutionReport(\n                **{\n                    **asdict(report),\n                    "pending_order_id": order_id,\n                }\n            )\n            write_session_report(\n                report,\n                report_path,\n            )\n            return 0, report\n\n        try:\n            quote = quote_provider(\n                pending.symbol,\n                moment,\n                config,\n            )\n            quote.validate(config)\n            input_path = Path(\n                input_directory\n            ).expanduser().resolve()\n            swing = load_market_csv(\n                input_path / "SWING.csv"\n            )\n            income = load_market_csv(\n                input_path / "QDTE.csv"\n            )\n            prior_close = (\n                _latest_price_on_or_before(\n                    swing,\n                    pending.signal_date,\n                )\n            )\n            income_price = (\n                _latest_price_on_or_before(\n                    income,\n                    moment.date(),\n                )\n            )\n            outcome = (\n                apply_pending_entry_regular_session(\n                    state,\n                    quote=quote,\n                    prior_close=prior_close,\n                    income_price=income_price,\n                    bot_config=BotConfig(),\n                    execution_config=config,\n                )\n            )\n        except Exception as exc:\n            report = _build_report(\n                current=moment,\n                status="QUOTE_RETRY",\n                message=(\n                    f"{type(exc).__name__}: {exc}"\n                ),\n                phase=phase,\n                state=state,\n                expected_session=expected_session,\n            )\n            write_session_report(\n                report,\n                report_path,\n            )\n            return 5, report\n\n        store.append_events(\n            list(outcome.events)\n        )\n        store.save(state)\n        report = _build_report(\n            current=moment,\n            status=outcome.status,\n            message=outcome.message,\n            phase=phase,\n            state=state,\n            expected_session=expected_session,\n            quote=quote,\n            outcome=outcome,\n        )\n        report = SessionExecutionReport(\n            **{\n                **asdict(report),\n                "signal_date": (\n                    pending.signal_date.isoformat()\n                ),\n                "pending_order_id": (\n                    pending.order_id\n                ),\n            }\n        )\n        write_session_report(\n            report,\n            report_path,\n        )\n        return 0, report\n\n\ndef _parser() -> argparse.ArgumentParser:\n    parser = argparse.ArgumentParser(\n        description=(\n            "Execute staged QPX paper entries only during "\n            "the next regular-session opening window."\n        )\n    )\n    parser.add_argument(\n        "--config",\n        default=str(DEFAULT_CONFIG_PATH),\n    )\n    parser.add_argument(\n        "--paper-runtime-dir",\n        default=str(DEFAULT_PAPER_RUNTIME),\n    )\n    parser.add_argument(\n        "--input-dir",\n        default=str(DEFAULT_INPUT_DIR),\n    )\n    parser.add_argument(\n        "--report-dir",\n        default=str(DEFAULT_REPORT_DIR),\n    )\n    parser.add_argument(\n        "--check-only",\n        action="store_true",\n    )\n    return parser\n\n\ndef main(argv: Sequence[str] | None = None) -> int:\n    args = _parser().parse_args(argv)\n    config = load_session_execution_config(\n        args.config\n    )\n    code, report = execute_regular_session(\n        config=config,\n        paper_runtime=args.paper_runtime_dir,\n        input_directory=args.input_dir,\n        report_directory=args.report_dir,\n        check_only=args.check_only,\n    )\n    print(_report_text(report))\n    return code\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n',
    "QPX_RUN_REGULAR_SESSION.py": '#!/usr/bin/env python3\n"""Run regular-session-only staged paper execution."""\n\nfrom qpx_bot.session_execution import main\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n',
    "QPX_TERMUX_SESSION.sh": '#!/data/data/com.termux/files/usr/bin/sh\n\nset -u\n\nROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"\nPREFIX_PATH="${PREFIX:-/data/data/com.termux/files/usr}"\nPYTHON_BIN="${PREFIX_PATH}/bin/python"\nLOG_DIR="${ROOT}/logs"\nLOG_FILE="${LOG_DIR}/qpx_regular_session.log"\n\nmkdir -p "${LOG_DIR}"\n\nwake_locked=0\n\nif command -v termux-wake-lock >/dev/null 2>&1; then\n    termux-wake-lock >/dev/null 2>&1 || true\n    wake_locked=1\nfi\n\ncd "${ROOT}" || exit 1\n"${PYTHON_BIN}" QPX_RUN_REGULAR_SESSION.py >>"${LOG_FILE}" 2>&1\nstatus=$?\n\nif [ "${wake_locked}" -eq 1 ] \\\n    && command -v termux-wake-unlock >/dev/null 2>&1; then\n    termux-wake-unlock >/dev/null 2>&1 || true\nfi\n\nexit "${status}"\n',
    "qpx_bot/schedule.py": '"""Install and manage local Termux schedules for QPX."""\n\nfrom __future__ import annotations\n\nimport json\nimport os\nimport shutil\nimport subprocess\nfrom datetime import datetime, timezone\nfrom pathlib import Path\nfrom typing import Sequence\n\n\nPACKAGE_DIR = Path(__file__).resolve().parent\nPROJECT_ROOT = PACKAGE_DIR.parent\nRUNTIME_DIR = PACKAGE_DIR / "operations_runtime"\nCRON_BEGIN = "# QPX DAILY OPERATIONS BEGIN"\nCRON_END = "# QPX DAILY OPERATIONS END"\n\n\ndef remove_qpx_cron_block(content: str) -> str:\n    output: list[str] = []\n    inside = False\n\n    for line in content.splitlines():\n        if line.strip() == CRON_BEGIN:\n            inside = True\n            continue\n\n        if line.strip() == CRON_END:\n            inside = False\n            continue\n\n        if not inside:\n            output.append(line)\n\n    while output and not output[-1].strip():\n        output.pop()\n\n    return "\\n".join(output)\n\n\ndef _cron_command(\n    script: Path,\n    *,\n    home: Path,\n    prefix: Path,\n) -> str:\n    return (\n        f\'HOME="{home}" \'\n        f\'PATH="{prefix / "bin"}:/system/bin" \'\n        f\'"{script}"\'\n    )\n\n\ndef build_qpx_cron_block(\n    script_path: str | Path,\n    *,\n    home: str | Path,\n    prefix: str | Path,\n) -> str:\n    analysis_script = Path(\n        script_path\n    ).expanduser().resolve()\n    session_script = analysis_script.with_name(\n        "QPX_TERMUX_SESSION.sh"\n    )\n    home_path = Path(\n        home\n    ).expanduser().resolve()\n    prefix_path = Path(\n        prefix\n    ).expanduser().resolve()\n    session_command = _cron_command(\n        session_script,\n        home=home_path,\n        prefix=prefix_path,\n    )\n    analysis_command = _cron_command(\n        analysis_script,\n        home=home_path,\n        prefix=prefix_path,\n    )\n\n    return "\\n".join(\n        [\n            CRON_BEGIN,\n            (\n                "# Regular-session checks. Python gates "\n                "execution to 09:35-10:30 New York time."\n            ),\n            (\n                f"*/15 6-12 * * 1-5 "\n                f"{session_command}"\n            ),\n            (\n                "# After-close analysis. This job stages "\n                "instructions but cannot fill entries."\n            ),\n            (\n                f"15 16-23 * * 1-5 "\n                f"{analysis_command}"\n            ),\n            CRON_END,\n        ]\n    )\n\n\ndef _current_crontab() -> str:\n    completed = subprocess.run(\n        ["crontab", "-l"],\n        text=True,\n        stdout=subprocess.PIPE,\n        stderr=subprocess.DEVNULL,\n    )\n\n    if completed.returncode != 0:\n        return ""\n\n    return completed.stdout\n\n\ndef _write_crontab(content: str) -> None:\n    subprocess.run(\n        ["crontab", "-"],\n        input=content,\n        text=True,\n        check=True,\n    )\n\n\ndef _ensure_cronie() -> None:\n    if (\n        shutil.which("crontab")\n        and shutil.which("crond")\n    ):\n        return\n\n    pkg = shutil.which("pkg")\n\n    if pkg is None:\n        raise RuntimeError(\n            "Termux pkg command was not found; "\n            "cannot install cronie."\n        )\n\n    subprocess.run(\n        [pkg, "install", "-y", "cronie"],\n        check=True,\n    )\n\n    if (\n        not shutil.which("crontab")\n        or not shutil.which("crond")\n    ):\n        raise RuntimeError(\n            "cronie installed but cron commands "\n            "remain unavailable."\n        )\n\n\ndef _start_crond() -> None:\n    pgrep = shutil.which("pgrep")\n\n    if pgrep is not None:\n        running = subprocess.run(\n            [pgrep, "-x", "crond"],\n            stdout=subprocess.DEVNULL,\n            stderr=subprocess.DEVNULL,\n        )\n\n        if running.returncode == 0:\n            return\n\n    subprocess.run(\n        ["crond"],\n        check=True,\n    )\n\n\ndef _write_boot_script(prefix: Path) -> Path:\n    boot_directory = (\n        Path.home() / ".termux" / "boot"\n    )\n    boot_directory.mkdir(\n        parents=True,\n        exist_ok=True,\n    )\n    path = (\n        boot_directory / "qpx-start-crond.sh"\n    )\n    path.write_text(\n        (\n            f"#!{prefix / \'bin\' / \'sh\'}\\n"\n            f\'export PATH="{prefix / "bin"}:\'\n            \'/system/bin:$PATH"\\n\'\n            "pgrep -x crond >/dev/null 2>&1 "\n            "|| crond\\n"\n        ),\n        encoding="utf-8",\n    )\n    path.chmod(0o700)\n    return path\n\n\ndef _write_scheduler_status(\n    *,\n    backend: str,\n    installed: bool,\n    script_path: Path,\n    boot_script: Path | None,\n) -> Path:\n    RUNTIME_DIR.mkdir(\n        parents=True,\n        exist_ok=True,\n    )\n    path = RUNTIME_DIR / "scheduler.json"\n    payload = {\n        "backend": backend,\n        "installed": installed,\n        "analysis_script": str(script_path),\n        "session_script": str(\n            script_path.with_name(\n                "QPX_TERMUX_SESSION.sh"\n            )\n        ),\n        "boot_script": (\n            str(boot_script)\n            if boot_script\n            else None\n        ),\n        "regular_session_schedule": (\n            "*/15 6-12 * * 1-5"\n        ),\n        "regular_session_gate": (\n            "09:35-10:30 America/New_York"\n        ),\n        "extended_hours": False,\n        "analysis_schedule": (\n            "15 16-23 * * 1-5"\n        ),\n        "analysis_gate": (\n            "17:15 America/New_York"\n        ),\n        "timezone": "device local time",\n        "updated_at_utc": datetime.now(\n            timezone.utc\n        ).isoformat(),\n    }\n    temporary = path.with_suffix(\n        ".json.tmp"\n    )\n    temporary.write_text(\n        json.dumps(payload, indent=2) + "\\n",\n        encoding="utf-8",\n    )\n    temporary.replace(path)\n    return path\n\n\ndef install_schedule(\n    script_path: str | Path,\n) -> Path:\n    _ensure_cronie()\n    script = Path(\n        script_path\n    ).expanduser().resolve()\n    session_script = script.with_name(\n        "QPX_TERMUX_SESSION.sh"\n    )\n\n    if not script.exists():\n        raise FileNotFoundError(script)\n\n    if not session_script.exists():\n        raise FileNotFoundError(\n            session_script\n        )\n\n    script.chmod(0o700)\n    session_script.chmod(0o700)\n    prefix = Path(\n        os.environ.get(\n            "PREFIX",\n            "/data/data/com.termux/files/usr",\n        )\n    )\n    cleaned = remove_qpx_cron_block(\n        _current_crontab()\n    )\n    block = build_qpx_cron_block(\n        script,\n        home=Path.home(),\n        prefix=prefix,\n    )\n    updated = (\n        (cleaned + "\\n\\n" if cleaned else "")\n        + block\n        + "\\n"\n    )\n    _write_crontab(updated)\n    _start_crond()\n    boot_script = _write_boot_script(\n        prefix\n    )\n    return _write_scheduler_status(\n        backend="cronie",\n        installed=True,\n        script_path=script,\n        boot_script=boot_script,\n    )\n\n\ndef remove_schedule(\n    script_path: str | Path,\n) -> Path:\n    _ensure_cronie()\n    cleaned = remove_qpx_cron_block(\n        _current_crontab()\n    )\n    _write_crontab(\n        cleaned + ("\\n" if cleaned else "")\n    )\n    return _write_scheduler_status(\n        backend="cronie",\n        installed=False,\n        script_path=Path(\n            script_path\n        ).expanduser().resolve(),\n        boot_script=None,\n    )\n\n\ndef _parser():\n    import argparse\n\n    parser = argparse.ArgumentParser(\n        description=(\n            "Install or remove QPX regular-session "\n            "and after-close schedules."\n        )\n    )\n    action = parser.add_mutually_exclusive_group()\n    action.add_argument(\n        "--install",\n        action="store_true",\n    )\n    action.add_argument(\n        "--remove",\n        action="store_true",\n    )\n    parser.add_argument(\n        "--script",\n        default=str(\n            PROJECT_ROOT / "QPX_TERMUX_DAILY.sh"\n        ),\n    )\n    return parser\n\n\ndef main(\n    argv: Sequence[str] | None = None,\n) -> int:\n    args = _parser().parse_args(argv)\n\n    if args.remove:\n        status = remove_schedule(\n            args.script\n        )\n        print(\n            f"QPX schedules removed: {status}"\n        )\n        return 0\n\n    status = install_schedule(\n        args.script\n    )\n    print(\n        f"QPX schedules installed: {status}"\n    )\n    print(\n        "Regular-session checks are gated to "\n        "09:35-10:30 New York time. After-close "\n        "jobs analyze completed bars only. "\n        "Extended-hours execution is disabled."\n    )\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n',
    "tests/test_qpx_bot_paper_trading.py": 'from dataclasses import replace\nfrom datetime import date, datetime, time, timedelta, timezone\nfrom pathlib import Path\nfrom tempfile import TemporaryDirectory\n\nfrom qpx_bot.config import BotConfig\nfrom qpx_bot.data_loader import Candle\nfrom qpx_bot.dividends import DividendEvent\nfrom qpx_bot.indicators import calculate_indicators\nfrom qpx_bot.market_calendar import NEW_YORK\nfrom qpx_bot.paper_engine import (\n    create_initial_state,\n    process_paper_day,\n    reconcile_state,\n)\nfrom qpx_bot.paper_state import StateStore\nfrom qpx_bot.session_execution import (\n    OpeningQuote,\n    SessionExecutionConfig,\n    apply_pending_entry_regular_session,\n)\n\n\nconfig = replace(\n    BotConfig(),\n    starting_cash=10_000.0,\n    monthly_contribution=500.0,\n    ema_fast_period=2,\n    ema_slow_period=3,\n    rsi_period=3,\n    rmi_period=3,\n    rmi_momentum=2,\n    sma_trend_period=5,\n    sma_slope_lookback=2,\n    atr_period=3,\n    average_volume_period=3,\n    breakout_lookback=3,\n    minimum_average_daily_volume=1_000,\n)\n\nexecution_config = SessionExecutionConfig(\n    schema_version=1,\n    market_timezone="America/New_York",\n    regular_session_open="09:30",\n    opening_window_start="09:35",\n    opening_window_end="10:30",\n    regular_session_close="16:00",\n    intraday_interval="1m",\n    intraday_range="1d",\n    maximum_gap_atr_multiple=10.0,\n    maximum_quote_attempts=1,\n    quote_timeout_seconds=1.0,\n    extended_hours_enabled=False,\n)\nexecution_config.validate()\n\nstart = date(2024, 1, 2)\nswing = []\nincome = []\n\nfor index in range(80):\n    day = start + timedelta(days=index)\n    swing_price = 100.0 + (index * 0.10)\n    income_price = 40.0 + (index * 0.03)\n\n    swing.append(\n        Candle(\n            date=day,\n            open=swing_price,\n            high=swing_price + 1.0,\n            low=swing_price - 1.0,\n            close=swing_price + 0.20,\n            volume=3_000_000,\n        )\n    )\n    income.append(\n        Candle(\n            date=day,\n            open=income_price,\n            high=income_price + 0.50,\n            low=income_price - 0.50,\n            close=income_price + 0.10,\n            volume=1_500_000,\n        )\n    )\n\nvix = [20.0] * len(swing)\ndividends = [\n    DividendEvent(\n        date=swing[21].date,\n        amount_per_share=0.20,\n    )\n]\nindicators = calculate_indicators(\n    swing,\n    config,\n)\n\nstate, initialized = create_initial_state(\n    swing_symbol="TEST",\n    income_symbol="QDTE",\n    start_date=swing[20].date,\n    income_price=income[20].close,\n    config=config,\n)\n\nevents = process_paper_day(\n    state=state,\n    swing_candles=swing,\n    income_candles=income,\n    dividends=dividends,\n    indicators=indicators,\n    vix_values=vix,\n    index=20,\n    config=config,\n    forced_entry=True,\n)\n\nassert state.pending_entry is not None\nassert state.position is None\nassert any(\n    event.event_type == "ENTRY_SIGNAL"\n    for event in events\n)\n\nquote_time = datetime.combine(\n    swing[21].date,\n    time(9, 30),\n    tzinfo=NEW_YORK,\n)\nquote = OpeningQuote(\n    symbol="TEST",\n    session_date=swing[21].date,\n    bar_time_market=quote_time,\n    observed_at_utc=datetime.now(\n        timezone.utc\n    ).isoformat(),\n    open_price=swing[21].open,\n    source="TEST_FIRST_REGULAR_BAR",\n    extended_hours=False,\n)\nfill_outcome = (\n    apply_pending_entry_regular_session(\n        state,\n        quote=quote,\n        prior_close=swing[20].close,\n        income_price=income[21].open,\n        bot_config=config,\n        execution_config=execution_config,\n    )\n)\n\nassert fill_outcome.status == "FILLED"\nassert state.pending_entry is None\nassert state.position is not None\nassert len(state.completed_order_keys) == 1\nassert any(\n    event.event_type\n    == "ENTRY_FILLED_REGULAR_SESSION"\n    for event in fill_outcome.events\n)\nassert all(\n    not event.details["extended_hours"]\n    for event in fill_outcome.events\n)\n\nevents = process_paper_day(\n    state=state,\n    swing_candles=swing,\n    income_candles=income,\n    dividends=dividends,\n    indicators=indicators,\n    vix_values=vix,\n    index=21,\n    config=config,\n    forced_entry=False,\n)\n\nassert state.position is not None\nassert state.dividends_received > 0\nassert not any(\n    event.event_type == "ENTRY_FILLED"\n    for event in events\n)\n\nrevision_before_duplicate = state.revision\nduplicate_events = process_paper_day(\n    state=state,\n    swing_candles=swing,\n    income_candles=income,\n    dividends=dividends,\n    indicators=indicators,\n    vix_values=vix,\n    index=21,\n    config=config,\n    forced_entry=True,\n)\nassert duplicate_events == []\nassert state.revision == revision_before_duplicate\nassert len(state.completed_order_keys) == 1\n\nassert state.position is not None\ntarget = state.position.target_price\nswing[22] = replace(\n    swing[22],\n    high=target + 1.0,\n    close=max(\n        swing[22].close,\n        target,\n    ),\n)\nindicators = calculate_indicators(\n    swing,\n    config,\n)\n\nevents = process_paper_day(\n    state=state,\n    swing_candles=swing,\n    income_candles=income,\n    dividends=dividends,\n    indicators=indicators,\n    vix_values=vix,\n    index=22,\n    config=config,\n    forced_entry=False,\n)\n\nassert state.position is None\nassert state.realized_pnl > 0\nassert state.tax_reserve_cash > 0\nassert len(state.trade_results_r) == 1\nassert any(\n    event.event_type == "EXIT_FILLED"\n    for event in events\n)\nassert all(\n    event.details.get(\n        "extended_hours",\n        False,\n    )\n    is False\n    for event in events\n)\n\nevents = process_paper_day(\n    state=state,\n    swing_candles=swing,\n    income_candles=income,\n    dividends=dividends,\n    indicators=indicators,\n    vix_values=vix,\n    index=31,\n    config=config,\n    forced_entry=False,\n)\nassert state.total_contributions == 10_500.0\nassert any(\n    event.event_type\n    == "MONTHLY_CONTRIBUTION"\n    for event in events\n)\n\nreconciliation = reconcile_state(\n    state,\n    swing_price=swing[31].close,\n    income_price=income[31].close,\n)\nassert reconciliation["total_equity"] > 0\n\nwith TemporaryDirectory() as temporary_directory:\n    store = StateStore(\n        Path(temporary_directory)\n    )\n    store.save(state)\n    loaded = store.load()\n\n    assert loaded.state_id == state.state_id\n    assert loaded.revision == state.revision\n    assert (\n        loaded.completed_order_keys\n        == state.completed_order_keys\n    )\n\n    appended = store.append_events(\n        [\n            initialized,\n            *fill_outcome.events,\n            *events,\n        ]\n    )\n    assert appended >= 1\n    first_count = (\n        store.verify_journal()[2]\n    )\n\n    store.append_events(\n        [\n            initialized,\n            *fill_outcome.events,\n            *events,\n        ]\n    )\n    assert (\n        store.verify_journal()[2]\n        == first_count\n    )\n\n    store.activate_kill_switch(\n        "test"\n    )\n    assert store.kill_switch_active()\n    store.deactivate_kill_switch()\n    assert not store.kill_switch_active()\n\n    with store.locked():\n        assert store.lock_path.exists()\n    assert not store.lock_path.exists()\n\nprint(\n    "QPX Bot Persistent Paper Trading PASS"\n)\n',
    "tests/test_qpx_bot_regular_session_execution.py": 'import json\nfrom datetime import date, datetime, time, timezone\nfrom pathlib import Path\nfrom tempfile import TemporaryDirectory\n\nfrom qpx_bot.market_calendar import (\n    NEW_YORK,\n    next_market_session,\n)\nfrom qpx_bot.paper_state import (\n    PaperState,\n    PendingEntry,\n    StateStore,\n)\nfrom qpx_bot.schedule import (\n    build_qpx_cron_block,\n)\nfrom qpx_bot.session_execution import (\n    OpeningQuote,\n    SessionExecutionConfig,\n    execute_regular_session,\n    session_phase,\n)\n\n\nconfig = SessionExecutionConfig(\n    schema_version=1,\n    market_timezone="America/New_York",\n    regular_session_open="09:30",\n    opening_window_start="09:35",\n    opening_window_end="10:30",\n    regular_session_close="16:00",\n    intraday_interval="1m",\n    intraday_range="1d",\n    maximum_gap_atr_multiple=1.5,\n    maximum_quote_attempts=1,\n    quote_timeout_seconds=1.0,\n    extended_hours_enabled=False,\n)\nconfig.validate()\n\nassert next_market_session(\n    date(2026, 8, 6)\n) == date(2026, 8, 7)\n\nopening_time = datetime(\n    2026,\n    8,\n    7,\n    9,\n    45,\n    tzinfo=NEW_YORK,\n)\nassert (\n    session_phase(\n        opening_time,\n        config,\n    )\n    == "OPENING_WINDOW"\n)\nassert (\n    session_phase(\n        datetime(\n            2026,\n            8,\n            7,\n            8,\n            0,\n            tzinfo=NEW_YORK,\n        ),\n        config,\n    )\n    == "PRE_MARKET"\n)\nassert (\n    session_phase(\n        datetime(\n            2026,\n            8,\n            7,\n            17,\n            0,\n            tzinfo=NEW_YORK,\n        ),\n        config,\n    )\n    == "AFTER_HOURS"\n)\n\nwith TemporaryDirectory() as temporary_directory:\n    root = Path(temporary_directory)\n    paper_runtime = (\n        root / "paper_runtime"\n    )\n    input_directory = (\n        root / "data_inputs"\n    )\n    report_directory = (\n        root / "reports"\n    )\n    input_directory.mkdir(\n        parents=True,\n        exist_ok=True,\n    )\n\n    (input_directory / "SWING.csv").write_text(\n        (\n            "Date,Open,High,Low,Close,Volume\\n"\n            "2026-08-06,100,101,99,100,3000000\\n"\n        ),\n        encoding="utf-8",\n    )\n    (input_directory / "QDTE.csv").write_text(\n        (\n            "Date,Open,High,Low,Close,Volume\\n"\n            "2026-08-06,40,41,39,40,1500000\\n"\n        ),\n        encoding="utf-8",\n    )\n\n    store = StateStore(paper_runtime)\n    state = PaperState(\n        state_id="regular-session-test",\n        swing_symbol="XLK",\n        income_symbol="QDTE",\n        start_date=date(2026, 8, 1),\n        starting_cash=10_000.0,\n        swing_cash=6_000.0,\n        tax_reserve_cash=0.0,\n        total_contributions=10_000.0,\n        realized_pnl=0.0,\n        income_shares=100.0,\n        income_cost=4_000.0,\n        dividends_received=0.0,\n        last_processed_date=date(2026, 8, 6),\n        pending_entry=PendingEntry(\n            order_id="entry-test-1",\n            symbol="XLK",\n            signal_date=date(2026, 8, 6),\n            signal_atr=2.0,\n        ),\n        revision=2,\n    )\n    store.save(state)\n\n    def quote_provider(\n        symbol,\n        current,\n        execution_config,\n    ):\n        return OpeningQuote(\n            symbol=symbol,\n            session_date=date(2026, 8, 7),\n            bar_time_market=datetime.combine(\n                date(2026, 8, 7),\n                time(9, 30),\n                tzinfo=NEW_YORK,\n            ),\n            observed_at_utc=datetime.now(\n                timezone.utc\n            ).isoformat(),\n            open_price=101.0,\n            source="TEST_REGULAR_SESSION",\n            extended_hours=False,\n        )\n\n    code, report = execute_regular_session(\n        config=config,\n        paper_runtime=paper_runtime,\n        input_directory=input_directory,\n        report_directory=report_directory,\n        current=opening_time,\n        quote_provider=quote_provider,\n    )\n    assert code == 0\n    assert report.status == "FILLED"\n    assert report.extended_hours is False\n    assert report.market_phase == "OPENING_WINDOW"\n\n    reloaded = store.load()\n    assert reloaded.pending_entry is None\n    assert reloaded.position is not None\n    assert reloaded.position.entry_date == date(\n        2026,\n        8,\n        7,\n    )\n    event_ids, _, records = (\n        store.verify_journal()\n    )\n    assert records == 1\n    assert event_ids\n\n    payload = json.loads(\n        (\n            report_directory\n            / "latest_session_execution.json"\n        ).read_text(encoding="utf-8")\n    )\n    assert payload["extended_hours"] is False\n    assert (\n        payload["mode"]\n        == "SIMULATED_REGULAR_SESSION_ONLY"\n    )\n\n    code, check = execute_regular_session(\n        config=config,\n        paper_runtime=paper_runtime,\n        input_directory=input_directory,\n        report_directory=report_directory,\n        current=opening_time,\n        check_only=True,\n        quote_provider=quote_provider,\n    )\n    assert code == 0\n    assert check.status == "CHECK_ONLY"\n\n    analysis_script = (\n        root / "QPX_TERMUX_DAILY.sh"\n    )\n    analysis_script.write_text(\n        "#!/bin/sh\\n",\n        encoding="utf-8",\n    )\n    session_script = (\n        root / "QPX_TERMUX_SESSION.sh"\n    )\n    session_script.write_text(\n        "#!/bin/sh\\n",\n        encoding="utf-8",\n    )\n    block = build_qpx_cron_block(\n        analysis_script,\n        home=root,\n        prefix=root / "usr",\n    )\n    assert "QPX_TERMUX_SESSION.sh" in block\n    assert "*/15 6-12 * * 1-5" in block\n    assert "15 16-23 * * 1-5" in block\n\nprint(\n    "QPX Bot Regular-Session Execution PASS"\n)\n',
    "qpx_bot/REGULAR_SESSION_EXECUTION_README.txt": 'QPX REGULAR-SESSION EXECUTION\n=============================\n\nThe workflow is now split into two independent phases.\n\n1. After-close analysis\n-----------------------\n\nQPX_TERMUX_DAILY.sh runs only after completed daily data is expected.\n\nIt may:\n- refresh completed daily bars;\n- rank the monthly swing universe;\n- reconcile the completed regular session;\n- update stops and targets from completed regular-session OHLC;\n- create a staged entry instruction for the next market session;\n- write health reports and verified backups.\n\nIt may not fill a staged entry.\n\n2. Regular-session execution\n----------------------------\n\nQPX_TERMUX_SESSION.sh checks every 15 minutes across a broad morning\nwindow. Python permits an entry only from 09:35 through 10:30\nAmerica/New_York on the next eligible market session.\n\nA paper entry uses the open of the first available one-minute\nregular-session bar. includePrePost=false is required.\n\nSafety rules:\n\n- extended-hours execution is hard-disabled;\n- the staged signal must be from the immediately preceding market\n  session;\n- stale instructions are cancelled;\n- instructions that miss the opening window are cancelled;\n- no after-close backfill is permitted;\n- duplicate order IDs cannot execute twice;\n- an opening gap above 1.5 signal ATR is rejected;\n- position sizing and portfolio-risk rules still apply;\n- the existing paper kill switch blocks session execution;\n- every result is appended to the hash-chained audit journal;\n- this remains simulated paper trading with no brokerage connection.\n\nFuture broker integration must use regular-hours orders and\nbroker-held protective OCO orders. Extended-hours trading remains\ndisabled unless a separate, explicit policy is designed and tested.\n\nCommands:\n\npython QPX_RUN_REGULAR_SESSION.py --check-only\npython QPX_RUN_REGULAR_SESSION.py\n\nReports:\n\nreports/qpx_session_execution/latest_session_execution.txt\nreports/qpx_session_execution/latest_session_execution.json\n',
}

SIMPLE_PATCHES = {
    "qpx_bot/market_calendar.py": [
        (
            '\ndef latest_completed_session(\n',
            '\n\ndef next_market_session(\n    day: date,\n    *,\n    include_day: bool = False,\n) -> date:\n    current = (\n        day\n        if include_day\n        else day + timedelta(days=1)\n    )\n\n    while not is_market_session(current):\n        current += timedelta(days=1)\n\n    return current\n\n\ndef latest_completed_session(\n',
        )
    ],
    "qpx_bot/paper_engine.py": [
        (
            "    Pending entries fill at the next bar's open. Stops and targets use\n    that bar's OHLC. New entry signals are created only after the close.\n",
            '    Pending entries are never filled by after-close analysis. The\n    regular-session runner consumes them during the next opening\n    window. Stops and targets use completed regular-session OHLC for\n    post-session reconciliation. New signals are created after close.\n',
        ),
        (
            '                            "execution": "NEXT_DAILY_OPEN",\n',
            '                            "execution": (\n                                "NEXT_REGULAR_SESSION_OPENING_WINDOW"\n                            ),\n                            "extended_hours": False,\n',
        ),
        (
            '                        "reason": (\n                            exit_evaluation.reason or "EXIT"\n                        ),\n',
            '                        "reason": (\n                            exit_evaluation.reason or "EXIT"\n                        ),\n                        "execution_session": (\n                            "REGULAR_SESSION_RECONCILIATION"\n                        ),\n                        "extended_hours": False,\n',
        ),
    ],
    "qpx_bot/backup.py": [
        (
            '    "qpx_bot/backup_config.json",\n',
            '    "qpx_bot/backup_config.json",\n    "qpx_bot/session_execution_config.json",\n',
        ),
        (
            '    "reports/qpx_operations/latest_health.json",\n',
            '    "reports/qpx_operations/latest_health.json",\n    "reports/qpx_session_execution/latest_session_execution.txt",\n    "reports/qpx_session_execution/latest_session_execution.json",\n',
        ),
    ],
}

REGION_PATCHES = {
    "qpx_bot/paper_engine.py": [
        (
            '    if (\n        state.pending_entry is not None\n        and state.position is None\n        and state.pending_entry.signal_date < current_date\n    ):\n',
            '    if state.position is not None and current_atr is not None:\n',
            '    # Staged entries are consumed only by qpx_bot.session_execution\n    # during the next regular-session opening window. After-close\n    # processing must never fill or clear a pending entry.\n\n',
        )
    ],
}

GITIGNORE_APPEND = '# QPX regular-session execution reports\nreports/qpx_session_execution/\n'
TARGETS = [
    *FILES,
    *SIMPLE_PATCHES,
    *REGION_PATCHES,
    ".gitignore",
]
originals: dict[str, bytes | None] = {}


def run(command: list[str]) -> None:
    print("$ " + " ".join(command))
    subprocess.run(
        command,
        cwd=ROOT,
        check=True,
    )


def is_tracked(relative: str) -> bool:
    return subprocess.run(
        [
            "git",
            "ls-files",
            "--error-unmatch",
            relative,
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0


def ensure_targets_are_safe() -> None:
    changed: list[str] = []

    for relative in TARGETS:
        path = ROOT / relative
        worktree = subprocess.run(
            [
                "git",
                "diff",
                "--quiet",
                "--",
                relative,
            ],
            cwd=ROOT,
        )
        staged = subprocess.run(
            [
                "git",
                "diff",
                "--cached",
                "--quiet",
                "--",
                relative,
            ],
            cwd=ROOT,
        )

        if (
            worktree.returncode != 0
            or staged.returncode != 0
        ):
            changed.append(relative)
            continue

        if (
            relative in FILES
            and path.exists()
            and not is_tracked(relative)
        ):
            changed.append(relative)

    if changed:
        raise RuntimeError(
            "These target files contain local changes and "
            "were not overwritten:\n"
            + "\n".join(changed)
        )


def apply_transformations(
    relative: str,
    content: str,
) -> str:
    for old, new in SIMPLE_PATCHES.get(
        relative,
        [],
    ):
        if old in content:
            content = content.replace(
                old,
                new,
                1,
            )
        elif new in content:
            continue
        else:
            raise RuntimeError(
                f"Expected marker not found in "
                f"{relative}:\n{old}"
            )

    for (
        start_marker,
        end_marker,
        replacement,
    ) in REGION_PATCHES.get(
        relative,
        [],
    ):
        if replacement in content:
            continue

        start = content.find(
            start_marker
        )

        if start < 0:
            raise RuntimeError(
                f"Region start marker not found in "
                f"{relative}:\n{start_marker}"
            )

        end = content.find(
            end_marker,
            start + len(start_marker),
        )

        if end < 0:
            raise RuntimeError(
                f"Region end marker not found in "
                f"{relative}:\n{end_marker}"
            )

        content = (
            content[:start]
            + replacement
            + content[end:]
        )

    return content


def validate_patch_markers() -> None:
    failures: list[str] = []

    for relative in {
        *SIMPLE_PATCHES,
        *REGION_PATCHES,
    }:
        path = ROOT / relative

        if not path.exists():
            failures.append(
                f"{relative}: file not found"
            )
            continue

        try:
            apply_transformations(
                relative,
                path.read_text(
                    encoding="utf-8"
                ),
            )
        except RuntimeError as exc:
            failures.append(str(exc))

    if failures:
        raise RuntimeError(
            "Patch preflight failed before any file "
            "changed:\n\n"
            + "\n\n".join(failures)
        )


def preserve(relative: str) -> None:
    if relative in originals:
        return

    path = ROOT / relative
    originals[relative] = (
        path.read_bytes()
        if path.exists()
        else None
    )

    if path.exists():
        backup_path = (
            BACKUP / relative
        )
        backup_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        shutil.copy2(
            path,
            backup_path,
        )


def install_files() -> None:
    for relative, content in FILES.items():
        preserve(relative)
        path = ROOT / relative
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        path.write_text(
            textwrap.dedent(
                content
            ).strip()
            + "\n",
            encoding="utf-8",
        )

        if path.suffix == ".sh":
            path.chmod(0o700)

        print(f"Installed: {relative}")


def patch_files() -> None:
    for relative in {
        *SIMPLE_PATCHES,
        *REGION_PATCHES,
    }:
        preserve(relative)
        path = ROOT / relative
        content = path.read_text(
            encoding="utf-8"
        )
        content = apply_transformations(
            relative,
            content,
        )
        path.write_text(
            content,
            encoding="utf-8",
        )
        print(f"Updated: {relative}")


def patch_gitignore() -> None:
    relative = ".gitignore"
    preserve(relative)
    path = ROOT / relative
    content = path.read_text(
        encoding="utf-8"
    )
    addition = textwrap.dedent(
        GITIGNORE_APPEND
    ).strip()

    if addition not in content:
        path.write_text(
            content.rstrip()
            + "\n\n"
            + addition
            + "\n",
            encoding="utf-8",
        )
        print("Updated: .gitignore")


def restore() -> None:
    print(
        "Restoring previous target files..."
    )

    for relative, original in originals.items():
        path = ROOT / relative

        if original is None:
            if path.exists():
                path.unlink()
        else:
            path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            path.write_bytes(original)


def commit_and_push() -> None:
    paths = list(TARGETS)

    try:
        paths.append(
            str(
                Path(__file__)
                .resolve()
                .relative_to(ROOT)
            )
        )
    except ValueError:
        pass

    run([
        "git",
        "add",
        "--",
        *paths,
    ])

    staged = subprocess.run(
        [
            "git",
            "diff",
            "--cached",
            "--quiet",
        ],
        cwd=ROOT,
    )

    if staged.returncode == 0:
        print(
            "Regular-session execution is "
            "already committed."
        )
        return

    run([
        "git",
        "commit",
        "-m",
        (
            "Implement QPX Bot "
            "regular-session execution"
        ),
    ])

    branch = subprocess.check_output(
        [
            "git",
            "branch",
            "--show-current",
        ],
        cwd=ROOT,
        text=True,
    ).strip()

    if not branch:
        raise RuntimeError(
            "Cannot push from detached Git state."
        )

    run([
        "git",
        "push",
        "origin",
        branch,
    ])


def main() -> int:
    print("=" * 78)
    print(
        "QPX BOT — REGULAR-SESSION "
        "EXECUTION INSTALLER"
    )
    print("=" * 78)
    print(f"Project: {ROOT}")

    ensure_targets_are_safe()
    validate_patch_markers()
    install_files()
    patch_files()
    patch_gitignore()

    try:
        run([
            sys.executable,
            "-m",
            (
                "tests."
                "test_qpx_bot_regular_session_execution"
            ),
        ])
        run([
            sys.executable,
            "tests/run_all_tests.py",
        ])
    except Exception:
        restore()
        raise

    commit_and_push()

    print()
    print(
        "Updating the Termux schedules..."
    )
    print()

    try:
        run([
            sys.executable,
            "QPX_SETUP_DAILY_SCHEDULE.py",
            "--install",
        ])
    except Exception:
        print()
        print("=" * 78)
        print(
            "QPX REGULAR-SESSION CODE: "
            "INSTALLED AND PUSHED"
        )
        print(
            "TERMUX SCHEDULE UPDATE: NEEDS RETRY"
        )
        print("=" * 78)
        print(
            "Re-run:\n"
            "python QPX_SETUP_DAILY_SCHEDULE.py "
            "--install"
        )
        return 2

    print()
    print(
        "Writing a non-mutating session snapshot..."
    )
    print()

    try:
        run([
            sys.executable,
            "QPX_RUN_REGULAR_SESSION.py",
            "--check-only",
        ])
    except Exception:
        print()
        print("=" * 78)
        print(
            "QPX REGULAR-SESSION CODE + "
            "SCHEDULE: INSTALLED"
        )
        print(
            "INITIAL SESSION SNAPSHOT: "
            "NEEDS RETRY"
        )
        print("=" * 78)
        print(
            "Re-run:\n"
            "python QPX_RUN_REGULAR_SESSION.py "
            "--check-only"
        )
        return 3

    print()
    print("=" * 78)
    print(
        "QPX REGULAR-SESSION EXECUTION: COMPLETE"
    )
    print("=" * 78)
    print(
        "After-close analysis can stage entries but "
        "cannot fill them. Extended-hours execution "
        "is disabled."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
