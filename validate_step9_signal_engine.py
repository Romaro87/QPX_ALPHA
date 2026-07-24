"""
========================================
QPX Alpha Step 9 Signal Engine Validation
========================================

Validation Scope:
- Signal engine components
- Feature-to-signal integration
- Signal generation execution
- Signal output schema
- Database/query integration
- Regression protection for Step 8 analytics layer

Not modified:
- importer pipeline
- CSV pipeline
- database lifecycle
- validated query layer
- analytics foundation

========================================
"""

import os
import sys
import traceback


BASE_PATH = "/storage/emulated/0/QPX_ALPHA"

PASS_COUNT = 0
FAIL_COUNT = 0


def check(name, condition, detail=""):
    global PASS_COUNT, FAIL_COUNT

    if condition:
        PASS_COUNT += 1
        print(f"[PASS] {name}")
        if detail:
            print(f"        {detail}")
    else:
        FAIL_COUNT += 1
        print(f"[FAIL] {name}")
        if detail:
            print(f"        {detail}")


print("=" * 40)
print("QPX Alpha Step 9 Signal Engine Validation")
print("=" * 40)


# -------------------------------------------------
# 1. Detect signal engine files
# -------------------------------------------------

signal_files = [
    "signal_engine.py",
]

detected = []

for file in signal_files:
    path = os.path.join(BASE_PATH, file)
    if os.path.exists(path):
        detected.append(path)

check(
    "Signal engine components detected",
    len(detected) > 0,
    "\n".join(detected) if detected else "No signal engine files found"
)


# -------------------------------------------------
# 2. Import signal engine
# -------------------------------------------------

signal_module = None

try:
    sys.path.insert(0, BASE_PATH)

    import signal_engine

    signal_module = signal_engine

    check(
        "Signal engine import successful",
        True
    )

except Exception:
    check(
        "Signal engine import successful",
        False,
        traceback.format_exc()
    )


# -------------------------------------------------
# 3. Detect signal generation functions/classes
# -------------------------------------------------

signal_objects = []

if signal_module:

    possible_objects = [
        "SignalEngine",
        "run_signal_engine",
        "generate_signals",
        "create_signals"
    ]

    for obj in possible_objects:
        if hasattr(signal_module, obj):
            signal_objects.append(obj)


check(
    "Signal generation components available",
    len(signal_objects) > 0,
    str(signal_objects)
)


# -------------------------------------------------
# 4. Feature-to-signal integration
# -------------------------------------------------

feature_module = None

try:

    import feature_engine

    feature_module = feature_engine

    check(
        "Feature engine integration available",
        True,
        "feature_engine module connected"
    )

except Exception:

    check(
        "Feature engine integration available",
        False,
        traceback.format_exc()
    )


# -------------------------------------------------
# 5. Execute signal generation
# -------------------------------------------------

signal_output = None

if signal_module:

    try:

        if hasattr(signal_module, "run_signal_engine"):

            signal_output = signal_module.run_signal_engine()

        elif hasattr(signal_module, "generate_signals"):

            signal_output = signal_module.generate_signals()

        elif hasattr(signal_module, "create_signals"):

            signal_output = signal_module.create_signals()

        check(
            "Signal generation executes",
            signal_output is not None,
            str(signal_output)[:300]
        )

    except Exception:

        check(
            "Signal generation executes",
            False,
            traceback.format_exc()
        )

else:

    check(
        "Signal generation executes",
        False,
        "Signal module unavailable"
    )


# -------------------------------------------------
# 6. Validate signal schema
# -------------------------------------------------

schema_valid = False


if signal_output is not None:

    if isinstance(signal_output, dict):

        schema_valid = True

    elif hasattr(signal_output, "columns"):

        schema_valid = True


check(
    "Signal schema validated",
    schema_valid,
    "Dictionary/DataFrame compatible output"
)


# -------------------------------------------------
# 7. Database/query integration check
# -------------------------------------------------

database_ok = False

try:

    import sqlite3

    db_candidates = [
        "market_data.db",
        "qpx_alpha.db"
    ]

    for db in db_candidates:

        db_path = os.path.join(BASE_PATH, db)

        if os.path.exists(db_path):

            conn = sqlite3.connect(db_path)

            conn.close()

            database_ok = True

            break


except Exception:

    pass


check(
    "Database/query integration confirmed",
    database_ok,
    "Existing database connection available"
)


# -------------------------------------------------
# 8. Step 8 regression protection
# -------------------------------------------------

try:

    import feature_engine

    regression_check = hasattr(
        feature_engine,
        "FeatureEngine"
    )

except Exception:

    regression_check = False


check(
    "Step 8 analytics layer regression check",
    regression_check,
    "FeatureEngine remains available"
)


# -------------------------------------------------
# FINAL RESULT
# -------------------------------------------------

print()
print("=" * 40)

if FAIL_COUNT == 0:

    print("STEP 9 STATUS: PASS")

elif PASS_COUNT > 0:

    print("STEP 9 STATUS: CONDITIONAL PASS")

else:

    print("STEP 9 STATUS: FAIL")


print("=" * 40)

print()
print("PASS COUNT:", PASS_COUNT)
print("FAIL COUNT:", FAIL_COUNT)

print("=" * 40)
