#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import sys

from contextlib import redirect_stdout
from datetime import date, datetime
from pathlib import Path


EXPECTED_SELECTION_FP = (
    "5e271e4a9e0d4a20b6f4d0cecc08e8b"
    "f9efe1d2123a64832d09ba1c1eb9ffd23"
)

EXPECTED_DATASET_FP = (
    "1a0d8d772b02079ee340109811d38678"
    "c73053f9a55e2fb3d3b5b96e484c5007"
)

RUN_VERSION = "candidate_v1_frozen_top100_portfolio_v1"

START = date(2024, 3, 7)
END = date(2026, 8, 7)


def find_root() -> Path:
    candidates = [
        Path("/storage/emulated/0/QPX_ALPHA"),
        Path.cwd(),
        Path(__file__).resolve().parent,
    ]

    checked = set()

    for start in candidates:
        try:
            start = start.resolve()
        except Exception:
            pass

        for candidate in (start, *start.parents):
            if candidate in checked:
                continue
            checked.add(candidate)

            if (
                (candidate / ".git").exists()
                and (candidate / "qpx_bot").exists()
                and (candidate / "QPX_RUN_SCENARIO.py").exists()
                and (candidate / "QPX_FIND_BEST_ALPACA_SWING.py").exists()
            ):
                return candidate

    raise RuntimeError(
        "Could not locate QPX_ALPHA. "
        "Expected /storage/emulated/0/QPX_ALPHA."
    )


ROOT = find_root()

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import QPX_FIND_BEST_ALPACA_SWING as sweep
import QPX_FREEZE_TOP100_ALPACA_DATA as freezer
import QPX_RUN_SCENARIO as runner

from qpx_bot.scenario_config import (
    load_scenario,
    validate_scenario,
)


FROZEN_ROOT = freezer.FROZEN_ROOT
SELECTION_PATH = freezer.SELECTION
DATASET_MANIFEST = freezer.DATASET_MANIFEST

RUNTIME_ROOT = (
    FROZEN_ROOT
    / "top100_portfolio_runtime_v1"
)

RUNTIME_SHARED = (
    RUNTIME_ROOT
    / "shared"
)

REPORT_ROOT = (
    ROOT
    / "reports"
    / "qpx_frozen_top100_portfolio_v1"
)

SUMMARY_JSON = (
    REPORT_ROOT
    / "summary.json"
)

