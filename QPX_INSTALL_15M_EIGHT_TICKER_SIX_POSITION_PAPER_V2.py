#!/usr/bin/env python3
"""Install, test, schedule, push, and initialize QPX 15-minute paper."""

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
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP = (
    ROOT
    / "backups"
    / "qpx_15m_eight_ticker_six_position_v2"
    / STAMP
)

FILES = {
    "qpx_bot/__init__.py": '"""\nQPX Bot\n\nResearch and paper-trading bot for the Hybrid Dividend + Swing strategy.\n"""\n\n__version__ = "1.22.1"\n',
    "qpx_bot/intraday_six_policy.json": '{\n  "schema_version": 1,\n  "interval": "15m",\n  "history_range": "60d",\n  "market_timezone": "America/New_York",\n  "regular_session_open": "09:30",\n  "first_scan_time": "09:45",\n  "regular_session_close": "16:00",\n  "maximum_concurrent_positions": 6,\n  "maximum_gap_atr_multiple": 1.5,\n  "candidates": [\n    "DIA",\n    "IWM",\n    "QQQ",\n    "SPY",\n    "XLE",\n    "XLF",\n    "XLK",\n    "XLV"\n  ],\n  "rankings_enabled": false,\n  "signal_evaluation": "all_candidates_each_completed_15m_bar",\n  "signal_execution": "next_completed_15m_bar_open",\n  "simultaneous_signal_tiebreak": "sha256_of_signal_bar_and_symbol",\n  "extended_hours_enabled": false,\n  "live_broker_enabled": false\n}\n',
    "qpx_bot/intraday_six_paper.py": '"""Restart-safe 15-minute, eight-symbol, six-position paper engine."""\n\nfrom __future__ import annotations\n\nimport argparse\nimport hashlib\nimport json\nimport math\nimport os\nimport time\nimport urllib.error\nimport urllib.parse\nimport urllib.request\nfrom contextlib import contextmanager\nfrom dataclasses import asdict, dataclass\nfrom datetime import date, datetime, time as clock_time, timedelta, timezone\nfrom pathlib import Path\nfrom typing import Any, Iterator, Mapping, Sequence\n\nfrom qpx_bot.allocation import rebalance_income_allocation\nfrom qpx_bot.config import BotConfig\nfrom qpx_bot.data_loader import Candle\nfrom qpx_bot.indicators import calculate_indicators\nfrom qpx_bot.market_calendar import NEW_YORK, is_market_session\nfrom qpx_bot.paper_state import StateStore\nfrom qpx_bot.portfolio import ClosedTrade, Portfolio, Position, contribution_allocation\nfrom qpx_bot.risk import buy_fill, calculate_position_size\nfrom qpx_bot.strategy import evaluate_entry, evaluate_exit\nfrom qpx_bot.time_rules import elapsed_complete_years\nfrom qpx_bot.yahoo_data import YAHOO_HOSTS\n\n\nPACKAGE_DIR = Path(__file__).resolve().parent\nPROJECT_ROOT = PACKAGE_DIR.parent\nDEFAULT_POLICY = PACKAGE_DIR / "intraday_six_policy.json"\nDEFAULT_RUNTIME = PACKAGE_DIR / "intraday_six_runtime"\nDEFAULT_LEGACY_RUNTIME = PACKAGE_DIR / "paper_runtime"\nDEFAULT_REPORTS = PROJECT_ROOT / "reports" / "qpx_intraday_six"\nSTATE_SCHEMA_VERSION = 1\n\n\n@dataclass(frozen=True, slots=True)\nclass IntradayPolicy:\n    schema_version: int\n    interval: str\n    history_range: str\n    market_timezone: str\n    regular_session_open: str\n    first_scan_time: str\n    regular_session_close: str\n    maximum_concurrent_positions: int\n    maximum_gap_atr_multiple: float\n    candidates: tuple[str, ...]\n    rankings_enabled: bool\n    signal_evaluation: str\n    signal_execution: str\n    simultaneous_signal_tiebreak: str\n    extended_hours_enabled: bool\n    live_broker_enabled: bool\n\n    def validate(self) -> None:\n        if self.schema_version != 1:\n            raise ValueError("Unsupported intraday policy schema.")\n\n        if self.interval != "15m":\n            raise ValueError("The active paper interval must be 15m.")\n\n        if self.history_range != "60d":\n            raise ValueError("The 15-minute history range must be 60d.")\n\n        if self.market_timezone != "America/New_York":\n            raise ValueError("The market timezone must be America/New_York.")\n\n        if self.maximum_concurrent_positions != 6:\n            raise ValueError("Exactly six concurrent swing slots are required.")\n\n        if len(self.candidates) != 8 or len(set(self.candidates)) != 8:\n            raise ValueError("Exactly eight unique swing symbols are required.")\n\n        if self.rankings_enabled:\n            raise ValueError("Rankings must remain disabled.")\n\n        if self.signal_evaluation != "all_candidates_each_completed_15m_bar":\n            raise ValueError("All eight symbols must be evaluated each bar.")\n\n        if self.signal_execution != "next_completed_15m_bar_open":\n            raise ValueError("Signals must execute at the next 15-minute open.")\n\n        if (\n            self.simultaneous_signal_tiebreak\n            != "sha256_of_signal_bar_and_symbol"\n        ):\n            raise ValueError("Unexpected simultaneous-signal tie-break.")\n\n        if self.maximum_gap_atr_multiple <= 0:\n            raise ValueError("The opening-gap limit must be positive.")\n\n        if self.extended_hours_enabled:\n            raise ValueError("Extended-hours scanning is prohibited.")\n\n        if self.live_broker_enabled:\n            raise ValueError("Live brokerage must remain disabled.")\n\n\n@dataclass(frozen=True, slots=True)\nclass IntradayBar:\n    start: datetime\n    open: float\n    high: float\n    low: float\n    close: float\n    volume: int\n\n\n@dataclass(frozen=True, slots=True)\nclass PendingSignal:\n    symbol: str\n    signal_bar: str\n    signal_atr: float\n    prior_close: float\n    tie_key: str\n\n\n@dataclass(slots=True)\nclass PaperAccount:\n    account_id: str\n    start_date: date\n    starting_total_capital: float\n    swing_cash: float\n    tax_reserve_cash: float\n    total_contributions: float\n    realized_pnl: float\n    income_shares: float\n    income_cost: float\n    dividends_received: float\n    last_contribution_month: str | None\n    last_allocation_years: int\n    last_processed_bar: str | None\n    processed_dividend_keys: list[str]\n    positions: dict[str, Position]\n    pending: dict[str, PendingSignal]\n    closed_trades: list[ClosedTrade]\n    trade_results_r: list[float]\n    revision: int = 0\n    schema_version: int = STATE_SCHEMA_VERSION\n\n    def validate(\n        self,\n        policy: IntradayPolicy,\n    ) -> None:\n        if self.schema_version != STATE_SCHEMA_VERSION:\n            raise ValueError("Unsupported 15-minute state schema.")\n\n        if not self.account_id.strip():\n            raise ValueError("Account ID cannot be empty.")\n\n        if len(self.positions) > policy.maximum_concurrent_positions:\n            raise ValueError("Open-position count exceeds the six-slot limit.")\n\n        if (\n            len(self.positions)\n            + len(self.pending)\n            > policy.maximum_concurrent_positions\n        ):\n            raise ValueError("Positions plus pending entries exceed six slots.")\n\n        if set(self.positions).intersection(self.pending):\n            raise ValueError("A symbol cannot be both open and pending.")\n\n        if any(value < -1e-9 for value in (\n            self.starting_total_capital,\n            self.swing_cash,\n            self.tax_reserve_cash,\n            self.total_contributions,\n            self.income_shares,\n            self.income_cost,\n            self.dividends_received,\n        )):\n            raise ValueError("Paper-account balances cannot be negative.")\n\n        if self.last_allocation_years < 0 or self.revision < 0:\n            raise ValueError("Paper-account counters cannot be negative.")\n\n\ndef load_policy(\n    filename: str | Path = DEFAULT_POLICY,\n) -> IntradayPolicy:\n    payload = json.loads(\n        Path(filename).read_text(encoding="utf-8")\n    )\n    policy = IntradayPolicy(\n        schema_version=int(payload["schema_version"]),\n        interval=str(payload["interval"]),\n        history_range=str(payload["history_range"]),\n        market_timezone=str(payload["market_timezone"]),\n        regular_session_open=str(payload["regular_session_open"]),\n        first_scan_time=str(payload["first_scan_time"]),\n        regular_session_close=str(payload["regular_session_close"]),\n        maximum_concurrent_positions=int(\n            payload["maximum_concurrent_positions"]\n        ),\n        maximum_gap_atr_multiple=float(\n            payload["maximum_gap_atr_multiple"]\n        ),\n        candidates=tuple(\n            str(symbol).strip().upper()\n            for symbol in payload["candidates"]\n        ),\n        rankings_enabled=bool(payload["rankings_enabled"]),\n        signal_evaluation=str(payload["signal_evaluation"]),\n        signal_execution=str(payload["signal_execution"]),\n        simultaneous_signal_tiebreak=str(\n            payload["simultaneous_signal_tiebreak"]\n        ),\n        extended_hours_enabled=bool(\n            payload["extended_hours_enabled"]\n        ),\n        live_broker_enabled=bool(\n            payload["live_broker_enabled"]\n        ),\n    )\n    policy.validate()\n    return policy\n\n\ndef _parse_clock(value: str) -> clock_time:\n    hour, minute = value.split(":", 1)\n    return clock_time(int(hour), int(minute))\n\n\ndef scan_window_open(\n    now_market: datetime,\n    policy: IntradayPolicy,\n) -> bool:\n    local = now_market.astimezone(NEW_YORK)\n    wall = local.time().replace(tzinfo=None)\n\n    return (\n        is_market_session(local.date())\n        and _parse_clock(policy.first_scan_time)\n        <= wall\n        <= _parse_clock(policy.regular_session_close)\n    )\n\n\ndef _chart_url(\n    host: str,\n    symbol: str,\n    *,\n    interval: str,\n    range_name: str,\n) -> str:\n    encoded = urllib.parse.quote(symbol, safe="")\n    query = urllib.parse.urlencode(\n        {\n            "range": range_name,\n            "interval": interval,\n            "events": "div,splits",\n            "includePrePost": "false",\n            "includeAdjustedClose": "true",\n        }\n    )\n    return (\n        f"https://{host}/v8/finance/chart/"\n        f"{encoded}?{query}"\n    )\n\n\ndef _open_json(\n    url: str,\n    *,\n    timeout_seconds: float = 20.0,\n) -> Mapping[str, Any]:\n    request = urllib.request.Request(\n        url,\n        headers={\n            "User-Agent": (\n                "Mozilla/5.0 (Linux; Android 14) "\n                "AppleWebKit/537.36 QPXBot/1.22"\n            ),\n            "Accept": "application/json,text/plain,*/*",\n            "Accept-Encoding": "identity",\n            "Connection": "close",\n        },\n    )\n\n    with urllib.request.urlopen(\n        request,\n        timeout=timeout_seconds,\n    ) as response:\n        payload = json.loads(\n            response.read().decode("utf-8")\n        )\n\n    chart = payload.get("chart")\n\n    if not isinstance(chart, Mapping) or chart.get("error"):\n        raise RuntimeError("Yahoo chart response is invalid.")\n\n    results = chart.get("result")\n\n    if not isinstance(results, list) or not results:\n        raise RuntimeError("Yahoo chart result is empty.")\n\n    result = results[0]\n\n    if not isinstance(result, Mapping):\n        raise RuntimeError("Yahoo chart result is malformed.")\n\n    return result\n\n\ndef fetch_intraday(\n    symbol: str,\n    policy: IntradayPolicy,\n    *,\n    now_market: datetime,\n) -> list[IntradayBar]:\n    last_error: Exception | None = None\n\n    for host in YAHOO_HOSTS:\n        try:\n            result = _open_json(\n                _chart_url(\n                    host,\n                    symbol,\n                    interval=policy.interval,\n                    range_name=policy.history_range,\n                )\n            )\n            timestamps = result.get("timestamp")\n            indicators = result.get("indicators")\n            quotes = (\n                indicators.get("quote")\n                if isinstance(indicators, Mapping)\n                else None\n            )\n\n            if (\n                not isinstance(timestamps, list)\n                or not isinstance(quotes, list)\n                or not quotes\n                or not isinstance(quotes[0], Mapping)\n            ):\n                raise RuntimeError(\n                    f"Intraday arrays are missing for {symbol}."\n                )\n\n            quote = quotes[0]\n            opens = quote.get("open")\n            highs = quote.get("high")\n            lows = quote.get("low")\n            closes = quote.get("close")\n            volumes = quote.get("volume")\n\n            arrays = (\n                timestamps,\n                opens,\n                highs,\n                lows,\n                closes,\n                volumes,\n            )\n\n            if not all(isinstance(value, list) for value in arrays):\n                raise RuntimeError(\n                    f"Intraday arrays are incomplete for {symbol}."\n                )\n\n            bars: list[IntradayBar] = []\n            session_open = _parse_clock(policy.regular_session_open)\n            session_close = _parse_clock(policy.regular_session_close)\n            now_local = now_market.astimezone(NEW_YORK)\n\n            for index, raw_timestamp in enumerate(timestamps):\n                try:\n                    start = datetime.fromtimestamp(\n                        int(raw_timestamp),\n                        tz=timezone.utc,\n                    ).astimezone(NEW_YORK)\n                    values = (\n                        float(opens[index]),\n                        float(highs[index]),\n                        float(lows[index]),\n                        float(closes[index]),\n                    )\n                    volume = int(volumes[index] or 0)\n                except (TypeError, ValueError, IndexError):\n                    continue\n\n                if not all(\n                    math.isfinite(value) and value > 0\n                    for value in values\n                ):\n                    continue\n\n                wall = start.time().replace(tzinfo=None)\n\n                if not (\n                    session_open <= wall < session_close\n                    and is_market_session(start.date())\n                ):\n                    continue\n\n                if (\n                    start + timedelta(minutes=15)\n                    > now_local\n                ):\n                    continue\n\n                bars.append(\n                    IntradayBar(\n                        start=start,\n                        open=values[0],\n                        high=values[1],\n                        low=values[2],\n                        close=values[3],\n                        volume=max(0, volume),\n                    )\n                )\n\n            deduplicated = {\n                bar.start.isoformat(): bar\n                for bar in bars\n            }\n            result_bars = sorted(\n                deduplicated.values(),\n                key=lambda bar: bar.start,\n            )\n\n            if len(result_bars) < 220:\n                raise RuntimeError(\n                    f"Only {len(result_bars)} completed "\n                    f"15-minute bars were returned for {symbol}."\n                )\n\n            return result_bars\n        except (\n            OSError,\n            RuntimeError,\n            urllib.error.URLError,\n            json.JSONDecodeError,\n        ) as exc:\n            last_error = exc\n\n    raise RuntimeError(\n        f"Unable to download valid 15-minute data for {symbol}: "\n        f"{last_error}"\n    )\n\n\ndef fetch_qdte_dividends() -> list[tuple[str, date, float]]:\n    last_error: Exception | None = None\n\n    for host in YAHOO_HOSTS:\n        try:\n            result = _open_json(\n                _chart_url(\n                    host,\n                    "QDTE",\n                    interval="1d",\n                    range_name="1y",\n                )\n            )\n            events = result.get("events")\n            dividends = (\n                events.get("dividends")\n                if isinstance(events, Mapping)\n                else None\n            )\n\n            if not isinstance(dividends, Mapping):\n                return []\n\n            rows: list[tuple[str, date, float]] = []\n\n            for key, raw in dividends.items():\n                if not isinstance(raw, Mapping):\n                    continue\n\n                amount = float(raw.get("amount", 0.0))\n                raw_date = raw.get("date")\n\n                if amount <= 0 or raw_date is None:\n                    continue\n\n                event_date = datetime.fromtimestamp(\n                    int(raw_date),\n                    tz=timezone.utc,\n                ).date()\n                rows.append(\n                    (\n                        str(key),\n                        event_date,\n                        amount,\n                    )\n                )\n\n            return sorted(rows, key=lambda item: item[1])\n        except (\n            OSError,\n            RuntimeError,\n            urllib.error.URLError,\n            json.JSONDecodeError,\n            TypeError,\n            ValueError,\n        ) as exc:\n            last_error = exc\n\n    raise RuntimeError(\n        f"Unable to download QDTE dividends: {last_error}"\n    )\n\n\ndef common_completed_times(\n    histories: Mapping[str, Sequence[IntradayBar]],\n) -> list[datetime]:\n    common: set[datetime] | None = None\n\n    for bars in histories.values():\n        times = {bar.start for bar in bars}\n        common = times if common is None else common.intersection(times)\n\n    return sorted(common or set())\n\n\ndef choose_without_ranking(\n    *,\n    signal_bar: datetime,\n    qualifying: Sequence[str],\n    available_slots: int,\n) -> tuple[tuple[str, ...], tuple[str, ...]]:\n    if available_slots < 0:\n        raise ValueError("Available slots cannot be negative.")\n\n    ordered = sorted(\n        {\n            symbol.strip().upper()\n            for symbol in qualifying\n            if symbol.strip()\n        },\n        key=lambda symbol: (\n            hashlib.sha256(\n                (\n                    signal_bar.isoformat()\n                    + "|"\n                    + symbol\n                ).encode("utf-8")\n            ).hexdigest(),\n            symbol,\n        ),\n    )\n    return (\n        tuple(ordered[:available_slots]),\n        tuple(ordered[available_slots:]),\n    )\n\n\ndef _position_to_dict(position: Position) -> dict[str, Any]:\n    payload = asdict(position)\n    payload["entry_date"] = position.entry_date.isoformat()\n    return payload\n\n\ndef _position_from_dict(payload: Mapping[str, Any]) -> Position:\n    return Position(\n        symbol=str(payload["symbol"]),\n        shares=int(payload["shares"]),\n        entry_date=date.fromisoformat(str(payload["entry_date"])),\n        entry_price=float(payload["entry_price"]),\n        entry_atr=float(payload["entry_atr"]),\n        stop_price=float(payload["stop_price"]),\n        target_price=float(payload["target_price"]),\n        highest_price=float(payload["highest_price"]),\n    )\n\n\ndef _trade_to_dict(trade: ClosedTrade) -> dict[str, Any]:\n    payload = asdict(trade)\n    payload["entry_date"] = trade.entry_date.isoformat()\n    payload["exit_date"] = trade.exit_date.isoformat()\n    return payload\n\n\ndef _trade_from_dict(payload: Mapping[str, Any]) -> ClosedTrade:\n    return ClosedTrade(\n        symbol=str(payload["symbol"]),\n        entry_date=date.fromisoformat(str(payload["entry_date"])),\n        exit_date=date.fromisoformat(str(payload["exit_date"])),\n        shares=int(payload["shares"]),\n        entry_price=float(payload["entry_price"]),\n        exit_price=float(payload["exit_price"]),\n        pnl=float(payload["pnl"]),\n        tax_reserved=float(payload["tax_reserved"]),\n        reason=str(payload["reason"]),\n        result_r=float(payload["result_r"]),\n    )\n\n\ndef account_to_dict(account: PaperAccount) -> dict[str, Any]:\n    return {\n        "schema_version": account.schema_version,\n        "account_id": account.account_id,\n        "start_date": account.start_date.isoformat(),\n        "starting_total_capital": account.starting_total_capital,\n        "swing_cash": account.swing_cash,\n        "tax_reserve_cash": account.tax_reserve_cash,\n        "total_contributions": account.total_contributions,\n        "realized_pnl": account.realized_pnl,\n        "income_shares": account.income_shares,\n        "income_cost": account.income_cost,\n        "dividends_received": account.dividends_received,\n        "last_contribution_month": account.last_contribution_month,\n        "last_allocation_years": account.last_allocation_years,\n        "last_processed_bar": account.last_processed_bar,\n        "processed_dividend_keys": list(\n            account.processed_dividend_keys\n        ),\n        "positions": {\n            symbol: _position_to_dict(position)\n            for symbol, position in account.positions.items()\n        },\n        "pending": {\n            symbol: asdict(signal)\n            for symbol, signal in account.pending.items()\n        },\n        "closed_trades": [\n            _trade_to_dict(trade)\n            for trade in account.closed_trades[-500:]\n        ],\n        "trade_results_r": list(account.trade_results_r[-500:]),\n        "revision": account.revision,\n    }\n\n\ndef account_from_dict(payload: Mapping[str, Any]) -> PaperAccount:\n    return PaperAccount(\n        schema_version=int(\n            payload.get(\n                "schema_version",\n                STATE_SCHEMA_VERSION,\n            )\n        ),\n        account_id=str(payload["account_id"]),\n        start_date=date.fromisoformat(str(payload["start_date"])),\n        starting_total_capital=float(\n            payload["starting_total_capital"]\n        ),\n        swing_cash=float(payload["swing_cash"]),\n        tax_reserve_cash=float(payload["tax_reserve_cash"]),\n        total_contributions=float(payload["total_contributions"]),\n        realized_pnl=float(payload["realized_pnl"]),\n        income_shares=float(payload["income_shares"]),\n        income_cost=float(payload["income_cost"]),\n        dividends_received=float(payload["dividends_received"]),\n        last_contribution_month=(\n            str(payload["last_contribution_month"])\n            if payload.get("last_contribution_month")\n            else None\n        ),\n        last_allocation_years=int(\n            payload.get("last_allocation_years", 0)\n        ),\n        last_processed_bar=(\n            str(payload["last_processed_bar"])\n            if payload.get("last_processed_bar")\n            else None\n        ),\n        processed_dividend_keys=[\n            str(value)\n            for value in payload.get(\n                "processed_dividend_keys",\n                [],\n            )\n        ],\n        positions={\n            str(symbol): _position_from_dict(raw)\n            for symbol, raw in dict(\n                payload.get("positions", {})\n            ).items()\n        },\n        pending={\n            str(symbol): PendingSignal(\n                symbol=str(raw["symbol"]),\n                signal_bar=str(raw["signal_bar"]),\n                signal_atr=float(raw["signal_atr"]),\n                prior_close=float(raw["prior_close"]),\n                tie_key=str(raw["tie_key"]),\n            )\n            for symbol, raw in dict(\n                payload.get("pending", {})\n            ).items()\n        },\n        closed_trades=[\n            _trade_from_dict(raw)\n            for raw in payload.get("closed_trades", [])\n        ],\n        trade_results_r=[\n            float(value)\n            for value in payload.get("trade_results_r", [])\n        ],\n        revision=int(payload.get("revision", 0)),\n    )\n\n\nclass AccountStore:\n    def __init__(self, directory: str | Path) -> None:\n        self.directory = Path(directory).expanduser().resolve()\n        self.state_path = self.directory / "paper_state.json"\n        self.checksum_path = self.directory / "paper_state.sha256"\n        self.audit_path = self.directory / "paper_audit.jsonl"\n        self.lock_path = self.directory / "paper.lock"\n\n    def exists(self) -> bool:\n        return self.state_path.exists()\n\n    @contextmanager\n    def locked(self) -> Iterator[None]:\n        self.directory.mkdir(parents=True, exist_ok=True)\n        descriptor: int | None = None\n\n        for _ in range(120):\n            try:\n                descriptor = os.open(\n                    self.lock_path,\n                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,\n                )\n                os.write(\n                    descriptor,\n                    (\n                        f"{os.getpid()}|"\n                        f"{datetime.now(timezone.utc).isoformat()}"\n                    ).encode("utf-8"),\n                )\n                break\n            except FileExistsError:\n                time.sleep(0.25)\n\n        if descriptor is None:\n            raise RuntimeError(\n                "The 15-minute paper runtime is already locked."\n            )\n\n        try:\n            yield\n        finally:\n            os.close(descriptor)\n            try:\n                self.lock_path.unlink()\n            except FileNotFoundError:\n                pass\n\n    def save(\n        self,\n        account: PaperAccount,\n        policy: IntradayPolicy,\n    ) -> None:\n        account.validate(policy)\n        encoded = (\n            json.dumps(\n                account_to_dict(account),\n                indent=2,\n                sort_keys=True,\n            )\n            + "\\n"\n        ).encode("utf-8")\n        checksum = hashlib.sha256(encoded).hexdigest()\n        state_temp = self.state_path.with_suffix(".json.tmp")\n        checksum_temp = self.checksum_path.with_suffix(".sha256.tmp")\n        state_temp.write_bytes(encoded)\n        checksum_temp.write_text(\n            checksum + "\\n",\n            encoding="utf-8",\n        )\n        state_temp.replace(self.state_path)\n        checksum_temp.replace(self.checksum_path)\n\n    def load(\n        self,\n        policy: IntradayPolicy,\n    ) -> PaperAccount:\n        encoded = self.state_path.read_bytes()\n        expected = self.checksum_path.read_text(\n            encoding="utf-8"\n        ).strip()\n        actual = hashlib.sha256(encoded).hexdigest()\n\n        if actual != expected:\n            raise RuntimeError(\n                "The 15-minute paper-state checksum is invalid."\n            )\n\n        account = account_from_dict(\n            json.loads(encoded.decode("utf-8"))\n        )\n        account.validate(policy)\n        return account\n\n    def event(\n        self,\n        event_type: str,\n        bar_time: datetime,\n        details: Mapping[str, Any],\n    ) -> None:\n        record = {\n            "timestamp_utc": datetime.now(\n                timezone.utc\n            ).isoformat(),\n            "event_type": event_type,\n            "bar_time_market": bar_time.isoformat(),\n            "details": dict(details),\n        }\n\n        with self.audit_path.open(\n            "a",\n            encoding="utf-8",\n        ) as file:\n            file.write(\n                json.dumps(\n                    record,\n                    sort_keys=True,\n                )\n                + "\\n"\n            )\n\n\ndef _portfolio(account: PaperAccount) -> Portfolio:\n    portfolio = Portfolio(0.0)\n    portfolio.cash = account.swing_cash\n    portfolio.tax_reserve_cash = account.tax_reserve_cash\n    portfolio.total_contributions = account.total_contributions\n    portfolio.realized_pnl = account.realized_pnl\n    portfolio.positions = {\n        symbol: position\n        for symbol, position in account.positions.items()\n    }\n    portfolio.closed_trades = list(account.closed_trades)\n    return portfolio\n\n\ndef _sync(\n    account: PaperAccount,\n    portfolio: Portfolio,\n) -> None:\n    account.swing_cash = portfolio.cash\n    account.tax_reserve_cash = portfolio.tax_reserve_cash\n    account.realized_pnl = portfolio.realized_pnl\n    account.positions = {\n        symbol: position\n        for symbol, position in portfolio.positions.items()\n    }\n    account.closed_trades = list(portfolio.closed_trades[-500:])\n    account.trade_results_r = [\n        trade.result_r\n        for trade in account.closed_trades[-500:]\n    ]\n\n\ndef _fresh_account(\n    *,\n    qdte_price: float,\n    first_bar: datetime,\n    config: BotConfig,\n) -> PaperAccount:\n    fill = buy_fill(\n        qdte_price,\n        config.slippage_rate,\n    )\n    income_shares = config.starting_cash / fill\n    account_id = (\n        "qpx-15m-"\n        + hashlib.sha256(\n            first_bar.isoformat().encode("utf-8")\n        ).hexdigest()[:20]\n    )\n    account = PaperAccount(\n        account_id=account_id,\n        start_date=first_bar.date(),\n        starting_total_capital=config.total_starting_capital,\n        swing_cash=config.starting_swing_cash,\n        tax_reserve_cash=0.0,\n        total_contributions=config.total_starting_capital,\n        realized_pnl=0.0,\n        income_shares=income_shares,\n        income_cost=config.starting_cash,\n        dividends_received=0.0,\n        last_contribution_month=(\n            f"{first_bar.year:04d}-{first_bar.month:02d}"\n        ),\n        last_allocation_years=0,\n        last_processed_bar=None,\n        processed_dividend_keys=[],\n        positions={},\n        pending={},\n        closed_trades=[],\n        trade_results_r=[],\n    )\n    _rebalance(\n        account=account,\n        portfolio=_portfolio(account),\n        qdte_price=qdte_price,\n        position_prices={},\n        target_income_weight=(\n            config.dividend_allocation_years_1_2\n        ),\n        config=config,\n    )\n    return account\n\n\ndef _migrate_legacy(\n    *,\n    legacy_directory: Path,\n    latest_bar: datetime,\n    policy: IntradayPolicy,\n) -> PaperAccount | None:\n    legacy = StateStore(legacy_directory)\n\n    if not legacy.exists():\n        return None\n\n    with legacy.locked():\n        state = legacy.load()\n\n    positions: dict[str, Position] = {}\n\n    if state.position is not None:\n        position = state.position\n        positions[position.symbol] = Position(\n            symbol=position.symbol,\n            shares=position.shares,\n            entry_date=position.entry_date,\n            entry_price=position.entry_price,\n            entry_atr=position.entry_atr,\n            stop_price=position.stop_price,\n            target_price=position.target_price,\n            highest_price=position.highest_price,\n        )\n\n    account = PaperAccount(\n        account_id=(\n            state.state_id\n            + "-15m6"\n        ),\n        start_date=state.start_date,\n        starting_total_capital=state.starting_cash,\n        swing_cash=state.swing_cash,\n        tax_reserve_cash=state.tax_reserve_cash,\n        total_contributions=state.total_contributions,\n        realized_pnl=state.realized_pnl,\n        income_shares=state.income_shares,\n        income_cost=state.income_cost,\n        dividends_received=state.dividends_received,\n        last_contribution_month=state.last_contribution_month,\n        last_allocation_years=elapsed_complete_years(\n            state.start_date,\n            latest_bar.date(),\n        ),\n        last_processed_bar=None,\n        processed_dividend_keys=list(\n            state.processed_dividend_keys\n        ),\n        positions=positions,\n        pending={},\n        closed_trades=[],\n        trade_results_r=list(state.trade_results_r),\n        revision=state.revision,\n    )\n    account.validate(policy)\n    return account\n\n\ndef _rebalance(\n    *,\n    account: PaperAccount,\n    portfolio: Portfolio,\n    qdte_price: float,\n    position_prices: Mapping[str, float],\n    target_income_weight: float,\n    config: BotConfig,\n) -> None:\n    swing_market_value = portfolio.market_value(\n        position_prices\n    )\n    result = rebalance_income_allocation(\n        income_shares=account.income_shares,\n        income_cost=account.income_cost,\n        swing_cash=portfolio.cash,\n        swing_market_value=swing_market_value,\n        income_price=qdte_price,\n        target_income_weight=target_income_weight,\n        slippage_rate=config.slippage_rate,\n        tax_reserve_rate=config.annual_tax_reserve_rate,\n        tolerance=config.allocation_rebalance_tolerance,\n        minimum_trade=config.minimum_rebalance_trade,\n    )\n    account.income_shares = result.shares_after\n    account.income_cost = result.income_cost_after\n    portfolio.cash = result.swing_cash_after\n    portfolio.tax_reserve_cash += result.tax_reserved\n    portfolio.realized_pnl += result.realized_pnl\n    _sync(account, portfolio)\n\n\ndef _bar_maps(\n    histories: Mapping[str, Sequence[IntradayBar]],\n) -> dict[str, dict[datetime, IntradayBar]]:\n    return {\n        symbol: {\n            bar.start: bar\n            for bar in bars\n        }\n        for symbol, bars in histories.items()\n    }\n\n\ndef _candles(\n    histories: Mapping[str, Sequence[IntradayBar]],\n) -> dict[str, list[Candle]]:\n    return {\n        symbol: [\n            Candle(\n                date=bar.start.date(),\n                open=bar.open,\n                high=bar.high,\n                low=bar.low,\n                close=bar.close,\n                volume=bar.volume,\n            )\n            for bar in bars\n        ]\n        for symbol, bars in histories.items()\n    }\n\n\ndef run_cycle(\n    *,\n    now_market: datetime | None = None,\n    policy_path: str | Path = DEFAULT_POLICY,\n    runtime_directory: str | Path = DEFAULT_RUNTIME,\n    legacy_runtime_directory: str | Path = DEFAULT_LEGACY_RUNTIME,\n    report_directory: str | Path = DEFAULT_REPORTS,\n) -> dict[str, Any]:\n    policy = load_policy(policy_path)\n    config = BotConfig()\n    config.validate()\n\n    if config.maximum_swing_positions != 6:\n        raise RuntimeError(\n            "BotConfig maximum_swing_positions must be six."\n        )\n\n    now_market = (\n        now_market.astimezone(NEW_YORK)\n        if now_market is not None\n        else datetime.now(tz=NEW_YORK)\n    )\n\n    if not scan_window_open(now_market, policy):\n        return {\n            "status": "OUTSIDE_REGULAR_SCAN_WINDOW",\n            "market_time": now_market.isoformat(),\n            "rankings_enabled": False,\n            "maximum_positions": 6,\n            "live_broker_enabled": False,\n        }\n\n    symbols = (\n        *policy.candidates,\n        "QDTE",\n        "^VIX",\n    )\n    histories = {\n        symbol: fetch_intraday(\n            symbol,\n            policy,\n            now_market=now_market,\n        )\n        for symbol in symbols\n    }\n    common_times = common_completed_times(histories)\n\n    if not common_times:\n        raise RuntimeError(\n            "The ten actual intraday histories have no common bar."\n        )\n\n    maps = _bar_maps(histories)\n    latest = common_times[-1]\n    store = AccountStore(runtime_directory)\n    report_dir = Path(report_directory).expanduser().resolve()\n    report_dir.mkdir(parents=True, exist_ok=True)\n\n    with store.locked():\n        if store.exists():\n            account = store.load(policy)\n            initialized = False\n            migration = "EXISTING_15M_STATE"\n        else:\n            account = _migrate_legacy(\n                legacy_directory=Path(\n                    legacy_runtime_directory\n                ).expanduser().resolve(),\n                latest_bar=latest,\n                policy=policy,\n            )\n            migration = "LEGACY_STATE_SNAPSHOT"\n\n            if account is None:\n                account = _fresh_account(\n                    qdte_price=maps["QDTE"][latest].close,\n                    first_bar=latest,\n                    config=config,\n                )\n                migration = "FRESH_15M_ACCOUNT"\n\n            initialized = True\n            account.last_processed_bar = (\n                common_times[-2].isoformat()\n                if len(common_times) >= 2\n                else latest.isoformat()\n            )\n            store.event(\n                "ACCOUNT_INITIALIZED",\n                latest,\n                {\n                    "source": migration,\n                    "legacy_state_unchanged": True,\n                    "maximum_positions": 6,\n                    "rankings_enabled": False,\n                },\n            )\n\n        last_processed = (\n            datetime.fromisoformat(account.last_processed_bar)\n            if account.last_processed_bar\n            else common_times[-2]\n        )\n        new_times = [\n            value\n            for value in common_times\n            if value > last_processed\n        ]\n\n        if not new_times:\n            return {\n                "status": "NO_NEW_COMPLETED_15M_BAR",\n                "market_time": now_market.isoformat(),\n                "latest_completed_bar": latest.isoformat(),\n                "open_positions": len(account.positions),\n                "pending_entries": len(account.pending),\n                "maximum_positions": 6,\n                "rankings_enabled": False,\n                "live_broker_enabled": False,\n            }\n\n        candle_sets = _candles(histories)\n        indicators = {\n            symbol: calculate_indicators(\n                candle_sets[symbol],\n                config,\n            )\n            for symbol in policy.candidates\n        }\n        index_maps = {\n            symbol: {\n                bar.start: index\n                for index, bar in enumerate(histories[symbol])\n            }\n            for symbol in policy.candidates\n        }\n        dividends = fetch_qdte_dividends()\n        processed_dividends = set(\n            account.processed_dividend_keys\n        )\n\n        if initialized:\n            processed_dividends.update(\n                key\n                for key, event_date, _ in dividends\n                if event_date <= latest.date()\n            )\n            account.processed_dividend_keys = sorted(\n                processed_dividends\n            )\n\n        events: list[dict[str, Any]] = []\n        evaluations = 0\n        qualifying_count = 0\n        filled = 0\n        closed = 0\n        rejected_gap = 0\n        rejected_risk = 0\n        deferred_capacity = 0\n\n        for bar_time in new_times:\n            qdte_bar = maps["QDTE"][bar_time]\n            portfolio = _portfolio(account)\n\n            for key, event_date, amount in dividends:\n                if (\n                    key not in processed_dividends\n                    and event_date <= bar_time.date()\n                ):\n                    cash = account.income_shares * amount\n                    portfolio.cash += cash\n                    account.dividends_received += cash\n                    processed_dividends.add(key)\n                    store.event(\n                        "QDTE_DISTRIBUTION",\n                        bar_time,\n                        {\n                            "event_key": key,\n                            "event_date": event_date.isoformat(),\n                            "amount_per_share": amount,\n                            "cash": cash,\n                        },\n                    )\n\n            account.processed_dividend_keys = sorted(\n                processed_dividends\n            )\n            month_key = (\n                f"{bar_time.year:04d}-{bar_time.month:02d}"\n            )\n            allocation_years = elapsed_complete_years(\n                account.start_date,\n                bar_time.date(),\n            )\n            month_changed = (\n                account.last_contribution_month != month_key\n            )\n            phase_changed = (\n                allocation_years != account.last_allocation_years\n            )\n\n            position_open_prices = {\n                symbol: maps[symbol][bar_time].open\n                for symbol in portfolio.positions\n            }\n\n            if month_changed:\n                portfolio.deposit(\n                    config.monthly_contribution\n                )\n                account.total_contributions += (\n                    config.monthly_contribution\n                )\n                account.last_contribution_month = month_key\n                store.event(\n                    "MONTHLY_CONTRIBUTION",\n                    bar_time,\n                    {\n                        "amount": config.monthly_contribution,\n                        "month": month_key,\n                    },\n                )\n\n            if month_changed or phase_changed:\n                target, _ = contribution_allocation(\n                    allocation_years,\n                    config,\n                )\n                _rebalance(\n                    account=account,\n                    portfolio=portfolio,\n                    qdte_price=qdte_bar.open,\n                    position_prices=position_open_prices,\n                    target_income_weight=target,\n                    config=config,\n                )\n                store.event(\n                    (\n                        "MONTHLY_ALLOCATION_REBALANCE"\n                        if month_changed\n                        else "ALLOCATION_PHASE_REBALANCE"\n                    ),\n                    bar_time,\n                    {\n                        "target_income_weight": target,\n                        "allocation_years": allocation_years,\n                    },\n                )\n\n            account.last_allocation_years = allocation_years\n            portfolio = _portfolio(account)\n\n            pending_items = sorted(\n                account.pending.values(),\n                key=lambda item: (\n                    item.tie_key,\n                    item.symbol,\n                ),\n            )\n            account.pending = {}\n\n            for signal in pending_items:\n                signal_time = datetime.fromisoformat(\n                    signal.signal_bar\n                )\n\n                if bar_time <= signal_time:\n                    account.pending[signal.symbol] = signal\n                    continue\n\n                if (\n                    len(portfolio.positions)\n                    >= policy.maximum_concurrent_positions\n                ):\n                    deferred_capacity += 1\n                    store.event(\n                        "ENTRY_CANCELLED_CAPACITY",\n                        bar_time,\n                        {"symbol": signal.symbol},\n                    )\n                    continue\n\n                bar = maps[signal.symbol][bar_time]\n                gap_atr = (\n                    abs(bar.open - signal.prior_close)\n                    / signal.signal_atr\n                )\n\n                if gap_atr > policy.maximum_gap_atr_multiple:\n                    rejected_gap += 1\n                    store.event(\n                        "ENTRY_REJECTED_GAP",\n                        bar_time,\n                        {\n                            "symbol": signal.symbol,\n                            "gap_atr": gap_atr,\n                        },\n                    )\n                    continue\n\n                open_prices = {\n                    symbol: maps[symbol][bar_time].open\n                    for symbol in portfolio.positions\n                }\n                total_equity = (\n                    portfolio.equity(open_prices)\n                    + account.income_shares * qdte_bar.open\n                )\n                sizing = calculate_position_size(\n                    account_equity=total_equity,\n                    available_cash=portfolio.cash,\n                    entry_price=bar.open,\n                    atr=signal.signal_atr,\n                    active_risk=portfolio.active_risk(),\n                    config=config,\n                    trade_results_r=account.trade_results_r,\n                )\n\n                if not sizing.is_tradeable:\n                    rejected_risk += 1\n                    store.event(\n                        "ENTRY_REJECTED_RISK",\n                        bar_time,\n                        {\n                            "symbol": signal.symbol,\n                            "reason": sizing.blocked_reason,\n                        },\n                    )\n                    continue\n\n                portfolio.open_position(\n                    symbol=signal.symbol,\n                    sizing=sizing,\n                    entry_date=bar_time.date(),\n                    entry_atr=signal.signal_atr,\n                )\n                filled += 1\n                store.event(\n                    "ENTRY_FILLED_15M",\n                    bar_time,\n                    {\n                        "symbol": signal.symbol,\n                        "shares": sizing.shares,\n                        "fill_price": sizing.entry_fill,\n                        "planned_risk": sizing.planned_risk,\n                    },\n                )\n\n            for position in list(\n                portfolio.positions.values()\n            ):\n                symbol = position.symbol\n                index = index_maps[symbol][bar_time]\n                atr = indicators[symbol].atr[index]\n\n                if atr is None or atr <= 0:\n                    continue\n\n                bar = maps[symbol][bar_time]\n                evaluation = evaluate_exit(\n                    position=position,\n                    candle=Candle(\n                        date=bar_time.date(),\n                        open=bar.open,\n                        high=bar.high,\n                        low=bar.low,\n                        close=bar.close,\n                        volume=bar.volume,\n                    ),\n                    current_atr=atr,\n                    config=config,\n                )\n\n                if evaluation.should_exit:\n                    trade = portfolio.close_position(\n                        symbol=symbol,\n                        exit_price=float(\n                            evaluation.exit_price\n                        ),\n                        exit_date=bar_time.date(),\n                        reason=(\n                            evaluation.reason\n                            or "EXIT"\n                        ),\n                        config=config,\n                    )\n                    closed += 1\n                    store.event(\n                        "POSITION_CLOSED_15M",\n                        bar_time,\n                        {\n                            "symbol": symbol,\n                            "pnl": trade.pnl,\n                            "reason": trade.reason,\n                            "result_r": trade.result_r,\n                        },\n                    )\n                else:\n                    position.stop_price = (\n                        evaluation.next_stop_price\n                    )\n                    position.highest_price = (\n                        evaluation.highest_price\n                    )\n\n            qualifying: list[str] = []\n            open_symbols = set(portfolio.positions)\n            pending_symbols = set(account.pending)\n\n            for symbol in policy.candidates:\n                index = index_maps[symbol][bar_time]\n                evaluation = evaluate_entry(\n                    candles=candle_sets[symbol],\n                    indicators=indicators[symbol],\n                    index=index,\n                    vix=maps["^VIX"][bar_time].close,\n                    config=config,\n                )\n                evaluations += 1\n\n                if (\n                    evaluation.should_enter\n                    and symbol not in open_symbols\n                    and symbol not in pending_symbols\n                ):\n                    qualifying.append(symbol)\n                    qualifying_count += 1\n\n                events.append(\n                    {\n                        "bar_time": bar_time.isoformat(),\n                        "symbol": symbol,\n                        "should_enter": evaluation.should_enter,\n                        "triggers": list(evaluation.triggers),\n                        "failed_checks": list(\n                            evaluation.failed_checks\n                        ),\n                    }\n                )\n\n            available_slots = max(\n                0,\n                policy.maximum_concurrent_positions\n                - len(portfolio.positions)\n                - len(account.pending),\n            )\n            accepted, deferred = choose_without_ranking(\n                signal_bar=bar_time,\n                qualifying=qualifying,\n                available_slots=available_slots,\n            )\n            deferred_capacity += len(deferred)\n\n            for symbol in accepted:\n                index = index_maps[symbol][bar_time]\n                atr = indicators[symbol].atr[index]\n\n                if atr is None or atr <= 0:\n                    continue\n\n                bar = maps[symbol][bar_time]\n                tie_key = hashlib.sha256(\n                    (\n                        bar_time.isoformat()\n                        + "|"\n                        + symbol\n                    ).encode("utf-8")\n                ).hexdigest()\n                account.pending[symbol] = PendingSignal(\n                    symbol=symbol,\n                    signal_bar=bar_time.isoformat(),\n                    signal_atr=atr,\n                    prior_close=bar.close,\n                    tie_key=tie_key,\n                )\n                store.event(\n                    "ENTRY_STAGED_15M",\n                    bar_time,\n                    {\n                        "symbol": symbol,\n                        "next_bar_execution": True,\n                    },\n                )\n\n            _sync(account, portfolio)\n            account.last_processed_bar = bar_time.isoformat()\n            account.revision += 1\n\n        account.validate(policy)\n        store.save(account, policy)\n\n        latest_prices = {\n            symbol: maps[symbol][latest].close\n            for symbol in account.positions\n        }\n        portfolio = _portfolio(account)\n        swing_equity = portfolio.equity(latest_prices)\n        income_value = (\n            account.income_shares\n            * maps["QDTE"][latest].close\n        )\n        summary = {\n            "schema_version": 1,\n            "generated_at_utc": datetime.now(\n                timezone.utc\n            ).isoformat(),\n            "status": "PROCESSED",\n            "market_time": now_market.isoformat(),\n            "latest_completed_bar": latest.isoformat(),\n            "bars_processed": len(new_times),\n            "eight_symbol_evaluations": evaluations,\n            "qualifying_signals": qualifying_count,\n            "filled_entries": filled,\n            "closed_positions": closed,\n            "gap_rejections": rejected_gap,\n            "risk_rejections": rejected_risk,\n            "capacity_deferred": deferred_capacity,\n            "open_positions": len(account.positions),\n            "pending_entries": len(account.pending),\n            "maximum_positions": 6,\n            "position_symbols": sorted(account.positions),\n            "swing_equity": swing_equity,\n            "income_value": income_value,\n            "total_equity": swing_equity + income_value,\n            "total_contributions": account.total_contributions,\n            "rankings_enabled": False,\n            "interval": "15m",\n            "extended_hours_enabled": False,\n            "live_broker_enabled": False,\n            "migration": migration,\n            "initialized_this_cycle": initialized,\n        }\n        report_path = (\n            report_dir\n            / "latest_15m_paper_status.json"\n        )\n        temporary = report_path.with_suffix(".json.tmp")\n        temporary.write_text(\n            json.dumps(\n                summary,\n                indent=2,\n                sort_keys=True,\n            )\n            + "\\n",\n            encoding="utf-8",\n        )\n        temporary.replace(report_path)\n\n        diagnostics_path = (\n            report_dir\n            / "latest_15m_entry_diagnostics.json"\n        )\n        diagnostics_temp = diagnostics_path.with_suffix(".json.tmp")\n        diagnostics_temp.write_text(\n            json.dumps(\n                {\n                    "generated_at_utc": summary[\n                        "generated_at_utc"\n                    ],\n                    "bars": events,\n                },\n                indent=2,\n            )\n            + "\\n",\n            encoding="utf-8",\n        )\n        diagnostics_temp.replace(diagnostics_path)\n        return summary\n\n\ndef _parser() -> argparse.ArgumentParser:\n    parser = argparse.ArgumentParser(\n        description=(\n            "Check all eight QPX ETFs on every completed "\n            "regular-session 15-minute bar and paper-trade "\n            "up to six positions."\n        )\n    )\n    parser.add_argument(\n        "--policy",\n        default=str(DEFAULT_POLICY),\n    )\n    parser.add_argument(\n        "--runtime-dir",\n        default=str(DEFAULT_RUNTIME),\n    )\n    parser.add_argument(\n        "--legacy-runtime-dir",\n        default=str(DEFAULT_LEGACY_RUNTIME),\n    )\n    parser.add_argument(\n        "--report-dir",\n        default=str(DEFAULT_REPORTS),\n    )\n    return parser\n\n\ndef main(argv: Sequence[str] | None = None) -> int:\n    args = _parser().parse_args(argv)\n    summary = run_cycle(\n        policy_path=args.policy,\n        runtime_directory=args.runtime_dir,\n        legacy_runtime_directory=args.legacy_runtime_dir,\n        report_directory=args.report_dir,\n    )\n    print("=" * 78)\n    print(\n        "QPX BOT v1.22.1 — 15-MINUTE EIGHT-TICKER "\n        "SIX-POSITION PAPER ENGINE"\n    )\n    print("=" * 78)\n\n    for key, value in summary.items():\n        print(f"{key:<28}: {value}")\n\n    print("Rankings                    : REMOVED")\n    print("Live brokerage              : DISABLED")\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n',
    "QPX_RUN_15M_PAPER.py": '#!/usr/bin/env python3\n"""Run one regular-session QPX 15-minute paper cycle."""\n\nfrom qpx_bot.intraday_six_paper import main\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n',
    "QPX_RUN_AUTO_PAPER.py": '#!/usr/bin/env python3\n"""Compatibility entry point for the active QPX 15-minute paper engine."""\n\nfrom qpx_bot.intraday_six_paper import main\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n',
    "QPX_START_15M_DAEMON.py": '#!/usr/bin/env python3\n"""Fallback quarter-hour daemon when Termux crond is unavailable."""\n\nfrom __future__ import annotations\n\nfrom datetime import datetime, timedelta\nfrom pathlib import Path\nimport os\nimport subprocess\nimport sys\nimport time\n\n\nROOT = Path(__file__).resolve().parent\nRUNTIME = ROOT / "qpx_bot" / "intraday_six_runtime"\nPID_PATH = RUNTIME / "daemon.pid"\nLOG_PATH = RUNTIME / "daemon.log"\n\n\ndef _alive(pid: int) -> bool:\n    try:\n        os.kill(pid, 0)\n    except OSError:\n        return False\n    return True\n\n\ndef _next_quarter(now: datetime) -> datetime:\n    base = now.replace(second=0, microsecond=0)\n    minutes = ((base.minute // 15) + 1) * 15\n\n    if minutes >= 60:\n        return (\n            base.replace(minute=0)\n            + timedelta(hours=1)\n        )\n\n    return base.replace(minute=minutes)\n\n\ndef main() -> int:\n    RUNTIME.mkdir(parents=True, exist_ok=True)\n\n    if PID_PATH.exists():\n        try:\n            existing = int(\n                PID_PATH.read_text(encoding="utf-8").strip()\n            )\n        except (OSError, ValueError):\n            existing = -1\n\n        if existing > 0 and _alive(existing):\n            print(\n                f"QPX 15-minute daemon is already running "\n                f"with PID {existing}."\n            )\n            return 0\n\n    PID_PATH.write_text(\n        str(os.getpid()) + "\\n",\n        encoding="utf-8",\n    )\n\n    try:\n        while True:\n            now = datetime.now()\n            target = _next_quarter(now)\n            delay = max(\n                1.0,\n                (target - now).total_seconds(),\n            )\n            time.sleep(delay)\n\n            with LOG_PATH.open(\n                "a",\n                encoding="utf-8",\n            ) as log:\n                subprocess.run(\n                    [\n                        sys.executable,\n                        str(\n                            ROOT / "QPX_RUN_15M_PAPER.py"\n                        ),\n                    ],\n                    cwd=ROOT,\n                    stdout=log,\n                    stderr=subprocess.STDOUT,\n                    check=False,\n                )\n    finally:\n        try:\n            PID_PATH.unlink()\n        except FileNotFoundError:\n            pass\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n',
    "tests/test_qpx_bot_intraday_six_paper.py": 'from datetime import datetime, timedelta\nfrom pathlib import Path\n\nfrom qpx_bot.config import BotConfig\nfrom qpx_bot.market_calendar import NEW_YORK\nfrom qpx_bot.intraday_six_paper import (\n    choose_without_ranking,\n    load_policy,\n    scan_window_open,\n)\n\n\npolicy = load_policy()\nconfig = BotConfig()\nconfig.validate()\n\nassert policy.interval == "15m"\nassert policy.maximum_concurrent_positions == 6\nassert config.maximum_swing_positions == 6\nassert len(policy.candidates) == 8\nassert not policy.rankings_enabled\nassert not policy.extended_hours_enabled\nassert not policy.live_broker_enabled\n\nmarket = NEW_YORK\n\nassert datetime(\n    2026,\n    1,\n    15,\n    12,\n    0,\n    tzinfo=market,\n).utcoffset() == timedelta(hours=-5)\nassert datetime(\n    2026,\n    7,\n    15,\n    12,\n    0,\n    tzinfo=market,\n).utcoffset() == timedelta(hours=-4)\n\nassert scan_window_open(\n    datetime(2026, 8, 6, 9, 45, tzinfo=market),\n    policy,\n)\nassert scan_window_open(\n    datetime(2026, 8, 6, 16, 0, tzinfo=market),\n    policy,\n)\nassert not scan_window_open(\n    datetime(2026, 8, 6, 9, 30, tzinfo=market),\n    policy,\n)\nassert not scan_window_open(\n    datetime(2026, 8, 8, 10, 0, tzinfo=market),\n    policy,\n)\n\naccepted_a, deferred_a = choose_without_ranking(\n    signal_bar=datetime(\n        2026,\n        8,\n        6,\n        10,\n        0,\n        tzinfo=market,\n    ),\n    qualifying=policy.candidates,\n    available_slots=6,\n)\naccepted_b, deferred_b = choose_without_ranking(\n    signal_bar=datetime(\n        2026,\n        8,\n        6,\n        10,\n        0,\n        tzinfo=market,\n    ),\n    qualifying=tuple(reversed(policy.candidates)),\n    available_slots=6,\n)\n\nassert accepted_a == accepted_b\nassert deferred_a == deferred_b\nassert len(accepted_a) == 6\nassert len(deferred_a) == 2\nassert set((*accepted_a, *deferred_a)) == set(policy.candidates)\n\nsource = (\n    Path(__file__).resolve().parents[1]\n    / "qpx_bot"\n    / "intraday_six_paper.py"\n).read_text(encoding="utf-8")\n\nfor required in (\n    \'interval != "15m"\',\n    "maximum_concurrent_positions != 6",\n    "for symbol in policy.candidates:",\n    "evaluate_entry(",\n    "evaluate_exit(",\n    "calculate_position_size(",\n    "portfolio.active_risk()",\n    "ENTRY_STAGED_15M",\n    "live_broker_enabled",\n):\n    assert required in source\n\nfor prohibited in (\n    "rank_candidates(",\n    "selected_symbol",\n    "monthly_winner",\n):\n    assert prohibited not in source\n\nwrapper = (\n    Path(__file__).resolve().parents[1]\n    / "QPX_RUN_AUTO_PAPER.py"\n).read_text(encoding="utf-8")\nassert "intraday_six_paper" in wrapper\nassert "auto_paper" not in wrapper\n\nprint(\n    "QPX Bot 15-Minute Eight-Ticker "\n    "Six-Position Paper PASS"\n)\n',
    "qpx_bot/INTRADAY_SIX_POSITION_README.txt": "QPX 15-MINUTE EIGHT-TICKER SIX-POSITION PAPER ENGINE\n=====================================================\n\nActive swing universe\n---------------------\n\nDIA\nIWM\nQQQ\nSPY\nXLE\nXLF\nXLK\nXLV\n\nOperating schedule\n------------------\n\nThe one-shot runner is scheduled every 15 minutes on weekdays. The\nrunner itself enforces the New York regular-session calendar and only\nprocesses completed 15-minute bars from 09:45 through 16:00 ET.\n\nExtended-hours bars are excluded.\n\nEntry and position policy\n-------------------------\n\nAll eight ETFs are evaluated on every completed 15-minute bar.\n\nMonthly rankings, winner selection, symbol bonuses, preferred symbols,\nand fallback symbols are not used.\n\nUp to six different ETF positions may be open or pending at one time.\nThe existing 1% base risk per trade and 6% aggregate active-risk cap\nremain active. A sixth position is not guaranteed: cash, quarter-Kelly\nsizing, opening-gap controls, or the global risk limit may reject it.\n\nSignals are generated from a completed 15-minute bar and executed using\nthe next completed 15-minute bar's opening price. The 1.5 ATR opening\ngap rejection remains active.\n\nAccount migration\n-----------------\n\nOn its first in-session run, the engine copies the current persistent\npaper-account snapshot into a new multi-position runtime. It preserves\nQDTE shares, swing cash, tax reserves, contributions, realized P&L, and\nan existing open swing position.\n\nThe original single-position paper state is not changed or deleted.\nAn old pending daily instruction is cancelled during migration because\nit is incompatible with the new 15-minute execution clock.\n\nFiles\n-----\n\nOne-shot runner:\n    python QPX_RUN_15M_PAPER.py\n\nCompatibility runner:\n    python QPX_RUN_AUTO_PAPER.py\n\nFallback daemon:\n    python QPX_START_15M_DAEMON.py\n\nRuntime:\n    qpx_bot/intraday_six_runtime/\n\nLatest status:\n    reports/qpx_intraday_six/latest_15m_paper_status.json\n\nLatest entry diagnostics:\n    reports/qpx_intraday_six/latest_15m_entry_diagnostics.json\n\nSafety\n------\n\nThis remains simulated paper trading. Live brokerage is disabled.\nHistorical or paper results do not guarantee future performance.\n",
}

