#!/usr/bin/env python3

"""
QPX Health Check

Checks:
- Required modules exist
- Modules can be imported
- Whether they expose run() or main()

Creates:
QPX_HEALTH_REPORT.txt
"""

import os
import importlib.util
import datetime

ROOT = "/storage/emulated/0/QPX_ALPHA"

REPORT = os.path.join(ROOT, "QPX_HEALTH_REPORT.txt")

MODULES = [
    "QPX_CONFIG_MIGRATION_MANAGER.py",
    "QPX_STRATEGY_CONFIG_MANAGER.py",
    "QPX_PROVIDER_MANAGER.py",
    "feature_engine.py",
    "swing_strategy_v3.py",
]


def inspect_module(filename):
    path = os.path.join(ROOT, filename)

    if not os.path.exists(path):
        return ("missing", "File not found")

    try:
        spec = importlib.util.spec_from_file_location(
            filename[:-3], path
        )

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        has_run = hasattr(module, "run")
        has_main = hasattr(module, "main")

        if has_run:
            return ("compatible", "run() found")

        if has_main:
            return ("adapter_needed", "main() found")

        return ("manual_review", "No run() or main()")

    except Exception as e:
        return ("import_error", str(e))


def main():

    now = datetime.datetime.now().isoformat()

    lines = [
        "=" * 40,
        "QPX HEALTH CHECK",
        now,
        "=" * 40,
        ""
    ]

    summary = {
        "compatible": 0,
        "adapter_needed": 0,
        "manual_review": 0,
        "missing": 0,
        "import_error": 0,
    }

    for module in MODULES:

        status, detail = inspect_module(module)

        summary[status] += 1

        lines.append(f"{module}")
        lines.append(f"  Status : {status}")
        lines.append(f"  Detail : {detail}")
        lines.append("")

        print(f"{module}: {status}")

    lines.append("=" * 40)
    lines.append("SUMMARY")
    lines.append("=" * 40)

    for key, value in summary.items():
        lines.append(f"{key}: {value}")

    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print()
    print("Health report written:")
    print(REPORT)


if __name__ == "__main__":
    main()