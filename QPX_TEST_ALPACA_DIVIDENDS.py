from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path


KEY_FILE = (
    Path.home()
    / ".config"
    / "qpx"
    / "alpaca.json"
)

URL = (
    "https://data.alpaca.markets"
    "/v1/corporate-actions"
)

TARGET_START = date(2024, 8, 8)
TARGET_END = date(2026, 8, 7)


credentials = json.loads(
    KEY_FILE.read_text(
        encoding="utf-8"
    )
)

headers = {
    "APCA-API-KEY-ID":
        credentials["key_id"],
    "APCA-API-SECRET-KEY":
        credentials["secret_key"],
    "Accept":
        "application/json",
    "Accept-Encoding":
        "identity",
}


def find_dividends(
    value,
    output,
):
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
            find_dividends(
                child,
                output,
            )

    elif isinstance(value, list):
        for child in value:
            find_dividends(
                child,
                output,
            )


params = {
    "symbols": "QDTE",
    "types": "cash_dividend",
    "region": "us",
    "start": "2024-07-01",
    "end": "2026-08-08",
    "limit": "1000",
    "data_quality": "complete",
    "sort": "asc",
}

all_records = []
page = 0

print("=" * 70)
print("QPX ALPACA QDTE DIVIDEND TEST")
print("=" * 70)

while True:
    page += 1

    url = (
        URL
        + "?"
        + urllib.parse.urlencode(
            params
        )
    )

    request = urllib.request.Request(
        url,
        headers=headers,
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=30,
        ) as response:
            payload = json.loads(
                response.read().decode(
                    "utf-8"
                )
            )

    except urllib.error.HTTPError as exc:
        body = exc.read().decode(
            "utf-8",
            errors="replace",
        )

        print(
            f"STATUS : HTTP {exc.code}"
        )
        print(
            f"DETAIL : {body[:800]}"
        )
        raise SystemExit(1)

    page_records = []

    find_dividends(
        payload,
        page_records,
    )

    all_records.extend(
        page_records
    )

    print(
        f"Page {page}: "
        f"{len(page_records)} "
        "dividend records"
    )

    token = payload.get(
        "next_page_token"
    )

    if not token:
        break

    params["page_token"] = str(
        token
    )


normalized = {}

for raw in all_records:
    raw_date = (
        raw.get("ex_date")
        or raw.get(
            "ex_dividend_date"
        )
    )

    raw_amount = (
        raw.get("rate")
        if raw.get("rate") is not None
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
        TARGET_START
        <= ex_date
        <= TARGET_END
    ):
        continue

    if amount <= 0:
        continue

    event_id = str(
        raw.get(
            "id",
            (
                f"QDTE|"
                f"{ex_date.isoformat()}|"
                f"{amount:.10f}"
            ),
        )
    )

    normalized[event_id] = (
        ex_date,
        amount,
    )


events = sorted(
    normalized.values(),
    key=lambda item: item[0],
)

print()
print("STATUS : SUCCESS")
print(
    f"EVENTS : {len(events)}"
)

if events:
    print(
        "FIRST  : "
        f"{events[0][0]} "
        f"${events[0][1]:.6f}"
    )

    print(
        "LAST   : "
        f"{events[-1][0]} "
        f"${events[-1][1]:.6f}"
    )

    print(
        "SUM/SHARE: "
        f"${sum(x[1] for x in events):.6f}"
    )

print("=" * 70)
print("TEST COMPLETE")
print("=" * 70)
