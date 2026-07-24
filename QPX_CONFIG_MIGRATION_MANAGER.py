#!/usr/bin/env python3

"""
QPX Configuration Migration Manager

Automatically upgrades older strategy_config.json
files to the newest format.

Future versions simply add new migration functions.
"""

import os
import json
import shutil
import datetime

ROOT = "/storage/emulated/0/QPX_ALPHA"

CONFIG = os.path.join(
    ROOT,
    "strategy_config.json"
)

BACKUP_DIR = os.path.join(
    ROOT,
    "CONFIG_BACKUPS"
)

LATEST_VERSION = 2


def log(text):
    print(datetime.datetime.now().isoformat(), text)


def backup():

    os.makedirs(BACKUP_DIR, exist_ok=True)

    if not os.path.exists(CONFIG):
        return

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    shutil.copy2(
        CONFIG,
        os.path.join(
            BACKUP_DIR,
            f"strategy_config_{ts}.json"
        )
    )


def migrate_v0_to_v2(cfg):

    return {

        "version": 2,

        "active_strategy": cfg.get(
            "strategy_name",
            "Swing Strategy V3"
        ),

        "strategies": {

            cfg.get(
                "strategy_name",
                "Swing Strategy V3"
            ): {

                "enabled": True,

                "ema_fast": cfg.get(
                    "ema_fast",
                    20
                ),

                "ema_slow": cfg.get(
                    "ema_slow",
                    50
                ),

                "rsi_period": cfg.get(
                    "rsi_period",
                    14
                ),

                "rsi_buy": cfg.get(
                    "rsi_buy",
                    35
                ),

                "rsi_sell": cfg.get(
                    "rsi_sell",
                    65
                ),

                "atr_period": cfg.get(
                    "atr_period",
                    14
                ),

                "atr_stop_multiplier": cfg.get(
                    "atr_stop_multiplier",
                    2.0
                ),

                "atr_target_multiplier": cfg.get(
                    "atr_target_multiplier",
                    3.0
                )

            }

        }

    }


def migrate(cfg):

    version = cfg.get(
        "version",
        0
    )

    if version == 0:

        log(
            "Migrating Version 0 -> 2"
        )

        cfg = migrate_v0_to_v2(cfg)

    return cfg


def main():

    log(
        "QPX CONFIG MIGRATION START"
    )

    if not os.path.exists(CONFIG):

        log(
            "Configuration not found"
        )

        return

    backup()

    with open(
        CONFIG,
        "r",
        encoding="utf-8"
    ) as f:

        cfg = json.load(f)

    cfg = migrate(cfg)

    with open(
        CONFIG,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            cfg,
            f,
            indent=4
        )

    log(
        "Configuration upgraded"
    )

    log(
        "Current Version: "
        + str(cfg["version"])
    )

    log(
        "STATUS: READY"
    )


if __name__ == "__main__":

    main()