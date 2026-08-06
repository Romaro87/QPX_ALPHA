#!/usr/bin/env python3
"""Fix Yahoo daily bars, test, push, and rerun the real QPX backtest."""

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
        for candidate in (start, *start.parents):
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
BACKUP = ROOT / "backups" / "qpx_daily_data_fix" / STAMP

FILES = {
    "qpx_bot/yahoo_data.py": '"""Dependency-free Yahoo chart data acquisition for QPX Bot."""\n\nfrom __future__ import annotations\n\nimport csv\nimport json\nimport shutil\nimport time\nimport urllib.error\nimport urllib.parse\nimport urllib.request\nfrom collections.abc import Callable, Mapping, Sequence\nfrom dataclasses import asdict, dataclass\nfrom datetime import date, datetime, timedelta, timezone\nfrom statistics import median\nfrom pathlib import Path\nfrom typing import Any\n\nfrom qpx_bot.real_data import sha256_file\n\n\nYAHOO_HOSTS = (\n    "query1.finance.yahoo.com",\n    "query2.finance.yahoo.com",\n)\n\n\nclass YahooDataError(RuntimeError):\n    """Raised when a complete, valid chart response cannot be obtained."""\n\n\n@dataclass(frozen=True, slots=True)\nclass MarketRow:\n    date: date\n    open: float\n    high: float\n    low: float\n    close: float\n    volume: int\n\n\n@dataclass(frozen=True, slots=True)\nclass DividendRow:\n    date: date\n    amount: float\n\n\n@dataclass(frozen=True, slots=True)\nclass DownloadSummary:\n    provider: str\n    swing_symbol: str\n    income_symbol: str\n    vix_symbol: str\n    swing_rows: int\n    income_rows: int\n    vix_rows: int\n    dividend_events: int\n    common_first_date: date\n    common_last_date: date\n    input_directory: Path\n    manifest_path: Path\n\n\n\ndef _daily_period_bounds(\n    range_name: str,\n) -> tuple[int, int, str]:\n    """\n    Convert a requested range into a bounded daily-data window.\n\n    Yahoo can silently downgrade ``range=max`` requests to weekly or\n    monthly bars. QPX therefore requests explicit Unix timestamps.\n    Five years stays inside the provider\'s daily-history limits while\n    fully covering QDTE\'s available history.\n    """\n    normalized = range_name.strip().lower()\n    years = 5\n\n    if normalized not in {"", "max", "daily"}:\n        if normalized.endswith("y") and normalized[:-1].isdigit():\n            years = int(normalized[:-1])\n        else:\n            raise ValueError(\n                "History range must be max, daily, or a value such "\n                "as 3y, 5y, or 8y."\n            )\n\n    years = max(1, min(years, 8))\n    end = datetime.now(timezone.utc) + timedelta(days=2)\n    start = end - timedelta(days=366 * years)\n\n    return (\n        int(start.timestamp()),\n        int(end.timestamp()),\n        f"{years}y-daily",\n    )\n\n\ndef _chart_url(\n    host: str,\n    symbol: str,\n    *,\n    range_name: str,\n) -> str:\n    encoded_symbol = urllib.parse.quote(symbol, safe="")\n    period1, period2, _ = _daily_period_bounds(range_name)\n    query = urllib.parse.urlencode(\n        {\n            "period1": period1,\n            "period2": period2,\n            "interval": "1d",\n            "events": "div,splits",\n            "includePrePost": "false",\n            "includeAdjustedClose": "true",\n        }\n    )\n    return (\n        f"https://{host}/v8/finance/chart/"\n        f"{encoded_symbol}?{query}"\n    )\n\n\n\ndef _open_json(url: str, timeout_seconds: float) -> Mapping[str, Any]:\n    request = urllib.request.Request(\n        url,\n        headers={\n            "User-Agent": (\n                "Mozilla/5.0 (Linux; Android 14) "\n                "AppleWebKit/537.36 QPXBot/1.7"\n            ),\n            "Accept": "application/json,text/plain,*/*",\n            "Accept-Encoding": "identity",\n            "Connection": "close",\n        },\n    )\n\n    with urllib.request.urlopen(\n        request,\n        timeout=timeout_seconds,\n    ) as response:\n        raw = response.read()\n\n    try:\n        payload = json.loads(raw.decode("utf-8"))\n    except (UnicodeDecodeError, json.JSONDecodeError) as exc:\n        raise YahooDataError(\n            "The provider returned a non-JSON response."\n        ) from exc\n\n    chart = payload.get("chart")\n\n    if not isinstance(chart, Mapping):\n        raise YahooDataError("Chart response is missing.")\n\n    provider_error = chart.get("error")\n\n    if provider_error:\n        raise YahooDataError(\n            f"Provider error: {provider_error}"\n        )\n\n    results = chart.get("result")\n\n    if not isinstance(results, list) or not results:\n        raise YahooDataError("Chart response contains no result.")\n\n    result = results[0]\n\n    if not isinstance(result, Mapping):\n        raise YahooDataError("Chart result has an invalid shape.")\n\n    return result\n\n\n\ndef _validate_daily_result(\n    result: Mapping[str, Any],\n    symbol: str,\n) -> None:\n    """Reject provider responses that were silently downsampled."""\n    meta = result.get("meta")\n    granularity = None\n\n    if isinstance(meta, Mapping):\n        raw_granularity = meta.get("dataGranularity")\n        if raw_granularity is not None:\n            granularity = str(raw_granularity).strip().lower()\n\n    if granularity and granularity != "1d":\n        raise YahooDataError(\n            f"{symbol} returned {granularity} bars instead of "\n            "required 1d bars."\n        )\n\n    timestamps = _sequence(result, "timestamp")\n\n    if len(timestamps) < 2:\n        raise YahooDataError(\n            f"{symbol} returned too few observations."\n        )\n\n    dates = [\n        datetime.fromtimestamp(\n            float(timestamp),\n            tz=timezone.utc,\n        ).date()\n        for timestamp in timestamps\n        if timestamp is not None\n    ]\n\n    if len(dates) < 2:\n        raise YahooDataError(\n            f"{symbol} returned too few valid timestamps."\n        )\n\n    gaps = [\n        (current - previous).days\n        for previous, current in zip(dates, dates[1:])\n        if current > previous\n    ]\n\n    if not gaps:\n        raise YahooDataError(\n            f"{symbol} returned no increasing daily dates."\n        )\n\n    typical_gap = float(median(gaps))\n\n    if typical_gap > 4.0:\n        raise YahooDataError(\n            f"{symbol} appears downsampled; median bar gap is "\n            f"{typical_gap:.1f} days."\n        )\n\n\ndef fetch_chart(\n    symbol: str,\n    *,\n    range_name: str = "max",\n    timeout_seconds: float = 30.0,\n    maximum_attempts: int = 6,\n) -> Mapping[str, Any]:\n    """Fetch one true daily chart with host failover and backoff."""\n    normalized = symbol.strip().upper()\n\n    if not normalized:\n        raise ValueError("Ticker symbol cannot be empty.")\n\n    if maximum_attempts < 1:\n        raise ValueError("Maximum attempts must be positive.")\n\n    errors: list[str] = []\n\n    for attempt in range(1, maximum_attempts + 1):\n        host = YAHOO_HOSTS[(attempt - 1) % len(YAHOO_HOSTS)]\n        url = _chart_url(\n            host,\n            normalized,\n            range_name=range_name,\n        )\n\n        try:\n            result = _open_json(url, timeout_seconds)\n            _validate_daily_result(result, normalized)\n            return result\n        except (\n            YahooDataError,\n            urllib.error.HTTPError,\n            urllib.error.URLError,\n            TimeoutError,\n            OSError,\n        ) as exc:\n            errors.append(\n                f"attempt {attempt} via {host}: "\n                f"{type(exc).__name__}: {exc}"\n            )\n\n            if attempt < maximum_attempts:\n                delay = min(12.0, 1.5 * attempt)\n                print(\n                    f"Provider retry {attempt}/"\n                    f"{maximum_attempts} in {delay:.1f}s..."\n                )\n                time.sleep(delay)\n\n    raise YahooDataError(\n        f"Unable to download true daily {normalized} data after "\n        f"{maximum_attempts} attempts.\\n"\n        + "\\n".join(errors)\n    )\n\n\n\ndef _sequence(\n    mapping: Mapping[str, Any],\n    name: str,\n) -> Sequence[Any]:\n    value = mapping.get(name, ())\n\n    if isinstance(value, Sequence) and not isinstance(\n        value,\n        (str, bytes),\n    ):\n        return value\n\n    return ()\n\n\ndef extract_market_rows(\n    result: Mapping[str, Any],\n) -> list[MarketRow]:\n    """Convert a Yahoo chart result into validated daily rows."""\n    meta = result.get("meta")\n    symbol = "UNKNOWN"\n\n    if isinstance(meta, Mapping):\n        symbol = str(meta.get("symbol") or symbol)\n\n    _validate_daily_result(result, symbol)\n    timestamps = _sequence(result, "timestamp")\n    indicators = result.get("indicators")\n\n    if not isinstance(indicators, Mapping):\n        raise YahooDataError("Chart indicators are missing.")\n\n    quotes = indicators.get("quote")\n\n    if not isinstance(quotes, list) or not quotes:\n        raise YahooDataError("Chart quote arrays are missing.")\n\n    quote = quotes[0]\n\n    if not isinstance(quote, Mapping):\n        raise YahooDataError("Chart quote data is invalid.")\n\n    opens = _sequence(quote, "open")\n    highs = _sequence(quote, "high")\n    lows = _sequence(quote, "low")\n    closes = _sequence(quote, "close")\n    volumes = _sequence(quote, "volume")\n\n    rows: list[MarketRow] = []\n\n    for index, timestamp in enumerate(timestamps):\n        try:\n            open_price = opens[index]\n            high_price = highs[index]\n            low_price = lows[index]\n            close_price = closes[index]\n        except IndexError:\n            continue\n\n        if any(\n            value is None\n            for value in (\n                timestamp,\n                open_price,\n                high_price,\n                low_price,\n                close_price,\n            )\n        ):\n            continue\n\n        volume_value = (\n            volumes[index]\n            if index < len(volumes)\n            and volumes[index] is not None\n            else 0\n        )\n\n        row = MarketRow(\n            date=datetime.fromtimestamp(\n                float(timestamp),\n                tz=timezone.utc,\n            ).date(),\n            open=float(open_price),\n            high=float(high_price),\n            low=float(low_price),\n            close=float(close_price),\n            volume=max(0, int(float(volume_value))),\n        )\n\n        if row.open <= 0 or row.close <= 0:\n            continue\n\n        if row.high < max(row.open, row.close, row.low):\n            continue\n\n        if row.low > min(row.open, row.close, row.high):\n            continue\n\n        rows.append(row)\n\n    rows.sort(key=lambda row: row.date)\n\n    deduplicated: dict[date, MarketRow] = {\n        row.date: row\n        for row in rows\n    }\n    rows = [\n        deduplicated[day]\n        for day in sorted(deduplicated)\n    ]\n\n    if not rows:\n        raise YahooDataError(\n            "No valid daily market rows were returned."\n        )\n\n    return rows\n\n\ndef extract_dividend_rows(\n    result: Mapping[str, Any],\n) -> list[DividendRow]:\n    """Extract and combine cash distributions by calendar date."""\n    events = result.get("events")\n\n    if not isinstance(events, Mapping):\n        return []\n\n    dividends = events.get("dividends")\n\n    if not isinstance(dividends, Mapping):\n        return []\n\n    amounts: dict[date, float] = {}\n\n    for event in dividends.values():\n        if not isinstance(event, Mapping):\n            continue\n\n        timestamp = event.get("date")\n        amount = event.get("amount")\n\n        if timestamp is None or amount is None:\n            continue\n\n        event_date = datetime.fromtimestamp(\n            float(timestamp),\n            tz=timezone.utc,\n        ).date()\n        numeric_amount = float(amount)\n\n        if numeric_amount < 0:\n            raise YahooDataError(\n                "Negative dividend amount was returned."\n            )\n\n        amounts[event_date] = (\n            amounts.get(event_date, 0.0)\n            + numeric_amount\n        )\n\n    return [\n        DividendRow(date=event_date, amount=amounts[event_date])\n        for event_date in sorted(amounts)\n    ]\n\n\ndef _atomic_csv(\n    path: Path,\n    header: Sequence[str],\n    rows: Sequence[Sequence[Any]],\n) -> None:\n    path.parent.mkdir(parents=True, exist_ok=True)\n    temporary = path.with_name(path.name + ".tmp")\n\n    with temporary.open(\n        "w",\n        newline="",\n        encoding="utf-8",\n    ) as file:\n        writer = csv.writer(file)\n        writer.writerow(header)\n        writer.writerows(rows)\n\n    temporary.replace(path)\n\n\ndef _write_market(path: Path, rows: Sequence[MarketRow]) -> None:\n    _atomic_csv(\n        path,\n        ("Date", "Open", "High", "Low", "Close", "Volume"),\n        [\n            (\n                row.date.isoformat(),\n                f"{row.open:.8f}",\n                f"{row.high:.8f}",\n                f"{row.low:.8f}",\n                f"{row.close:.8f}",\n                row.volume,\n            )\n            for row in rows\n        ],\n    )\n\n\ndef _write_vix(path: Path, rows: Sequence[MarketRow]) -> None:\n    _atomic_csv(\n        path,\n        ("Date", "VIX"),\n        [\n            (\n                row.date.isoformat(),\n                f"{row.close:.8f}",\n            )\n            for row in rows\n        ],\n    )\n\n\ndef _write_dividends(\n    path: Path,\n    rows: Sequence[DividendRow],\n) -> None:\n    _atomic_csv(\n        path,\n        ("Date", "Dividend"),\n        [\n            (\n                row.date.isoformat(),\n                f"{row.amount:.8f}",\n            )\n            for row in rows\n        ],\n    )\n\n\ndef _backup_existing_files(\n    paths: Sequence[Path],\n    backup_directory: Path | None,\n) -> None:\n    if backup_directory is None:\n        return\n\n    existing = [path for path in paths if path.exists()]\n\n    if not existing:\n        return\n\n    backup_directory.mkdir(parents=True, exist_ok=True)\n\n    for path in existing:\n        shutil.copy2(path, backup_directory / path.name)\n\n    print(f"Previous input files backed up: {backup_directory}")\n\n\ndef download_real_dataset(\n    *,\n    swing_symbol: str,\n    input_directory: str | Path,\n    income_symbol: str = "QDTE",\n    vix_symbol: str = "^VIX",\n    range_name: str = "max",\n    backup_directory: str | Path | None = None,\n    fetcher: Callable[[str], Mapping[str, Any]] | None = None,\n) -> DownloadSummary:\n    """\n    Download swing, income, dividend, and VIX data atomically.\n\n    The default fetcher uses Yahoo\'s public chart endpoint. A custom\n    fetcher is accepted so the conversion path can be tested without\n    network access.\n    """\n    normalized_swing = swing_symbol.strip().upper()\n    normalized_income = income_symbol.strip().upper()\n    normalized_vix = vix_symbol.strip().upper()\n\n    if not normalized_swing:\n        raise ValueError("Swing symbol cannot be empty.")\n\n    directory = Path(input_directory).expanduser().resolve()\n    directory.mkdir(parents=True, exist_ok=True)\n\n    if fetcher is None:\n        def selected_fetcher(symbol: str) -> Mapping[str, Any]:\n            return fetch_chart(symbol, range_name=range_name)\n    else:\n        selected_fetcher = fetcher\n\n    print(f"Downloading {normalized_swing} daily history...")\n    swing_result = selected_fetcher(normalized_swing)\n\n    print(f"Downloading {normalized_income} daily history...")\n    income_result = selected_fetcher(normalized_income)\n\n    print(f"Downloading {normalized_vix} daily history...")\n    vix_result = selected_fetcher(normalized_vix)\n\n    swing_rows = extract_market_rows(swing_result)\n    income_rows = extract_market_rows(income_result)\n    vix_rows = extract_market_rows(vix_result)\n    dividend_rows = extract_dividend_rows(income_result)\n\n    if not dividend_rows:\n        raise YahooDataError(\n            f"No dividend events were returned for "\n            f"{normalized_income}."\n        )\n\n    output_paths = {\n        "swing": directory / "SWING.csv",\n        "income": directory / "QDTE.csv",\n        "dividends": directory / "QDTE_DIVIDENDS.csv",\n        "vix": directory / "VIX.csv",\n        "manifest": directory / "DOWNLOAD_MANIFEST.json",\n    }\n\n    backup_path = (\n        Path(backup_directory).expanduser().resolve()\n        if backup_directory is not None\n        else None\n    )\n    _backup_existing_files(\n        (\n            output_paths["swing"],\n            output_paths["income"],\n            output_paths["dividends"],\n            output_paths["vix"],\n            output_paths["manifest"],\n        ),\n        backup_path,\n    )\n\n    _write_market(output_paths["swing"], swing_rows)\n    _write_market(output_paths["income"], income_rows)\n    _write_dividends(\n        output_paths["dividends"],\n        dividend_rows,\n    )\n    _write_vix(output_paths["vix"], vix_rows)\n\n    common_first = max(\n        swing_rows[0].date,\n        income_rows[0].date,\n        vix_rows[0].date,\n    )\n    common_last = min(\n        swing_rows[-1].date,\n        income_rows[-1].date,\n        vix_rows[-1].date,\n    )\n\n    if common_first > common_last:\n        raise YahooDataError(\n            "Downloaded histories do not overlap."\n        )\n\n    manifest = {\n        "provider": "Yahoo Finance chart endpoint",\n        "downloaded_at_utc": datetime.now(\n            timezone.utc\n        ).isoformat(),\n        "requested_range": range_name,\n        "effective_window": _daily_period_bounds(range_name)[2],\n        "interval": "1d",\n        "symbols": {\n            "swing": normalized_swing,\n            "income": normalized_income,\n            "vix": normalized_vix,\n        },\n        "rows": {\n            "swing": len(swing_rows),\n            "income": len(income_rows),\n            "vix": len(vix_rows),\n            "dividend_events": len(dividend_rows),\n        },\n        "common_first_date": common_first.isoformat(),\n        "common_last_date": common_last.isoformat(),\n        "files": {\n            name: {\n                "path": str(path),\n                "sha256": sha256_file(path),\n            }\n            for name, path in output_paths.items()\n            if name != "manifest"\n        },\n        "notice": (\n            "Third-party market data can be revised or unavailable. "\n            "Preserve this manifest with every research result."\n        ),\n    }\n    output_paths["manifest"].write_text(\n        json.dumps(manifest, indent=2),\n        encoding="utf-8",\n    )\n\n    return DownloadSummary(\n        provider=manifest["provider"],\n        swing_symbol=normalized_swing,\n        income_symbol=normalized_income,\n        vix_symbol=normalized_vix,\n        swing_rows=len(swing_rows),\n        income_rows=len(income_rows),\n        vix_rows=len(vix_rows),\n        dividend_events=len(dividend_rows),\n        common_first_date=common_first,\n        common_last_date=common_last,\n        input_directory=directory,\n        manifest_path=output_paths["manifest"],\n    )\n',
    "QPX_FETCH_AND_RUN_REAL_DATA.py": '#!/usr/bin/env python3\n"""Download real market data and run the QPX hybrid backtest."""\n\nfrom __future__ import annotations\n\nimport argparse\nfrom datetime import datetime\nfrom pathlib import Path\nfrom typing import Sequence\n\nfrom qpx_bot.report import format_hybrid_report\nfrom qpx_bot.run_real_backtest import (\n    DEFAULT_INPUT_DIR,\n    DEFAULT_OUTPUT_DIR,\n    run_real_data_backtest,\n)\nfrom qpx_bot.yahoo_data import download_real_dataset\n\n\nPROJECT_ROOT = Path(__file__).resolve().parent\n\n\ndef _parser() -> argparse.ArgumentParser:\n    parser = argparse.ArgumentParser(\n        description=(\n            "Download real daily market data and run the QPX "\n            "hybrid dividend-plus-swing backtest."\n        )\n    )\n    parser.add_argument(\n        "--symbol",\n        default="SPY",\n        help="Swing ticker to download. Default: SPY.",\n    )\n    parser.add_argument(\n        "--input-dir",\n        default=str(DEFAULT_INPUT_DIR),\n        help="Destination for the four real-data CSV files.",\n    )\n    parser.add_argument(\n        "--output-dir",\n        default=str(DEFAULT_OUTPUT_DIR),\n        help="Destination for validation and backtest reports.",\n    )\n    parser.add_argument(\n        "--range",\n        dest="range_name",\n        default="max",\n        help=("Daily window: max/default maps to five years; ""or use 3y through 8y."),\n    )\n    parser.add_argument(\n        "--download-only",\n        action="store_true",\n        help="Download and validate files later without backtesting now.",\n    )\n    return parser\n\n\ndef main(argv: Sequence[str] | None = None) -> int:\n    args = _parser().parse_args(argv)\n    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")\n    backup_directory = (\n        PROJECT_ROOT\n        / "backups"\n        / "qpx_market_data"\n        / timestamp\n    )\n\n    print("=" * 76)\n    print("QPX BOT v1.7 — MARKET DATA ACQUISITION + REAL BACKTEST")\n    print("=" * 76)\n    print(f"Swing symbol : {args.symbol.strip().upper()}")\n    print(f"Input folder : {Path(args.input_dir).resolve()}")\n    print(f"Output folder: {Path(args.output_dir).resolve()}")\n    print()\n\n    summary = download_real_dataset(\n        swing_symbol=args.symbol,\n        input_directory=args.input_dir,\n        range_name=args.range_name,\n        backup_directory=backup_directory,\n    )\n\n    print()\n    print("Download complete")\n    print(f"Provider       : {summary.provider}")\n    print(f"Swing rows     : {summary.swing_rows}")\n    print(f"QDTE rows      : {summary.income_rows}")\n    print(f"VIX rows       : {summary.vix_rows}")\n    print(f"Dividend events: {summary.dividend_events}")\n    print(\n        f"Common period  : {summary.common_first_date} "\n        f"to {summary.common_last_date}"\n    )\n    print(f"Manifest       : {summary.manifest_path}")\n\n    if args.download_only:\n        print()\n        print("QPX REAL MARKET DATA DOWNLOAD: COMPLETE")\n        return 0\n\n    result, validation, artifacts = run_real_data_backtest(\n        input_directory=args.input_dir,\n        output_directory=args.output_dir,\n        swing_symbol=args.symbol,\n    )\n\n    print()\n    print(validation.format_text())\n    print()\n    print(format_hybrid_report(result))\n    print()\n    print("Research artifacts:")\n    for name, path in artifacts.items():\n        print(f"  {name:<10} {path}")\n\n    print()\n    print("=" * 76)\n    print("QPX FIRST REAL HYBRID BACKTEST: COMPLETE")\n    print("=" * 76)\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n',
    "tests/test_qpx_bot_yahoo_data.py": 'from datetime import datetime, timedelta, timezone\nimport json\nfrom pathlib import Path\nfrom tempfile import TemporaryDirectory\n\nfrom qpx_bot.dividends import load_dividend_csv\nfrom qpx_bot.real_data import load_market_csv, load_vix_csv\nfrom qpx_bot.yahoo_data import (\n    YahooDataError,\n    download_real_dataset,\n    extract_market_rows,\n)\n\n\ndef make_result(\n    *,\n    symbol: str,\n    base_price: float,\n    volume: int,\n    with_dividends: bool,\n):\n    start = datetime(2024, 1, 2, 12, tzinfo=timezone.utc)\n    timestamps = []\n    opens = []\n    highs = []\n    lows = []\n    closes = []\n    volumes = []\n\n    for index in range(260):\n        moment = start + timedelta(days=index)\n        price = base_price + (index * 0.03)\n        timestamps.append(int(moment.timestamp()))\n        opens.append(price)\n        highs.append(price + 1.0)\n        lows.append(price - 1.0)\n        closes.append(price + 0.25)\n        volumes.append(volume)\n\n    events = {}\n\n    if with_dividends:\n        dividend_events = {}\n        for index, amount in (\n            (20, 0.20),\n            (70, 0.22),\n            (140, 0.19),\n            (220, 0.24),\n        ):\n            timestamp = timestamps[index]\n            dividend_events[str(timestamp)] = {\n                "amount": amount,\n                "date": timestamp,\n            }\n        events["dividends"] = dividend_events\n\n    return {\n        "meta": {\n            "symbol": symbol,\n            "dataGranularity": "1d",\n        },\n        "timestamp": timestamps,\n        "indicators": {\n            "quote": [\n                {\n                    "open": opens,\n                    "high": highs,\n                    "low": lows,\n                    "close": closes,\n                    "volume": volumes,\n                }\n            ]\n        },\n        "events": events,\n    }\n\n\nresponses = {\n    "SPY": make_result(\n        symbol="SPY",\n        base_price=450.0,\n        volume=70_000_000,\n        with_dividends=False,\n    ),\n    "QDTE": make_result(\n        symbol="QDTE",\n        base_price=40.0,\n        volume=1_500_000,\n        with_dividends=True,\n    ),\n    "^VIX": make_result(\n        symbol="^VIX",\n        base_price=18.0,\n        volume=0,\n        with_dividends=False,\n    ),\n}\n\n\ndef fake_fetcher(symbol: str):\n    return responses[symbol]\n\n\nwith TemporaryDirectory() as temporary_directory:\n    input_directory = Path(temporary_directory) / "inputs"\n\n    summary = download_real_dataset(\n        swing_symbol="SPY",\n        input_directory=input_directory,\n        fetcher=fake_fetcher,\n    )\n\n    assert summary.swing_symbol == "SPY"\n    assert summary.income_symbol == "QDTE"\n    assert summary.swing_rows == 260\n    assert summary.income_rows == 260\n    assert summary.vix_rows == 260\n    assert summary.dividend_events == 4\n    assert summary.common_first_date <= summary.common_last_date\n\n    swing = load_market_csv(input_directory / "SWING.csv")\n    income = load_market_csv(input_directory / "QDTE.csv")\n    vix = load_vix_csv(input_directory / "VIX.csv")\n    dividends = load_dividend_csv(\n        input_directory / "QDTE_DIVIDENDS.csv"\n    )\n\n    assert len(swing) == 260\n    assert len(income) == 260\n    assert len(vix) == 260\n    assert len(dividends) == 4\n    assert dividends[0].amount_per_share == 0.20\n\n    manifest = json.loads(\n        (\n            input_directory / "DOWNLOAD_MANIFEST.json"\n        ).read_text(encoding="utf-8")\n    )\n    assert manifest["symbols"]["swing"] == "SPY"\n    assert manifest["rows"]["dividend_events"] == 4\n    assert len(manifest["files"]["swing"]["sha256"]) == 64\n\n\nmonthly_result = make_result(\n    symbol="MONTHLY",\n    base_price=100.0,\n    volume=1_000_000,\n    with_dividends=False,\n)\nmonthly_result["meta"]["dataGranularity"] = "1mo"\n\ntry:\n    extract_market_rows(monthly_result)\nexcept YahooDataError as exc:\n    assert "instead of required 1d bars" in str(exc)\nelse:\n    raise AssertionError("Downsampled market data was not rejected.")\n\nprint("QPX Bot Market Data Acquisition PASS")\n',
    "qpx_bot/data_inputs/README.txt": 'QPX BOT REAL-DATA INPUT FOLDER\n================================\n\nAUTOMATIC WORKFLOW\n\nFrom the QPX_ALPHA project root, run:\n\npython QPX_FETCH_AND_RUN_REAL_DATA.py --symbol SPY\n\nThe command requests an explicit five-year daily window so the\nprovider cannot silently substitute weekly or monthly bars.\n\nThe command downloads:\n\nSWING.csv\n    Daily history for the selected swing symbol.\n\nQDTE.csv\n    Daily QDTE OHLCV history.\n\nQDTE_DIVIDENDS.csv\n    QDTE cash-distribution events.\n\nVIX.csv\n    Daily CBOE Volatility Index closing values.\n\nDOWNLOAD_MANIFEST.json\n    Provider, symbols, row counts, date range, and SHA-256 hashes.\n\nIt then validates the overlapping history and runs the real hybrid\ndividend-plus-swing backtest. Reports are written to:\n\nreports/qpx_real_backtest/\n\nMANUAL FALLBACK\n\nThe runner also accepts manually exported daily CSV files. Required\nnames and columns are:\n\nSWING.csv\nQDTE.csv\n    Date/time, Open, High, Low, Close, Volume\n\nQDTE_DIVIDENDS.csv\n    Date, Dividend\n\nVIX.csv\n    Date,VIX\n    or daily OHLCV with a Close column\n\nImportant:\n- Use daily bars, not intraday bars.\n- Provider data is third-party research data and can be revised.\n- Raw downloads and generated reports are intentionally not committed.\n- Preserve each DOWNLOAD_MANIFEST.json with its research results.\n- This is research simulation software, not live trading or advice.\n',
}

