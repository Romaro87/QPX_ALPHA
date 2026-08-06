"""Monthly data-driven selection plus daily persistent paper operation."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from qpx_bot.paper_runner import main as paper_main
from qpx_bot.paper_state import AuditEvent, StateStore
from qpx_bot.symbol_selector import (
    load_selection_config,
    select_from_provider,
    write_selection_artifacts,
)


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
DEFAULT_UNIVERSE = PACKAGE_DIR / "swing_universe.json"
DEFAULT_SELECTION_RUNTIME = (
    PACKAGE_DIR / "selection_runtime"
)
DEFAULT_SELECTION_REPORTS = (
    PROJECT_ROOT / "reports" / "qpx_symbol_selection"
)
DEFAULT_PAPER_RUNTIME = PACKAGE_DIR / "paper_runtime"
DEFAULT_INPUT_DIR = PACKAGE_DIR / "data_inputs"
DEFAULT_PAPER_REPORTS = (
    PROJECT_ROOT / "reports" / "qpx_paper"
)


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _decision_month() -> str:
    return datetime.now(
        timezone.utc
    ).strftime("%Y-%m")


def _load_cached_decision(
    path: Path,
    *,
    month: str,
    candidates: tuple[str, ...],
) -> dict | None:
    if not path.exists():
        return None

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return None

    selected = str(
        payload.get("selected_symbol", "")
    ).strip().upper()

    if (
        payload.get("decision_month") != month
        or selected not in candidates
    ):
        return None

    return payload


def _selection_event(
    *,
    state_id: str,
    previous_symbol: str,
    selected_symbol: str,
    month: str,
) -> AuditEvent:
    raw = (
        f"{state_id}|{previous_symbol}|"
        f"{selected_symbol}|{month}"
    )
    event_id = (
        "symbol-rotation-"
        + hashlib.sha256(
            raw.encode("utf-8")
        ).hexdigest()[:24]
    )

    return AuditEvent(
        event_id=event_id,
        event_type="SYMBOL_ROTATION",
        event_date=datetime.now().date(),
        details={
            "previous_symbol": previous_symbol,
            "selected_symbol": selected_symbol,
            "decision_month": month,
            "selection_policy": (
                "data-driven; no symbol bonus"
            ),
        },
    )


def _execution_symbol(
    *,
    store: StateStore,
    selected_symbol: str,
    decision_month: str,
) -> tuple[str, str]:
    if not store.exists():
        return (
            selected_symbol,
            "new paper account uses ranked winner",
        )

    with store.locked():
        state = store.load()

        if (
            state.position is not None
            or state.pending_entry is not None
        ):
            return (
                state.swing_symbol,
                (
                    "existing position or pending order locks "
                    "the current symbol until flat"
                ),
            )

        if state.swing_symbol == selected_symbol:
            return (
                selected_symbol,
                "saved paper symbol already matches ranked winner",
            )

        previous_symbol = state.swing_symbol
        state.swing_symbol = selected_symbol
        state.revision += 1
        event = _selection_event(
            state_id=state.state_id,
            previous_symbol=previous_symbol,
            selected_symbol=selected_symbol,
            month=decision_month,
        )
        store.append_events([event])
        store.save(state)

        return (
            selected_symbol,
            (
                f"flat paper account rotated from "
                f"{previous_symbol} to ranked winner"
            ),
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Select a swing ticker without hardcoded preference, "
            "then advance the persistent simulated paper account."
        )
    )
    parser.add_argument(
        "--universe",
        default=str(DEFAULT_UNIVERSE),
    )
    parser.add_argument(
        "--selection-runtime-dir",
        default=str(DEFAULT_SELECTION_RUNTIME),
    )
    parser.add_argument(
        "--selection-report-dir",
        default=str(DEFAULT_SELECTION_REPORTS),
    )
    parser.add_argument(
        "--paper-runtime-dir",
        default=str(DEFAULT_PAPER_RUNTIME),
    )
    parser.add_argument(
        "--input-dir",
        default=str(DEFAULT_INPUT_DIR),
    )
    parser.add_argument(
        "--paper-report-dir",
        default=str(DEFAULT_PAPER_REPORTS),
    )
    parser.add_argument(
        "--force-reselect",
        action="store_true",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = load_selection_config(args.universe)
    month = _decision_month()
    selection_runtime = Path(
        args.selection_runtime_dir
    ).expanduser().resolve()
    decision_path = (
        selection_runtime / "selection_decision.json"
    )
    cached = (
        None
        if args.force_reselect
        else _load_cached_decision(
            decision_path,
            month=month,
            candidates=config.candidates,
        )
    )

    print("=" * 78)
    print("QPX BOT v1.10 — SYMBOL-NEUTRAL AUTO PAPER RUNNER")
    print("=" * 78)
    print(
        "SPY is a candidate only; it has no bonus, "
        "fallback, or default."
    )

    if cached is None:
        result = select_from_provider(config)
        artifacts = write_selection_artifacts(
            result,
            args.selection_report_dir,
        )
        selected_symbol = result.selected_symbol
        decision = {
            "decision_month": month,
            "selected_symbol": selected_symbol,
            "created_at_utc": result.generated_at_utc,
            "latest_market_date": (
                result.latest_market_date.isoformat()
            ),
            "symbol_bonus_policy": (
                result.symbol_bonus_policy
            ),
            "report": str(artifacts["report"]),
            "result": str(artifacts["result"]),
        }
        _atomic_json(decision_path, decision)
        print()
        print(
            f"Monthly ranked winner: {selected_symbol}"
        )
        print(f"Selection report: {artifacts['report']}")
    else:
        selected_symbol = str(
            cached["selected_symbol"]
        ).strip().upper()
        print(
            f"Using cached monthly winner: {selected_symbol}"
        )

    paper_store = StateStore(args.paper_runtime_dir)
    execution_symbol, reason = _execution_symbol(
        store=paper_store,
        selected_symbol=selected_symbol,
        decision_month=month,
    )
    print(f"Execution symbol     : {execution_symbol}")
    print(f"Execution policy     : {reason}")
    print()

    return paper_main(
        [
            "--symbol",
            execution_symbol,
            "--runtime-dir",
            str(
                Path(args.paper_runtime_dir)
                .expanduser()
                .resolve()
            ),
            "--input-dir",
            str(
                Path(args.input_dir)
                .expanduser()
                .resolve()
            ),
            "--report-dir",
            str(
                Path(args.paper_report_dir)
                .expanduser()
                .resolve()
            ),
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
