"""
==================================================
QPX ALPHA QUANT RESEARCH PLATFORM
STEP 11 AUTOMATED PORTFOLIO VALIDATION
==================================================

Self-discovering validator.
Does not modify project files.
"""

import os
import sys
import importlib
import traceback


ROOT = os.path.dirname(
    os.path.abspath(__file__)
)


print("=" * 55)
print("QPX Alpha Step 11 Automated Portfolio Validation")
print("=" * 55)


results = []


def report(name, status, detail=""):
    state = "PASS" if status else "FAIL"
    print(f"{state}: {name} {detail}")
    results.append(
        {
            "name": name,
            "status": status,
            "detail": detail
        }
    )


# --------------------------------------------------
# MODULE DISCOVERY
# --------------------------------------------------

def discover_modules(keywords):

    found = []

    for root, dirs, files in os.walk(ROOT):

        for file in files:

            if file.endswith(".py"):

                lower = file.lower()

                for key in keywords:

                    if key in lower:

                        path = os.path.join(
                            root,
                            file
                        )

                        found.append(
                            path
                        )

    return found


print("\nSearching QPX modules...")


portfolio_files = discover_modules(
    [
        "portfolio",
        "allocation",
        "position"
    ]
)


analytics_files = discover_modules(
    [
        "analytics",
        "metric",
        "analysis"
    ]
)


print("\nPortfolio candidates:")
for f in portfolio_files:
    print(" -", f)


print("\nAnalytics candidates:")
for f in analytics_files:
    print(" -", f)


# --------------------------------------------------
# IMPORT TESTING
# --------------------------------------------------

def path_to_module(path):

    relative = os.path.relpath(
        path,
        ROOT
    )

    module = relative.replace(
        os.sep,
        "."
    )

    return module[:-3]


def inspect_module(path):

    try:

        module_name = path_to_module(path)

        module = importlib.import_module(
            module_name
        )

        classes = [
            x for x in dir(module)
            if not x.startswith("_")
        ]

        return True, classes

    except Exception as e:

        return False, str(e)



portfolio_objects = []


for file in portfolio_files:

    ok, info = inspect_module(file)

    if ok:

        report(
            "Portfolio module import",
            True,
            file
        )

        portfolio_objects.extend(info)

    else:

        report(
            "Portfolio module import",
            False,
            str(info)
        )


analytics_objects = []


for file in analytics_files:

    ok, info = inspect_module(file)

    if ok:

        report(
            "Analytics module import",
            True,
            file
        )

        analytics_objects.extend(info)

    else:

        report(
            "Analytics module import",
            False,
            str(info)
        )



# --------------------------------------------------
# CLASS DISCOVERY
# --------------------------------------------------

portfolio_classes = [

    x for x in portfolio_objects

    if any(
        word in x.lower()

        for word in
        [
            "portfolio",
            "allocation",
            "constructor",
            "position"
        ]
    )

]


analytics_classes = [

    x for x in analytics_objects

    if any(
        word in x.lower()

        for word in
        [
            "metric",
            "analytics",
            "performance"
        ]
    )

]


report(
    "Portfolio construction component discovery",
    len(portfolio_classes) > 0,
    str(portfolio_classes)
)


report(
    "Analytics component discovery",
    len(analytics_classes) > 0,
    str(analytics_classes)
)



# --------------------------------------------------
# REGRESSION CHECKS
# --------------------------------------------------

for module in [

    "signal_engine",
    "backtesting_engine"

]:

    try:

        importlib.import_module(
            module
        )

        report(
            module + " regression",
            True,
            "available"
        )

    except Exception as e:

        report(
            module + " regression",
            False,
            str(e)
        )



# --------------------------------------------------
# SUMMARY
# --------------------------------------------------

print("\n")
print("=" * 55)
print("STEP 11 AUTOMATED VALIDATION SUMMARY")
print("=" * 55)


failed = [

    x for x in results
    if not x["status"]

]


print(
    "Checks:",
    len(results)
)

print(
    "Failures:",
    len(failed)
)


if failed:

    print(
        "\nSTEP 11 STATUS: FAIL (DISCOVERY REQUIRED)"
    )

    print("\nMissing items:")

    for f in failed:

        print(
            "-",
            f["name"],
            ":",
            f["detail"]
        )

else:

    print(
        "\nSTEP 11 STATUS: PASS"
    )


print("\nValidation Complete")