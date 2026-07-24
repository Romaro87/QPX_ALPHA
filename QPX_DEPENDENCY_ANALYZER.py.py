#!/usr/bin/env python3
"""
=============================================================
QPX DEPENDENCY ANALYZER
QPX Alpha Step 15.5

Reads
    scanner.json
    architecture.json

Produces
    dependency_analysis.json

Purpose
-------
Analyze module relationships and identify architectural
characteristics based on observed imports.
=============================================================
"""

import os
import json
import datetime
from collections import Counter

ROOT = "/storage/emulated/0/QPX_ALPHA"
CONTEXT = os.path.join(ROOT, "QPX_CONTEXT")

SCANNER = os.path.join(CONTEXT, "scanner.json")
ARCH = os.path.join(CONTEXT, "architecture.json")

OUTPUT = os.path.join(
    CONTEXT,
    "dependency_analysis.json"
)


def load(path):

    with open(path, "r", encoding="utf-8") as f:

        return json.load(f)


def main():

    scanner = load(SCANNER)
    arch = load(ARCH)

    files = scanner["files"]

    module_names = {}

    for f in files:

        if f["extension"] == ".py":

            module = os.path.splitext(f["name"])[0]

            module_names[module] = f["name"]

    imported = Counter()

    import_count = {}

    missing = {}

    orphan_candidates = []

    dependency_score = []

    for f in files:

        if f["extension"] != ".py":
            continue

        imports = f.get("imports", [])

        import_count[f["name"]] = len(imports)

        dependency_score.append({

            "module": f["name"],

            "imports": len(imports)

        })

        if len(imports) == 0:

            orphan_candidates.append(f["name"])

        for imp in imports:

            root = imp.split(".")[0]

            imported[root] += 1

            if root not in module_names:

                missing[root] = missing.get(root, 0) + 1

    dependency_score.sort(

        key=lambda x: x["imports"],

        reverse=True

    )

    core_modules = []

    for mod, count in imported.most_common(20):

        if mod in module_names:

            core_modules.append({

                "module": module_names[mod],

                "times_imported": count

            })

    report = {

        "generated":

            datetime.datetime.now().isoformat(),

        "core_modules":

            core_modules,

        "highest_dependency_modules":

            dependency_score[:20],

        "possible_orphans":

            sorted(orphan_candidates),

        "missing_imports":

            dict(

                sorted(

                    missing.items(),

                    key=lambda x: x[1],

                    reverse=True

                )

            ),

        "summary": {

            "python_modules":

                scanner["statistics"]["python"],

            "unique_imports":

                len(imported),

            "core_modules":

                len(core_modules),

            "possible_orphans":

                len(orphan_candidates),

            "missing_import_groups":

                len(missing)

        },

        "observations": []

    }

    if report["summary"]["possible_orphans"] > 20:

        report["observations"].append(

            "Many modules have no detected imports. "

            "Review whether they are standalone utilities "

            "or candidates for consolidation."

        )

    if report["summary"]["missing_import_groups"] > 0:

        report["observations"].append(

            "Some imports do not correspond to project "

            "modules. They may be standard library modules, "

            "third-party packages, or unresolved references."

        )

    if len(arch["entry_points"]) > 50:

        report["observations"].append(

            "Large number of executable entry points "

            "suggests separating user workflows from "

            "developer tooling."

        )

    with open(

        OUTPUT,

        "w",

        encoding="utf-8"

    ) as f:

        json.dump(

            report,

            f,

            indent=4

        )

    print("=" * 60)
    print("QPX DEPENDENCY ANALYZER")
    print("=" * 60)
    print("Core Modules           :", len(report["core_modules"]))
    print("Possible Orphans       :", report["summary"]["possible_orphans"])
    print("Missing Import Groups  :", report["summary"]["missing_import_groups"])
    print()
    print("Output")
    print(OUTPUT)
    print("STATUS: COMPLETE")


if __name__ == "__main__":
    main()