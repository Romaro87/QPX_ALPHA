#!/usr/bin/env python3
"""
============================================================
QPX HISTORY ANALYZER
QPX Alpha Step 15.3

Reads

    QPX_CONTEXT/scanner.json
    QPX_CONTEXT/architecture.json

Scans every report produced by QPX Alpha

Produces

    QPX_CONTEXT/history.json

============================================================
"""

import os
import re
import json
import datetime

ROOT = "/storage/emulated/0/QPX_ALPHA"

CONTEXT = os.path.join(ROOT, "QPX_CONTEXT")

SCANNER = os.path.join(CONTEXT, "scanner.json")

ARCH = os.path.join(CONTEXT, "architecture.json")

OUTPUT = os.path.join(CONTEXT, "history.json")


STATUS_RE = re.compile(
    r"STATUS\s*:\s*(PASS|FAIL|READY|SUCCESS|COMPLETE|FAILED)",
    re.IGNORECASE
)

STEP_RE = re.compile(
    r"STEP\s*([0-9]+)",
    re.IGNORECASE
)


def load(path):

    with open(path, "r", encoding="utf-8") as f:

        return json.load(f)


def read_text(path):

    try:

        with open(path, "r", encoding="utf-8", errors="ignore") as f:

            return f.read()

    except Exception:

        return ""


def discover_reports():

    reports = []

    for root, dirs, files in os.walk(ROOT):

        if "QPX_CONTEXT" in root:

            continue

        for file in files:

            if file.lower().endswith(".txt"):

                reports.append(
                    os.path.join(root, file)
                )

            elif file.lower().endswith(".json"):

                reports.append(
                    os.path.join(root, file)
                )

    return reports


def detect_status(text):

    m = STATUS_RE.search(text)

    if m:

        return m.group(1).upper()

    return "UNKNOWN"


def detect_step(name):

    m = STEP_RE.search(name)

    if m:

        return int(m.group(1))

    return None


def build_history():

    scanner = load(SCANNER)

    arch = load(ARCH)

    history = {

        "generated":
            datetime.datetime.now().isoformat(),

        "reports": [],

        "timeline": [],

        "completed_steps": [],

        "failed_reports": [],

        "project_health": {},

        "statistics": scanner["statistics"],

        "architecture_summary": {

            "entry_points":
                len(arch["entry_points"]),

            "engines":
                len(arch["engines"]),

            "pipelines":
                len(arch["pipelines"]),

            "repair_modules":
                len(arch["repair_modules"])

        }

    }

    completed = set()

    failures = 0

    total = 0

    for report in discover_reports():

        text = read_text(report)

        status = detect_status(text)

        step = detect_step(
            os.path.basename(report)
        )

        total += 1

        if status in ("FAIL", "FAILED"):

            failures += 1

            history["failed_reports"].append(

                os.path.basename(report)

            )

        if step:

            completed.add(step)

        history["reports"].append({

            "file":
                os.path.relpath(report, ROOT),

            "status":
                status,

            "step":
                step

        })

    history["completed_steps"] = sorted(

        list(completed)

    )

    for step in history["completed_steps"]:

        history["timeline"].append({

            "step": step,

            "status": "Observed"

        })

    health = "Excellent"

    if failures > 20:

        health = "Needs Attention"

    elif failures > 5:

        health = "Good"

    history["project_health"] = {

        "overall": health,

        "reports_scanned": total,

        "failed_reports": failures,

        "duplicate_modules":

            len(scanner["duplicates"]),

        "backups":

            scanner["statistics"]["backups"]

    }

    return history


def main():

    history = build_history()

    with open(

        OUTPUT,

        "w",

        encoding="utf-8"

    ) as f:

        json.dump(

            history,

            f,

            indent=4

        )

    print("=" * 60)

    print("QPX HISTORY ANALYZER")

    print("=" * 60)

    print("Reports")

    print(len(history["reports"]))

    print()

    print("Completed Steps")

    print(history["completed_steps"])

    print()

    print("Overall Health")

    print(history["project_health"]["overall"])

    print()

    print("Output")

    print(OUTPUT)

    print("STATUS: COMPLETE")


if __name__ == "__main__":

    main()