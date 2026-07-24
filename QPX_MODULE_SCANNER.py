#!/usr/bin/env python3

import os
import ast
import json
import datetime

ROOT = "/storage/emulated/0/QPX_ALPHA"

MANIFEST = os.path.join(
    ROOT,
    "qpx_module_manifest.json"
)

IGNORE = {
    "__pycache__",
    ".git",
    "venv",
    "env"
}


def classify(path):

    with open(
        path,
        "r",
        encoding="utf-8"
    ) as f:

        tree = ast.parse(f.read())

    classes = []
    functions = []

    for node in tree.body:

        if isinstance(node, ast.ClassDef):
            classes.append(node.name)

        elif isinstance(node, ast.FunctionDef):
            functions.append(node.name)

    if "run" in functions:

        return {

            "type": "executable",

            "entry": "run"

        }

    if "main" in functions:

        return {

            "type": "executable",

            "entry": "main"

        }

    if classes:

        return {

            "type": "library",

            "classes": classes

        }

    return {

        "type": "utility",

        "functions": functions

    }


def main():

    modules = []

    for root, dirs, files in os.walk(ROOT):

        dirs[:] = [
            d for d in dirs
            if d not in IGNORE
        ]

        for file in files:

            if not file.endswith(".py"):
                continue

            path = os.path.join(
                root,
                file
            )

            try:

                info = classify(path)

                info["file"] = file

                modules.append(info)

                print(file, info["type"])

            except Exception as e:

                modules.append({

                    "file": file,

                    "type": "error",

                    "error": str(e)

                })

    manifest = {

        "generated": datetime.datetime.now().isoformat(),

        "modules": modules

    }

    with open(

        MANIFEST,

        "w",

        encoding="utf-8"

    ) as f:

        json.dump(

            manifest,

            f,

            indent=4

        )

    print()

    print("Manifest created")

    print(MANIFEST)


if __name__ == "__main__":

    main()