originals: dict[str, bytes | None] = {}


def run(command: list[str]) -> None:
    print("$ " + " ".join(command))
    subprocess.run(command, cwd=ROOT, check=True)


def ensure_targets_are_safe() -> None:
    changed: list[str] = []

    for relative in FILES:
        worktree = subprocess.run(
            ["git", "diff", "--quiet", "--", relative],
            cwd=ROOT,
        )
        staged = subprocess.run(
            ["git", "diff", "--cached", "--quiet", "--", relative],
            cwd=ROOT,
        )

        if worktree.returncode != 0 or staged.returncode != 0:
            changed.append(relative)

    if changed:
        raise RuntimeError(
            "These target files have uncommitted edits and were "
            "not overwritten:\n" + "\n".join(changed)
        )


def install() -> None:
    for relative, content in FILES.items():
        path = ROOT / relative
        originals[relative] = (
            path.read_bytes()
            if path.exists()
            else None
        )

        if path.exists():
            backup_path = BACKUP / relative
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup_path)

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            textwrap.dedent(content).strip() + "\n",
            encoding="utf-8",
        )
        print(f"Installed: {relative}")


def restore_code() -> None:
    print("Restoring previous target files...")

    for relative, original in originals.items():
        path = ROOT / relative

        if original is None:
            if path.exists():
                path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(original)


