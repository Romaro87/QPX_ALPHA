#!/usr/bin/env python3

import os
import json
import time
import datetime
import urllib.request
import urllib.parse
import urllib.error

ROOT = "/storage/emulated/0/QPX_ALPHA"

CONFIG = os.path.join(ROOT, "qpx_provider.json")
OUTPUT = os.path.join(ROOT, "historical_data.csv")

SYMBOL = "SPY"


def log(text):
    print(datetime.datetime.now().isoformat(), text)


def load_provider():

    if not os.path.exists(CONFIG):
        raise FileNotFoundError(CONFIG)

    with open(CONFIG, "r", encoding="utf-8") as f:
        return json.load(f)


def download_alpha_vantage(cfg):

    api_key = cfg.get("api_key", "").strip()

    if not api_key:
        raise RuntimeError("No Alpha Vantage API key configured.")

    params = urllib.parse.urlencode({
        "function": "TIME_SERIES_DAILY_ADJUSTED",
        "symbol": SYMBOL,
        "outputsize": "full",
        "datatype": "csv",
        "apikey": api_key
    })

    url = "https://www.alphavantage.co/query?" + params

    log("Provider: Alpha Vantage")
    log("Downloading " + SYMBOL)

    urllib.request.urlretrieve(url, OUTPUT)

    return True


def download_yahoo():

    url = (
        "https://query1.finance.yahoo.com/v7/finance/download/"
        + SYMBOL
        + "?period1=1704067200"
        + "&period2=1782864000"
        + "&interval=1d"
        + "&events=history"
    )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0"
        }
    )

    with urllib.request.urlopen(request) as response:
        data = response.read()

    with open(OUTPUT, "wb") as f:
        f.write(data)

    return True


def download():

    cfg = load_provider()

    provider = cfg.get("provider", "").lower()

    for attempt in range(1, 4):

        try:

            log(f"Attempt {attempt}")

            if provider == "alpha_vantage":
                return download_alpha_vantage(cfg)

            elif provider == "yahoo":
                return download_yahoo()

            else:
                raise RuntimeError(
                    "Unsupported provider: " + provider
                )

        except urllib.error.HTTPError as e:

            log(f"HTTP {e.code}")

            if e.code == 401:
                log("Authentication failed.")

            elif e.code == 429:
                log("Rate limit reached.")

            time.sleep(attempt * 5)

        except Exception as e:

            log(str(e))
            time.sleep(attempt * 5)

    return False


def main():

    log("QPX HISTORICAL DOWNLOADER V3 START")

    if download():

        log("CSV CREATED")
        log(OUTPUT)
        log("STATUS: COMPLETE")

    else:

        log("STATUS: FAILED")


if __name__ == "__main__":
    main()