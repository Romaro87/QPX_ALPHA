from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path


cred_path = (
    Path.home()
    / ".config"
    / "qpx"
    / "alpaca.json"
)

creds = json.loads(
    cred_path.read_text(
        encoding="utf-8"
    )
)

headers = {
    "APCA-API-KEY-ID":
        creds["key_id"],
    "APCA-API-SECRET-KEY":
        creds["secret_key"],
    "Accept":
        "application/json",
}

BASE = (
    "https://data.alpaca.markets"
    "/v2/stocks/bars"
)

params_base = {
    "symbols": "XLE,QDTE",
    "timeframe": "15Min",
    "start": "2026-08-03T00:00:00Z",
    "end": "2026-08-06T00:00:00Z",
    "limit": "1000",
    "sort": "asc",
}

print("=" * 68)
print("QPX ALPACA ENTITLEMENT TEST")
print("=" * 68)

for feed in ("sip", "iex"):
    params = dict(params_base)
    params["feed"] = feed

    url = (
        BASE
        + "?"
        + urllib.parse.urlencode(
            params
        )
    )

    request = urllib.request.Request(
        url,
        headers=headers,
    )

    print()
    print(
        f"Testing feed: "
        f"{feed.upper()}"
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

        bars = payload.get(
            "bars",
            {},
        )

        counts = {
            symbol: len(rows)
            for symbol, rows
            in bars.items()
            if isinstance(rows, list)
        }

        print("STATUS : SUCCESS")
        print(
            "COUNTS : "
            + ", ".join(
                f"{symbol}={count}"
                for symbol, count
                in counts.items()
            )
        )

        print(
            "NEXT   : "
            + str(
                bool(
                    payload.get(
                        "next_page_token"
                    )
                )
            )
        )

    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode(
                "utf-8",
                errors="replace",
            )
        except OSError:
            body = ""

        print(
            f"STATUS : HTTP "
            f"{exc.code}"
        )
        print(
            f"DETAIL : "
            f"{body[:500]}"
        )

    except Exception as exc:
        print(
            "STATUS : ERROR"
        )
        print(
            f"DETAIL : "
            f"{type(exc).__name__}: "
            f"{exc}"
        )

print()
print("=" * 68)
print("TEST COMPLETE")
print("=" * 68)