def commit_and_push() -> None:
    paths = list(FILES)

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
        print("Daily-data fix is already committed.")
        return

    run([
        "git",
        "commit",
        "-m",
        "Fix QPX Bot daily market data acquisition",
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
    print("=" * 76)
    print("QPX BOT — TRUE DAILY MARKET DATA FIX")
    print("=" * 76)
    print(f"Project: {ROOT}")

    ensure_targets_are_safe()
    install()

    try:
        run([sys.executable, "tests/run_all_tests.py"])
    except Exception:
        restore_code()
        raise

    commit_and_push()

    print()
    print("Daily-data fix passed all tests and was pushed.")
    print("Replacing the downsampled files and rerunning SPY...")
    print()

    try:
        run([
            sys.executable,
            "QPX_FETCH_AND_RUN_REAL_DATA.py",
            "--symbol",
            "SPY",
        ])
    except Exception:
        print()
        print("=" * 76)
        print("QPX TRUE DAILY DATA FIX: INSTALLED AND PUSHED")
        print("LIVE PROVIDER/BACKTEST: NEEDS RETRY")
        print("=" * 76)
        print(
            "Re-run:\n"
            "python QPX_FETCH_AND_RUN_REAL_DATA.py --symbol SPY"
        )
        return 2

    print()
    print("=" * 76)
    print("QPX TRUE DAILY DATA + REAL BACKTEST: COMPLETE")
    print("=" * 76)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