PATCHES = {
    "qpx_bot/config.py": (
        (
            "maximum_swing_positions: int = 3",
            "maximum_swing_positions: int = 6",
        ),
        (
            "This strategy requires exactly three swing slots.",
            "This strategy requires exactly six swing slots.",
        ),
        (
            "if self.maximum_swing_positions != 3:",
            "if self.maximum_swing_positions != 6:",
        ),
    ),
    "qpx_bot/multi_swing_policy.json": (
        (
            '"maximum_concurrent_positions": 3',
            '"maximum_concurrent_positions": 6',
        ),
    ),
    "qpx_bot/actual_two_year_three_position.py": (
        (
            "maximum_concurrent_positions != 3",
            "maximum_concurrent_positions != 6",
        ),
        (
            "Exactly three concurrent swing slots are required.",
            "Exactly six concurrent swing slots are required.",
        ),
        (
            "THREE-POSITION BACKTEST",
            "SIX-POSITION BACKTEST",
        ),
    ),
    "tests/test_qpx_bot_unranked_three_position.py": (
        (
            "config.maximum_swing_positions == 3",
            "config.maximum_swing_positions == 6",
        ),
        (
            "policy.maximum_concurrent_positions == 3",
            "policy.maximum_concurrent_positions == 6",
        ),
        (
            "available_slots=3,",
            "available_slots=6,",
        ),
        (
            "assert len(accepted_a) == 3",
            "assert len(accepted_a) == 6",
        ),
        (
            "assert len(deferred_a) == 5",
            "assert len(deferred_a) == 2",
        ),
        (
            "Unranked Three-Position",
            "Unranked Six-Position",
        ),
    ),
}