CONSOLE_LOG = (
    REPORT_ROOT
    / "console.txt"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def atomic_json(path: Path, payload) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = path.with_suffix(
        path.suffix + ".tmp"
    )

    temporary.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary.replace(path)


def load_frozen_state():
    if not SELECTION_PATH.exists():
        raise RuntimeError(
            f"Frozen Top-100 selection missing: {SELECTION_PATH}"
        )

    if not DATASET_MANIFEST.exists():
        raise RuntimeError(
            f"Frozen dataset manifest missing: {DATASET_MANIFEST}"
        )

    selection = json.loads(
        SELECTION_PATH.read_text(
            encoding="utf-8"
        )
    )

    dataset = json.loads(
        DATASET_MANIFEST.read_text(
            encoding="utf-8"
        )
    )

    if (
        selection.get("status")
        != "AUDITED_SELECTION_FROZEN"
    ):
        raise RuntimeError(
            "Top-100 selection is not AUDITED_SELECTION_FROZEN."
        )

    if (
        selection.get("manifest_fingerprint")
        != EXPECTED_SELECTION_FP
    ):
        raise RuntimeError(
            "Top-100 selection fingerprint changed. "
            "STOP rather than silently using a different universe."
        )

    if (
        dataset.get("status")
        != "FROZEN_AND_VERIFIED"
    ):
        raise RuntimeError(
            "Frozen dataset is not FROZEN_AND_VERIFIED."
        )

    if (
        dataset.get("dataset_fingerprint")
        != EXPECTED_DATASET_FP
    ):
        raise RuntimeError(
            "Frozen dataset fingerprint changed. "
            "STOP rather than silently using different data."
        )

    top100 = [
        str(symbol).strip().upper()
        for symbol in selection["top100"]
    ]

    if len(top100) != 100:
        raise RuntimeError(
            f"Expected exactly 100 Top-100 symbols, got {len(top100)}."
        )

    if len(set(top100)) != 100:
        raise RuntimeError(
            "Top-100 selection contains duplicates."
        )

    symbols = dataset.get("symbols", {})

    required = [
        *top100,
        "QDTE",
    ]

    for symbol in required:
        if symbol not in symbols:
            raise RuntimeError(
                f"{symbol}: missing from frozen dataset manifest."
            )

    return selection, dataset, top100


def verify_required_files(
    dataset,
    top100,
) -> None:
    print("=" * 92)
    print("QPX FROZEN TOP-100 PORTFOLIO BACKTEST — DATA VERIFY")
    print("=" * 92)

    # Original freeze verifier:
    # validates all 102 frozen bar files, support files,
    # common-clock hash, and the dataset fingerprint.
    freezer.verify_dataset()

    for symbol in [*top100, "QDTE"]:
        path = freezer.frozen_bar_path(
            symbol
        )

        expected = (
            dataset["symbols"][symbol]["sha256"]
        )

        actual = sha256(path)

        if actual != expected:
            raise RuntimeError(
                f"{symbol}: frozen bar hash mismatch."
            )

    print("TOP-100 DATA FILES     : VERIFIED")
    print("NETWORK DATA REFRESH   : DISABLED")
    print("SYNTHETIC DATA         : DISABLED")
    print("FORWARD FILL           : DISABLED")
    print("TIMESTAMP SUBSTITUTION : DISABLED")
    print("=" * 92)
    print()


def support_item_by_name(
    dataset,
    name: str,
):
    for key, item in (
        dataset.get("support", {})
        .items()
    ):
        path_value = str(
            item.get("path", "")
        )

        if (
            Path(path_value).name
            == name
        ):
            return key, item

    return None, None


def prepare_runtime_support(
    dataset,
) -> None:
    RUNTIME_SHARED.mkdir(
        parents=True,
        exist_ok=True,
    )

    required = (
        "CBOE_VIX_DAILY.csv",
        "QDTE_DIVIDENDS.csv",
    )

    optional = (
        "QDTE_DIVIDENDS.csv.manifest.json",
    )

    for name in (*required, *optional):
        _, item = support_item_by_name(
            dataset,
            name,
        )

        if item is not None:
            source = (
                FROZEN_ROOT
                / item["path"]
            )
            expected = item["sha256"]
        else:
            source = (
                FROZEN_ROOT
                / "support"
                / name
            )
            expected = (
                sha256(source)
                if source.exists()
                else None
            )

        if not source.exists():
            if name in optional:
                continue

            raise RuntimeError(
                f"Frozen support file missing: {source}"
            )

        if (
            expected is not None
            and sha256(source) != expected
        ):
            raise RuntimeError(
                f"Frozen support hash mismatch: {source}"
            )

        target = (
            RUNTIME_SHARED
            / name
        )

        if (
            not target.exists()
            or sha256(target)
            != sha256(source)
        ):
            temporary = (
                target.with_suffix(
                    target.suffix + ".tmp"
                )
            )

            shutil.copyfile(
                source,
                temporary,
            )

            temporary.replace(
                target
            )


def make_scenario_payload(
    top100,
):
    base = load_scenario(
        sweep.BASE
    )

    payload = (
        base.clone_payload()
    )

    payload["name"] = (
        "frozen_top100_portfolio_v1"
    )

    payload["description"] = (
        "QPX Candidate V1 viability test using the "
        "entire audited frozen Alpaca Top-100 universe "
        "simultaneously. $1300 total starting capital; "
        "$1300 initially QDTE; $0 initial swing cash; "
        "zero external contributions; Thursday-only "
        "weekly rebalancing."
    )

    payload["revision"] = 1

    payload["symbols"][
        "candidate_symbols"
    ] = list(top100)

    payload["symbols"][
        "tradable_symbols"
    ] = list(top100)

    payload["capital"][
        "monthly_contribution"
    ] = 0.0

    payload["capital"][
        "starting_total_capital"
    ] = 1300.0

    payload["allocation"][
        "rebalance_frequency"
    ] = "weekly"

    validate_scenario(
        payload
    )

    return payload


def patch_frozen_bar_root(
    source: str,
) -> str:
    old = '''FRESH_CACHE = (
    FRESH_ROOT
    / "shared"
    / "aggregate_15m"
)'''

    new = (
        "FRESH_CACHE = Path("
        + repr(
            str(
                FROZEN_ROOT
                / "bars"
            )
        )
        + ")"
    )

    count = source.count(old)

    if count != 1:
        raise RuntimeError(
            "Could not redirect the generated runner "
            f"to frozen Top-100 bars; found {count} cache blocks."
        )

    return source.replace(
        old,
        new,
        1,
    )


def isolate_report_folder(
    source: str,
    scenario_name: str,
) -> str:
    old_report = (
        "qpx_scenario_"
        + runner.safe_name(
            scenario_name
        )
    )

    new_report = (
        "qpx_frozen_top100_portfolio_v1"
        "/engine"
    )

    count = source.count(
        old_report
    )

    if count != 1:
        raise RuntimeError(
            "Could not isolate Top-100 report folder. "
            f"Found {count} report markers."
        )

    return source.replace(
        old_report,
        new_report,
        1,
    )


def engine_fingerprint() -> str:
    files = [
        Path(sweep.__file__).resolve(),
        Path(runner.__file__).resolve(),
        Path(freezer.__file__).resolve(),
        runner.REFERENCE_RUNNER.resolve(),
        Path(
            ROOT
            / "qpx_bot"
            / "actual_two_year_15m_six.py"
        ),
        Path(sweep.BASE).resolve(),
    ]

    payload = []

    for path in files:
        if not path.exists():
            raise RuntimeError(
                f"Engine fingerprint file missing: {path}"
            )

        try:
            relative = path.relative_to(ROOT)
            label = str(relative)
        except ValueError:
            label = str(path)

        payload.append(
            (
                label,
                sha256(path),
            )
        )

    encoded = json.dumps(
        payload,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    return hashlib.sha256(
        encoded
    ).hexdigest()


def run_backtest(
    selection,
    dataset,
    top100,
):
    prepare_runtime_support(
        dataset
    )

    payload = make_scenario_payload(
        top100
    )

    scenario_path = (
        RUNTIME_ROOT
        / "top100_scenario.json"
    )

    scenario_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    scenario_path.write_text(
        json.dumps(
            payload,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    scenario = load_scenario(
        scenario_path
    )

    source = runner.build_source(
        scenario,
        start=START,
        end=END,
    )

    source = (
        runner.adapt_source_for_provider(
            source,
            scenario=scenario,
            provider_root=RUNTIME_ROOT,
        )
    )

    # Reuse frozen bar files directly.
    source = patch_frozen_bar_root(
        source
    )

    # Enforce exact $1300 QDTE / $0 swing seed and
    # Thursday-only weekly rebalance used by discovery.
    source = sweep.patch_generated_source(
        source,
        "TOP100",
    )

    source = isolate_report_folder(
        source,
        scenario.name,
    )

    REPORT_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    output = io.StringIO()

    namespace = {
        "__name__": "__main__",
        "__file__": str(
            runner.REFERENCE_RUNNER
        ),
    }

    print("=" * 92)
    print("QPX CANDIDATE V1 — FROZEN TOP-100 PORTFOLIO VIABILITY TEST")
    print("=" * 92)
    print(f"Universe               : {len(top100)} FROZEN TOP-100 SYMBOLS")
    print(f"Start                  : {START}")
    print(f"End                    : {END}")
    print("Starting total         : $1,300.00")
    print("Starting QDTE          : $1,300.00")
    print("Starting swing cash    : $0.00")
    print("External contributions : $0.00")
    print("Rebalance              : THURSDAY-ONLY WEEKLY")
    print(
        "Maximum positions      : "
        f"{scenario.risk['maximum_positions']}"
    )
    print(
        "Risk / active risk     : "
        f"{scenario.risk['risk_per_trade']:.2%} / "
        f"{scenario.risk['maximum_active_portfolio_risk']:.2%}"
    )
    print(
        "Position notional cap  : "
        f"{scenario.risk['maximum_position_notional']:.2%}"
    )
    print("Network data fetch     : DISABLED")
    print("Frozen dataset         : VERIFIED")
    print(
        "Dataset fingerprint    : "
        f"{dataset['dataset_fingerprint']}"
    )

    clock = dataset.get(
        "all102_common_clock",
        {},
    )

    print(
        "All-102 clock status   : "
        f"{clock.get('status', 'UNKNOWN')}"
    )
    print(
        "All-102 common bars    : "
        f"{int(clock.get('bars', 0)):,}"
    )
    print(
        "All-102 clock coverage : "
        f"{float(clock.get('qdte_bar_coverage', 0.0)):.2%}"
    )

    print(
        "Causal replay audit    : "
        "NOT YET FORMALLY QUALIFIED"
    )
    print(
        "Interpretation         : "
        "PRELIMINARY VIABILITY RESEARCH ONLY"
    )
    print("=" * 92)
    print()

    with redirect_stdout(
        output
    ):
        exec(
            compile(
                source,
                str(
                    runner.REFERENCE_RUNNER
                ),
                "exec",
            ),
            namespace,
        )

    text = output.getvalue()

    CONSOLE_LOG.write_text(
        text,
        encoding="utf-8",
    )

    print(text)

    match = sweep.RESULT_RE.search(
        text
    )

    if not match:
        raise RuntimeError(
            "Backtest did not report a result artifact. "
            f"See {CONSOLE_LOG}"
        )

    result_path = Path(
        match.group(1).strip()
    ).expanduser()

    if not result_path.is_absolute():
        result_path = (
            ROOT
            / result_path
        ).resolve()

    if not result_path.exists():
        raise RuntimeError(
            f"Backtest result artifact missing: {result_path}"
        )

    result = json.loads(
        result_path.read_text(
            encoding="utf-8"
        )
    )

    if (
        result["actual_start"]
        != START.isoformat()
        or result["actual_end"]
        != END.isoformat()
    ):
        raise RuntimeError(
            "Top-100 engine did not preserve the requested "
            "full comparison date range."
        )

    git_head = subprocess.check_output(
        [
            "git",
            "rev-parse",
            "HEAD",
        ],
        cwd=ROOT,
        text=True,
    ).strip()

    summary = {
        "schema_version": 1,
        "run_version": RUN_VERSION,
        "status": "COMPLETE",
        "research_classification": (
            "PRELIMINARY_VIABILITY_ONLY"
        ),
        "causal_replay_qualification": (
            "NOT_YET_FORMALLY_AUDITED"
        ),
        "selection_fingerprint": (
            selection[
                "manifest_fingerprint"
            ]
        ),
        "dataset_fingerprint": (
            dataset[
                "dataset_fingerprint"
            ]
        ),
        "engine_fingerprint": (
            engine_fingerprint()
        ),
        "git_head": git_head,
        "universe_count": len(
            top100
        ),
        "universe": list(
            top100
        ),
        "all102_common_clock": (
            dataset.get(
                "all102_common_clock"
            )
        ),
        "scenario": payload,
        "engine_result_artifact": str(
            result_path.relative_to(ROOT)
            if result_path.is_relative_to(ROOT)
            else result_path
        ),
        "result": result,
        "created_at": (
            datetime.now()
            .astimezone()
            .isoformat()
        ),
    }

    core = json.dumps(
        summary,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")

    summary[
        "summary_fingerprint"
    ] = hashlib.sha256(
        core
    ).hexdigest()

    atomic_json(
        SUMMARY_JSON,
        summary,
    )

    return result, summary


def format_pf(value):
    try:
        value = float(value)
    except Exception:
        return "N/A"

    if value == float("inf"):
        return "INF"

    return f"{value:.3f}"


def main() -> int:
    print()
    print(
        "Repository             :",
        ROOT,
    )
    print(
        "Frozen root            :",
        FROZEN_ROOT,
    )
    print()

    selection, dataset, top100 = (
        load_frozen_state()
    )

    verify_required_files(
        dataset,
        top100,
    )

    result, summary = run_backtest(
        selection,
        dataset,
        top100,
    )

    print()
    print("=" * 92)
    print("QPX FROZEN TOP-100 PORTFOLIO — RESULT")
    print("=" * 92)
    print(
        "Actual range           : "
        f"{result['actual_start']} -> "
        f"{result['actual_end']}"
    )
    print(
        "Common 15m bars        : "
        f"{int(result['common_test_bars']):,}"
    )
    print(
        "Market sessions        : "
        f"{int(result['test_sessions']):,}"
    )
    print(
        "Session coverage       : "
        f"{float(result['session_coverage']):.2%}"
    )
    print(
        "Closed swing trades    : "
        f"{int(result['closed_trades']):,}"
    )
    print(
        "Win rate               : "
        f"{float(result['win_rate']):.2%}"
    )
    print(
        "Profit factor          : "
        f"{format_pf(result.get('profit_factor'))}"
    )
    print(
        "Closed swing P&L       : "
        f"${float(result['closed_swing_trade_pnl']):,.2f}"
    )
    print(
        "Income rebalance P&L   : "
        f"${float(result['income_rebalance_realized_pnl']):,.2f}"
    )
    print(
        "QDTE distributions     : "
        f"${float(result['qdte_distributions_received']):,.2f}"
    )
    print(
        "Net portfolio profit   : "
        f"${float(result['net_profit']):,.2f}"
    )
    print(
        "Ending equity          : "
        f"${float(result['ending_equity']):,.2f}"
    )
    print(
        "CAGR                   : "
        f"{float(result['flow_adjusted_cagr']):.2%}"
    )
    print(
        "Maximum drawdown       : "
        f"{float(result['maximum_drawdown']):.2%}"
    )
    print(
        "Risk rejections        : "
        f"{int(result['risk_rejections']):,}"
    )
    print(
        "Notional adjustments   : "
        f"{int(result['notional_cap_adjustments']):,}"
    )
    print(
        "Causal replay status   : "
        "NOT YET FORMALLY QUALIFIED"
    )
    print(
        "Summary                : "
        f"{SUMMARY_JSON}"
    )
    print(
        "Summary fingerprint    : "
        f"{summary['summary_fingerprint']}"
    )
    print("=" * 92)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
