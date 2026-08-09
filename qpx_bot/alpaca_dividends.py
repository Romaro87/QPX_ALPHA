from __future__ import annotations

import csv
import json
import urllib.error
import urllib.parse
import urllib.request

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from qpx_bot.alpaca_provider import credentials


PROJECT_ROOT = Path(__file__).resolve().parent.parent

ALPACA_ROOT = (
    PROJECT_ROOT
    / "research_data"
    / "qpx_alpaca_sip"
)

URL = (
    "https://data.alpaca.markets"
    "/v1/corporate-actions"
)


def dividend_path(symbol: str) -> Path:
    name = (
        symbol.strip().upper()
        .replace("^", "")
        .replace(":", "_")
        .replace("/", "_")
    )

    return (
        ALPACA_ROOT
        / "shared"
        / f"{name}_DIVIDENDS.csv"
    )


def manifest_path(symbol: str) -> Path:
    path = dividend_path(symbol)

    return path.with_suffix(
        path.suffix + ".manifest.json"
    )


def _request(
    params: dict[str, str],
) -> dict[str, Any]:
    key, secret = credentials()

    url = (
        URL
        + "?"
        + urllib.parse.urlencode(params)
    )

    request = urllib.request.Request(
        url,
        headers={
            "APCA-API-KEY-ID": key,
            "APCA-API-SECRET-KEY": secret,
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "User-Agent": "QPX-ALPHA",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=45,
        ) as response:
            payload = json.loads(
                response.read().decode("utf-8")
            )

    except urllib.error.HTTPError as exc:
        body = exc.read().decode(
            "utf-8",
            errors="replace",
        )

        raise RuntimeError(
            f"Alpaca corporate-actions HTTP "
            f"{exc.code}: {body[:500]}"
        ) from exc

    if not isinstance(payload, dict):
        raise RuntimeError(
            "Malformed Alpaca corporate-actions response."
        )

    return payload


def _find_records(
    value: Any,
    output: list[dict[str, Any]],
) -> None:
    if isinstance(value, dict):
        has_date = (
            "ex_date" in value
            or "ex_dividend_date" in value
        )

        has_amount = (
            "rate" in value
            or "cash_amount" in value
            or "cash" in value
        )

        if has_date and has_amount:
            output.append(value)

        for child in value.values():
            _find_records(
                child,
                output,
            )

    elif isinstance(value, list):
        for child in value:
            _find_records(
                child,
                output,
            )


def _read_existing(
    symbol: str,
) -> dict[str, tuple[date, float]]:
    path = dividend_path(symbol)

    if not path.exists():
        return {}

    result: dict[
        str,
        tuple[date, float],
    ] = {}

    with path.open(
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        reader = csv.DictReader(file)

        for row in reader:
            try:
                event_id = str(
                    row["EventId"]
                ).strip()

                ex_date = date.fromisoformat(
                    row["ExDividendDate"]
                )

                amount = float(
                    row["CashAmount"]
                )
            except (
                KeyError,
                TypeError,
                ValueError,
            ):
                continue

            if event_id and amount > 0:
                result[event_id] = (
                    ex_date,
                    amount,
                )

    return result


def sync_dividends(
    *,
    symbol: str,
    start: date,
    end: date,
) -> Path:
    symbol = symbol.strip().upper()

    if not symbol:
        raise ValueError(
            "Dividend symbol cannot be empty."
        )

    if end < start:
        raise ValueError(
            "Dividend end date precedes start date."
        )

    path = dividend_path(symbol)
    manifest = manifest_path(symbol)

    existing = _read_existing(symbol)

    cached_start = None
    cached_end = None

    if manifest.exists():
        try:
            payload = json.loads(
                manifest.read_text(
                    encoding="utf-8"
                )
            )

            cached_start = date.fromisoformat(
                str(
                    payload[
                        "coverage_start"
                    ]
                )
            )

            cached_end = date.fromisoformat(
                str(
                    payload[
                        "coverage_end"
                    ]
                )
            )

        except (
            OSError,
            KeyError,
            TypeError,
            ValueError,
        ):
            cached_start = None
            cached_end = None

    if (
        cached_start is not None
        and cached_end is not None
        and cached_start <= start
        and cached_end >= end
        and existing
    ):
        print(
            f"{symbol} dividends CACHE HIT "
            f"{cached_start} -> {cached_end}"
        )

        return path

    request_start = min(
        start,
        cached_start
        if cached_start is not None
        else start,
    )

    request_end = max(
        end,
        cached_end
        if cached_end is not None
        else end,
    )

    params = {
        "symbols": symbol,
        "types": "cash_dividend",
        "region": "us",
        "start": (
            request_start
            - timedelta(days=120)
        ).isoformat(),
        "end": (
            request_end
            + timedelta(days=30)
        ).isoformat(),
        "limit": "1000",
        "data_quality": "complete",
        "sort": "asc",
    }

    page = 0

    while True:
        page += 1

        payload = _request(params)

        records: list[
            dict[str, Any]
        ] = []

        _find_records(
            payload,
            records,
        )

        print(
            f"{symbol} dividend page "
            f"{page}: {len(records)} records"
        )

        for raw in records:
            raw_date = (
                raw.get("ex_date")
                or raw.get(
                    "ex_dividend_date"
                )
            )

            raw_amount = (
                raw.get("rate")
                if raw.get("rate")
                is not None
                else raw.get(
                    "cash_amount",
                    raw.get("cash"),
                )
            )

            try:
                ex_date = date.fromisoformat(
                    str(raw_date)[:10]
                )

                amount = float(
                    raw_amount
                )
            except (
                TypeError,
                ValueError,
            ):
                continue

            if not (
                request_start
                <= ex_date
                <= request_end
            ):
                continue

            if amount <= 0:
                continue

            event_id = str(
                raw.get(
                    "id",
                    (
                        f"{symbol}|"
                        f"{ex_date.isoformat()}|"
                        f"{amount:.10f}"
                    ),
                )
            )

            existing[event_id] = (
                ex_date,
                amount,
            )

        token = payload.get(
            "next_page_token"
        )

        if not token:
            break

        params["page_token"] = str(
            token
        )

    filtered = {
        event_id: item
        for event_id, item
        in existing.items()
        if (
            request_start
            <= item[0]
            <= request_end
        )
    }

    if not filtered:
        raise RuntimeError(
            f"No dividend events found for {symbol}."
        )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)

        writer.writerow(
            (
                "EventId",
                "ExDividendDate",
                "CashAmount",
            )
        )

        for event_id, (
            ex_date,
            amount,
        ) in sorted(
            filtered.items(),
            key=lambda item: (
                item[1][0],
                item[0],
            ),
        ):
            writer.writerow(
                (
                    event_id,
                    ex_date.isoformat(),
                    f"{amount:.10f}",
                )
            )

    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provider": "alpaca",
                "source": "corporate_actions",
                "symbol": symbol,
                "coverage_start":
                    request_start.isoformat(),
                "coverage_end":
                    request_end.isoformat(),
                "event_count":
                    len(filtered),
                "synthetic_data": False,
                "placeholder_data": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        f"{symbol} dividends cached: "
        f"{len(filtered)} events"
    )

    return path