GITIGNORE_APPEND = '# QPX 15-minute six-position paper runtime\nqpx_bot/intraday_six_runtime/\nreports/qpx_intraday_six/\n'
TARGETS = [
    *FILES,
    *PATCHES,
    ".gitignore",
]
originals: dict[str, bytes | None] = {}


def run(
    command: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess:
    print("$ " + " ".join(command))
    return subprocess.run(
        command,
        cwd=ROOT,
        check=check,
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


def ensure_safe() -> None:
    changed: list[str] = []

    for relative in TARGETS:
        path = ROOT / relative
        worktree = subprocess.run(
            ["git", "diff", "--quiet", "--", relative],
            cwd=ROOT,
        )
        staged = subprocess.run(
            ["git", "diff", "--cached", "--quiet", "--", relative],
            cwd=ROOT,
        )

        if worktree.returncode or staged.returncode:
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
            "These target files contain local changes and were "
            "not overwritten:\n"
            + "\n".join(changed)
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
        backup = BACKUP / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)


def install_files() -> None:
    for relative, content in FILES.items():
        preserve(relative)
        path = ROOT / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            textwrap.dedent(content).strip() + "\n",
            encoding="utf-8",
        )

        if path.name.startswith("QPX_"):
            path.chmod(0o700)

        print(f"Installed: {relative}")


