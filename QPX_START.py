#!/usr/bin/env python3

"""
QPX START
Main application entry point
"""

import datetime
import importlib
import json
import os
import traceback

ROOT = "/storage/emulated/0/QPX_ALPHA"

MANIFEST = os.path.join(ROOT, "qpx_manifest.json")

PIPELINE = [
    ("Config Migration", "QPX_CONFIG_MIGRATION_MANAGER"),
    ("Strategy Config", "QPX_STRATEGY_CONFIG_MANAGER"),
    ("Provider Manager", "QPX_PROVIDER_MANAGER"),
    ("Feature Engine", "feature_engine"),
    ("Strategy", "swing_strategy_v3"),
]


def load_manifest():
    if os.path.exists(MANIFEST):
        with open(MANIFEST, "r") as f:
            return json.load(f)

    return {
        "qpx_version": "2.0.0",
        "last_run_status": "never",
        "last_start": None,
        "last_end": None,
        "results": []
    }


def save_manifest(manifest):
    with open(MANIFEST, "w") as f:
        json.dump(manifest, f, indent=4)


def run_module(module_name):

    try:

        module = importlib.import_module(module_name)

        if hasattr(module, "run"):

            result = module.run()

            if isinstance(result, dict):
                return result

        return {
            "status": "success",
            "message": "Completed"
        }

    except Exception as e:

        return {

            "status": "failed",

            "message": str(e),

            "traceback": traceback.format_exc()

        }


def main():

    manifest = load_manifest()

    manifest["last_start"] = datetime.datetime.now().isoformat()

    manifest["results"] = []

    print("QPX START")

    for name, module in PIPELINE:

        print("Running:", name)

        result = run_module(module)

        result["module"] = name

        manifest["results"].append(result)

        print(result["status"])

        if result["status"] != "success":

            manifest["last_run_status"] = "failed"

            manifest["last_end"] = datetime.datetime.now().isoformat()

            save_manifest(manifest)

            return

    manifest["last_run_status"] = "success"

    manifest["last_end"] = datetime.datetime.now().isoformat()

    save_manifest(manifest)

    print("QPX COMPLETE")


if __name__ == "__main__":
    main()