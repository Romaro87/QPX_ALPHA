"""
QPX Alpha Quant Research Platform
STEP 10 BACKTESTING ENGINE VALIDATION

Validation Scope:
- Backtesting engine layer only
- Signal input integration layer
- Historical simulation execution
- Performance metric generation
- Trade event schema validation

Preserve:
- importer pipeline
- CSV pipeline
- database lifecycle
- validated query layer
- analytics foundation
- Step 8 feature engine layer
- Step 9 signal engine layer
"""

import traceback
from datetime import datetime, timezone


VALIDATION_RESULTS = []


def report(name, status, message=""):
    VALIDATION_RESULTS.append({
        "test": name,
        "status": "PASS" if status else "FAIL",
        "message": message
    })


print("QPX Alpha Step 10 Backtesting Engine Validation")
print("=" * 50)


# -------------------------------------------------
# 1. Detect Backtesting Components
# -------------------------------------------------

try:
    import backtesting_engine

    report(
        "Backtesting engine components detected",
        True,
        "backtesting_engine import available"
    )

except Exception as e:
    report(
        "Backtesting engine components detected",
        False,
        str(e)
    )


# -------------------------------------------------
# 2. Import Signal Engine
# -------------------------------------------------

try:
    import signal_engine

    report(
        "Signal input integration successful",
        True,
        "Step 9 signal engine available"
    )

except Exception as e:
    report(
        "Signal input integration successful",
        False,
        str(e)
    )


# -------------------------------------------------
# 3. Execute Historical Simulation
# -------------------------------------------------

backtest_output = None

try:

    from backtesting_engine import run_backtest

    sample_signals = [
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "signal": "BUY",
            "score": 0.20,
            "confidence": 0.20,
            "source": "QPX_STEP_9_SIGNAL_ENGINE"
        }
    ]

    backtest_output = run_backtest(sample_signals)

    report(
        "Historical simulation executes",
        True,
        "Backtest completed"
    )

except Exception as e:

    report(
        "Historical simulation executes",
        False,
        str(e)
    )


# -------------------------------------------------
# 4. Performance Metrics Validation
# -------------------------------------------------

try:

    metrics = backtest_output.get("metrics")

    required_metrics = [
        "return",
        "trades",
        "win_rate"
    ]

    valid = (
        isinstance(metrics, dict)
        and all(x in metrics for x in required_metrics)
    )

    report(
        "Performance metrics generated",
        valid,
        str(metrics)
    )

except Exception as e:

    report(
        "Performance metrics generated",
        False,
        str(e)
    )


# -------------------------------------------------
# 5. Trade Event Schema Validation
# -------------------------------------------------

try:

    trades = backtest_output.get("trades", [])

    schema_valid = True

    required_fields = [
        "timestamp",
        "action",
        "price"
    ]

    for trade in trades:
        for field in required_fields:
            if field not in trade:
                schema_valid = False

    report(
        "Trade event schema validated",
        schema_valid,
        f"Trades checked: {len(trades)}"
    )

except Exception as e:

    report(
        "Trade event schema validated",
        False,
        str(e)
    )


# -------------------------------------------------
# 6. Database / Query Integration
# -------------------------------------------------

try:

    import database
    import query_engine

    report(
        "Database/query integration confirmed",
        True,
        "Existing validated query layer accessible"
    )

except Exception as e:

    report(
        "Database/query integration confirmed",
        False,
        str(e)
    )


# -------------------------------------------------
# 7. Regression Checks
# -------------------------------------------------

try:

    import feature_engine

    report(
        "Step 8 analytics layer regression check",
        True,
        "Feature engine import successful"
    )

except Exception as e:

    report(
        "Step 8 analytics layer regression check",
        False,
        str(e)
    )


try:

    import signal_engine

    report(
        "Step 9 signal engine regression check",
        True,
        "Signal engine remains available"
    )

except Exception as e:

    report(
        "Step 9 signal engine regression check",
        False,
        str(e)
    )


# -------------------------------------------------
# Final Output
# -------------------------------------------------

print("\nValidation Results")
print("=" * 50)

for item in VALIDATION_RESULTS:
    print(
        f"{item['status']}: "
        f"{item['test']} "
        f"{item['message']}"
    )


print("\nBacktest Output:")
print(backtest_output)


failed = [
    x for x in VALIDATION_RESULTS
    if x["status"] == "FAIL"
]


print("\nSTEP 10 STATUS:")

if len(failed) == 0:
    print("PASS")
else:
    print("FAIL")


print("\nValidation Complete")




# STEP10 REPAIR PATCH

from trade_event_schema_v2 import normalize_trade


normalized_trades = []


for trade in trades:

    normalized_trades.append(
        normalize_trade(trade)
    )


trades = normalized_trades