def apply_patches() -> None:
    for relative, replacements in PATCHES.items():
        preserve(relative)
        path = ROOT / relative
        source = path.read_text(encoding="utf-8")

        for old, new in replacements:
            if old in source:
                source = source.replace(old, new)
            elif new in source:
                continue
            else:
                raise RuntimeError(
                    f"Expected patch marker was not found in "
                    f"{relative}: {old}"
                )

        if relative.endswith(".py"):
            compile(source, relative, "exec")

        path.write_text(source, encoding="utf-8")
        print(f"Updated: {relative}")


def patch_gitignore() -> None:
    relative = ".gitignore"
    preserve(relative)
    path = ROOT / relative
    content = path.read_text(encoding="utf-8")
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


def restore() -> None:
    print("Restoring previous target files...")

    for relative, original in originals.items():
        path = ROOT / relative

        if original is None:
            if path.exists():
                path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(original)


def install_schedule() -> str:
    marker = "# QPX_15M_EIGHT_TICKER_SIX_POSITION"
    python_path = sys.executable
    log_path = (
        ROOT
        / "qpx_bot"
        / "intraday_six_runtime"
        / "cron.log"
    )
    line = (
        "*/15 * * * 1-5 "
        f"cd {ROOT} && {python_path} "
        "QPX_RUN_15M_PAPER.py "
        f">> {log_path} 2>&1 "
        f"{marker}"
    )

    if shutil.which("crontab"):
        existing = subprocess.run(
            ["crontab", "-l"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        ).stdout
        retained = [
            item
            for item in existing.splitlines()
            if marker not in item
        ]
        payload = "\n".join(
            [*retained, line]
        ).strip() + "\n"
        result = subprocess.run(
            ["crontab", "-"],
            cwd=ROOT,
            input=payload,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            raise RuntimeError(
                "Unable to install the 15-minute crontab entry."
            )

        if shutil.which("crond"):
            subprocess.run(
                ["crond"],
                cwd=ROOT,
                check=False,
            )

        return "TERMUX_CRON_EVERY_15_MINUTES"

    runtime = (
        ROOT
        / "qpx_bot"
        / "intraday_six_runtime"
    )
    runtime.mkdir(parents=True, exist_ok=True)
    daemon_log = runtime / "daemon_boot.log"

    with daemon_log.open("a", encoding="utf-8") as log:
        subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "QPX_START_15M_DAEMON.py"),
            ],
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    return "BACKGROUND_DAEMON_EVERY_15_MINUTES"


