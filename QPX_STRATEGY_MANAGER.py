#!/usr/bin/env python3

"""
QPX Strategy Manager
Version 1.0

- Creates strategy_config.json if missing
- Backs up the configuration before changes
- Loads the active strategy
- Returns its parameters
"""

import os
import json
import shutil
import datetime

ROOT = "/storage/emulated/0/QPX_ALPHA"

CONFIG = os.path.join(ROOT, "strategy_config.json")

BACKUP_DIR = os.path.join(ROOT, "CONFIG_BACKUPS")


DEFAULT_CONFIG = {
    "version": 1,
    "active_strategy": "Swing Strategy V3",
    "strategies": {
        "Swing Strategy V3": {
            "enabled": True,
            "ema_fast": 20,
            "ema_slow": 50,
            "rsi_period": 14,
            "rsi_buy": 35,
            "rsi_sell": 65,
            "atr_period": 14,
            "atr_stop_multiplier": 2.0,
            "atr_target_multiplier": 3.0
        }
    }
}


def log(message):
    print(datetime.datetime.now().isoformat(), message)


def ensure_backup_dir():
    os.makedirs(BACKUP_DIR, exist_ok=True)


def create_default():
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, indent=4)


def backup_config():
    if not os.path.exists(CONFIG):
        return

    ensure_backup_dir()

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    backup_file = os.path.join(
        BACKUP_DIR,
        f"strategy_config_{timestamp}.json"
    )

    shutil.copy2(CONFIG, backup_file)

    log(f"Backup created: {backup_file}")


def load_config():
    if not os.path.exists(CONFIG):
        log("Configuration missing - creating default")
        create_default()

    with open(CONFIG, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg):
    backup_config()

    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4)


def get_active_strategy(cfg):

    name = cfg.get("active_strategy")

    strategies = cfg.get("strategies", {})

    if name not in strategies:
        raise ValueError(
            f"Strategy '{name}' not found."
        )

    return name, strategies[name]


def main():

    log("QPX STRATEGY MANAGER START")

    cfg = load_config()

    name, strategy = get_active_strategy(cfg)

    save_config(cfg)

    log(f"Active Strategy: {name}")

    for key, value in strategy.items():
        log(f"{key}: {value}")

    log("STATUS: READY")


if __name__ == "__main__":
    main()