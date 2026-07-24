#!/usr/bin/env python3

"""
QPX Provider Manager

Chooses the configured data provider.
Falls back safely if no provider is configured.
"""

import os
import json
import datetime

ROOT = "/storage/emulated/0/QPX_ALPHA"

CONFIG_FILE = os.path.join(ROOT, "qpx_provider.json")


DEFAULT_CONFIG = {
    "provider": "placeholder",
    "api_key": "",
    "symbol": "SPY",
    "interval": "1day"
}


def log(msg):
    print(datetime.datetime.now().isoformat(), msg)


def load_config():

    if not os.path.exists(CONFIG_FILE):

        with open(CONFIG_FILE, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)

        return DEFAULT_CONFIG

    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def main():

    log("QPX PROVIDER MANAGER START")

    cfg = load_config()

    provider = cfg.get("provider", "placeholder")

    log("Configured Provider: {}".format(provider))

    if provider == "placeholder":

        log("No live provider configured.")
        log("Using CSV import workflow.")
        return

    if not cfg.get("api_key"):

        log("API key missing.")
        log("Provider disabled.")
        return

    log("Provider configuration looks valid.")
    log("Ready for download requests.")

    log("STATUS: READY")


if __name__ == "__main__":
    main()