def commit_and_push() -> None:
    paths = list(TARGETS)

    try:
        paths.append(
            str(Path(__file__).resolve().relative_to(ROOT))
        )
    except ValueError:
        pass

    run(["git", "add", "--", *paths])

    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=ROOT,
    )

    if staged.returncode == 0:
        print("15-minute six-position engine is already committed.")
        return

    run([
        "git",
        "commit",
        "-m",
        (
            "Add dependency-free 15-minute eight-ticker "
            "six-position paper engine"
        ),
    ])
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"],
        cwd=ROOT,
        text=True,
    ).strip()

    if not branch:
        raise RuntimeError("Cannot push from detached Git state.")

    run(["git", "push", "origin", branch])


def main() -> int:
    print("=" * 78)
    print(
        "QPX BOT — 15-MINUTE EIGHT-TICKER "
        "SIX-POSITION PAPER INSTALLER V2"
    )
    print("=" * 78)
    print(f"Project: {ROOT}")

    ensure_safe()

    try:
        install_files()
        apply_patches()
        patch_gitignore()
        run([
            sys.executable,
            "-m",
            "tests.test_qpx_bot_intraday_six_paper",
        ])
        run([
            sys.executable,
            "tests/run_all_tests.py",
        ])
    except Exception:
        restore()
        raise

    schedule = install_schedule()
    commit_and_push()

    print()
    print(f"Schedule: {schedule}")
    print(
        "Attempting one immediate cycle. Outside the regular "
        "session this safely reports a no-op."
    )
    result = run(
        [
            sys.executable,
            "QPX_RUN_15M_PAPER.py",
        ],
        check=False,
    )

    if result.returncode != 0:
        print()
        print(
            "Code, tests, schedule, commit, and push completed, "
            "but the immediate provider cycle needs a retry."
        )
        return result.returncode

    print()
    print("=" * 78)
    print(
        "QPX 15-MINUTE EIGHT-TICKER "
        "SIX-POSITION PAPER V2: COMPLETE"
    )
    print("=" * 78)
    print(
        "All eight ETFs are checked on completed regular-session "
        "15-minute bars. Rankings are removed. Maximum positions: 6. "
        "Live brokerage remains disabled."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
