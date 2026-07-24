#!/usr/bin/env python3
"""
=============================================================
QPX_ARCHITECTURE_ANALYZER.py
QPX Alpha Step 15.2

Reads:
    QPX_CONTEXT/scanner.json

Creates:
    QPX_CONTEXT/architecture.json

Purpose
-------
Infer the high-level architecture of the project from the
inventory produced by QPX_CONTEXT_SCANNER.py.
=============================================================
"""

import json
import os
import datetime
from collections import Counter

ROOT = "/storage/emulated/0/QPX_ALPHA"

SCAN = os.path.join(
    ROOT,
    "QPX_CONTEXT",
    "scanner.json"
)

OUTPUT = os.path.join(
    ROOT,
    "QPX_CONTEXT",
    "architecture.json"
)


def load():

    with open(SCAN, "r", encoding="utf-8") as f:
        return json.load(f)


def main():

    scan = load()

    arch = {

        "generated":
            datetime.datetime.now().isoformat(),

        "project":

            "QPX Alpha",

        "statistics":
            scan["statistics"],

        "entry_points": [],

        "engines": [],

        "managers": [],

        "pipelines": [],

        "validators": [],

        "repair_modules": [],

        "libraries": [],

        "executables": [],

        "imports": Counter(),

        "duplicate_modules":
            scan["duplicates"],

        "core_modules": {},

        "observations": []

    }

    for module in scan["files"]:

        name = module["name"]

        module_type = module["type"]

        if module.get("entry_point"):
            arch["entry_points"].append(name)

        if module_type == "engine":
            arch["engines"].append(name)

        elif module_type == "manager":
            arch["managers"].append(name)

        elif module_type == "pipeline":
            arch["pipelines"].append(name)

        elif module_type == "validator":
            arch["validators"].append(name)

        elif module_type == "repair":
            arch["repair_modules"].append(name)

        if module["extension"] == ".py":
            arch["libraries"].append(name)

        if module.get("entry_point"):
            arch["executables"].append(name)

        for imp in module.get("imports", []):
            arch["imports"][imp] += 1

    wanted = [

        "database.py",

        "feature_engine.py",

        "signal_engine.py",

        "backtesting_engine.py",

        "paper_trading_engine.py",

        "position_manager.py",

        "risk_controller.py",

        "QPX_MASTER_RUNNER.py",

        "QPX_START.py"

    ]

    names = {
        f["name"]: f
        for f in scan["files"]
    }

    for item in wanted:

        if item in names:
            arch["core_modules"][item] = names[item]["path"]

    if len(scan["duplicates"]) > 20:

        arch["observations"].append(

            "Large number of duplicate filenames detected. "
            "Project would benefit from consolidation."

        )

    if scan["statistics"]["backups"] > 10:

        arch["observations"].append(

            "Large number of backup files detected."

        )

    if len(arch["repair_modules"]) > 10:

        arch["observations"].append(

            "Many repair utilities exist. "
            "Consider replacing with reusable repair framework."

        )

    arch["imports"] = dict(

        sorted(

            arch["imports"].items(),

            key=lambda x: x[1],

            reverse=True

        )

    )

    with open(

        OUTPUT,

        "w",

        encoding="utf-8"

    ) as f:

        json.dump(

            arch,

            f,

            indent=4

        )

    print("=" * 60)
    print("QPX ARCHITECTURE ANALYZER")
    print("=" * 60)
    print("Entry Points :", len(arch["entry_points"]))
    print("Engines      :", len(arch["engines"]))
    print("Managers     :", len(arch["managers"]))
    print("Pipelines    :", len(arch["pipelines"]))
    print("Validators   :", len(arch["validators"]))
    print("Repairs      :", len(arch["repair_modules"]))
    print("Imports      :", len(arch["imports"]))
    print()
    print("Output")
    print(OUTPUT)
    print("STATUS: COMPLETE")


if __name__ == "__main__":
    main()