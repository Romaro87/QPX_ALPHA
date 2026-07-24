#!/usr/bin/env python3

import json
import os
import importlib.util
import traceback

ROOT = "/storage/emulated/0/QPX_ALPHA"

MANIFEST = os.path.join(
    ROOT,
    "qpx_module_manifest.json"
)


def load_module(path):

    spec = importlib.util.spec_from_file_location(

        os.path.basename(path)[:-3],

        path

    )

    module = importlib.util.module_from_spec(spec)

    spec.loader.exec_module(module)

    return module


def run(module):

    if hasattr(module, "run"):

        return module.run()

    if hasattr(module, "main"):

        module.main()

        return {

            "status": "success"

        }

    return {

        "status": "skipped"

    }


def main():

    if not os.path.exists(MANIFEST):

        print("Module manifest missing.")

        print("Run QPX_MODULE_SCANNER first.")

        return

    with open(

        MANIFEST,

        "r",

        encoding="utf-8"

    ) as f:

        manifest = json.load(f)

    print("=" * 40)

    print("QPX AUTO START")

    print("=" * 40)

    for info in manifest["modules"]:

        if info["type"] != "executable":

            continue

        file = info["file"]

        print()

        print("Running", file)

        try:

            module = load_module(

                os.path.join(ROOT, file)

            )

            result = run(module)

            print(result)

        except Exception:

            traceback.print_exc()

    print()

    print("Startup Complete")


if __name__ == "__main__":

    main()