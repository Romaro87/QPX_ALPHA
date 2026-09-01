"""Market-calendar lifecycle owner for the Clean-V2 IEX paper runner."""

from __future__ import annotations

import argparse
import json
import signal
import subprocess
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Sequence

from qpx_bot.market_calendar import (
    NEW_YORK,
    MarketSession,
    is_market_session,
    market_session,
    next_market_session,
)


TARGET_UNIT = "qpx-pr50-iex-forward-research-paper-clean-v2.service"
START_OFFSET = timedelta(minutes=5)
STOP_OFFSET = timedelta(minutes=5)
ACTIVE_RECONCILE_SECONDS = 300
MAX_IDLE_SLEEP_SECONDS = 3600
ERROR_RETRY_SECONDS = 300


@dataclass(frozen=True, slots=True)
class SessionWindow:
    session: MarketSession
    configured_start: datetime
    configured_stop: datetime


@dataclass(frozen=True, slots=True)
class ScheduleDecision:
    evaluated_at_utc: datetime
    market_time: datetime
    market_session_state: str
    window: SessionWindow
    desired_active: bool
    next_action: str
    next_action_at: datetime


class SystemdControlError(RuntimeError):
    pass


class SystemdUserController:
    def __init__(self, unit: str = TARGET_UNIT):
        if unit != TARGET_UNIT:
            raise ValueError("The Clean-V2 supervisor may control only its fixed target unit.")
        self.unit = unit

    def _run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ("systemctl", "--user", *arguments),
                check=False,
                capture_output=True,
                text=True,
                timeout=360,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise SystemdControlError(
                f"Unable to invoke user systemd for {self.unit}: {exc}"
            ) from exc

    def state(self) -> str:
        result = self._run("show", self.unit, "--property=ActiveState", "--value")
        value = result.stdout.strip()
        if result.returncode != 0 or value not in {
            "active", "activating", "deactivating", "inactive", "failed", "reloading",
        }:
            message = result.stderr.strip() or value or f"exit={result.returncode}"
            raise SystemdControlError(
                f"Cannot determine {self.unit} state: {message}"
            )
        return value

    def start(self) -> None:
        result = self._run("start", self.unit)
        if result.returncode:
            raise SystemdControlError(
                f"Failed to start {self.unit}: {result.stderr.strip()}"
            )

    def stop(self) -> None:
        result = self._run("stop", self.unit)
        if result.returncode:
            raise SystemdControlError(
                f"Failed to stop {self.unit}: {result.stderr.strip()}"
            )


def session_window(day: date) -> SessionWindow:
    session = market_session(day)
    return SessionWindow(
        session=session,
        configured_start=session.regular_open - START_OFFSET,
        configured_stop=session.regular_close + STOP_OFFSET,
    )


def _normalize_moment(moment: datetime | None) -> datetime:
    value = moment or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Supervisor time must be timezone-aware; failing closed.")
    return value.astimezone(NEW_YORK)


def schedule_decision(moment: datetime | None = None) -> ScheduleDecision:
    market_now = _normalize_moment(moment)
    today = market_now.date()
    evaluated_at_utc = market_now.astimezone(timezone.utc)
    if is_market_session(today):
        window = session_window(today)
        if market_now < window.configured_start:
            return ScheduleDecision(
                evaluated_at_utc, market_now, "TRADING_DAY_BEFORE_START",
                window, False, "START_CLEAN_V2", window.configured_start,
            )
        if market_now < window.session.regular_open:
            return ScheduleDecision(
                evaluated_at_utc, market_now, "PRE_OPEN_START_BUFFER",
                window, True, "STOP_CLEAN_V2", window.configured_stop,
            )
        if market_now < window.session.regular_close:
            return ScheduleDecision(
                evaluated_at_utc, market_now, "REGULAR_SESSION",
                window, True, "STOP_CLEAN_V2", window.configured_stop,
            )
        if market_now < window.configured_stop:
            return ScheduleDecision(
                evaluated_at_utc, market_now, "POST_CLOSE_STOP_BUFFER",
                window, True, "STOP_CLEAN_V2", window.configured_stop,
            )
        next_window = session_window(next_market_session(today))
        return ScheduleDecision(
            evaluated_at_utc, market_now, "TRADING_DAY_AFTER_STOP",
            window, False, "START_CLEAN_V2", next_window.configured_start,
        )
    next_window = session_window(next_market_session(today))
    return ScheduleDecision(
        evaluated_at_utc, market_now, "NON_TRADING_DAY",
        next_window, False, "START_CLEAN_V2", next_window.configured_start,
    )


def reconcile(
    controller: SystemdUserController,
    decision: ScheduleDecision,
) -> tuple[str, str | None]:
    state = controller.state()
    action: str | None = None
    if decision.desired_active:
        if state == "inactive":
            controller.start()
            action = "STARTED_CLEAN_V2"
            state = controller.state()
        elif state == "failed":
            action = "FAIL_CLOSED_CLEAN_V2_FAILED"
    elif state not in {"inactive", "failed"}:
        controller.stop()
        action = "STOPPED_CLEAN_V2"
        state = controller.state()
    return state, action


def status_payload(
    decision: ScheduleDecision,
    service_state: str,
) -> dict[str, Any]:
    next_action = decision.next_action
    next_action_at = decision.next_action_at
    if decision.desired_active and service_state == "inactive":
        next_action = "START_CLEAN_V2_IMMEDIATELY"
        next_action_at = decision.market_time
    elif not decision.desired_active and service_state not in {"inactive", "failed"}:
        next_action = "STOP_CLEAN_V2_IMMEDIATELY"
        next_action_at = decision.market_time
    session = decision.window.session
    return {
        "evaluated_at_utc": decision.evaluated_at_utc.isoformat(),
        "market_time": decision.market_time.isoformat(),
        "market_timezone": "America/New_York",
        "market_session_state": decision.market_session_state,
        "reference_trading_date": session.trading_date.isoformat(),
        "early_close": session.early_close,
        "regular_open": session.regular_open.isoformat(),
        "regular_close": session.regular_close.isoformat(),
        "configured_start": decision.window.configured_start.isoformat(),
        "configured_stop": decision.window.configured_stop.isoformat(),
        "clean_v2_unit": TARGET_UNIT,
        "clean_v2_service_state": service_state,
        "desired_service_state": "active" if decision.desired_active else "inactive",
        "next_scheduled_action": next_action,
        "next_action_at": next_action_at.isoformat(),
    }


def _seconds_until(moment: datetime, now: datetime) -> float:
    return max(0.0, (
        moment.astimezone(timezone.utc) - now.astimezone(timezone.utc)
    ).total_seconds())


def supervisor_sleep_seconds(decision: ScheduleDecision) -> float:
    until_action = _seconds_until(decision.next_action_at, decision.market_time)
    ceiling = (
        ACTIVE_RECONCILE_SECONDS
        if decision.desired_active
        else MAX_IDLE_SLEEP_SECONDS
    )
    return max(1.0, min(float(ceiling), until_action or 1.0))


def _log(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")), flush=True)


def run_supervisor(
    controller: SystemdUserController,
    *,
    stop_requested: threading.Event | None = None,
) -> None:
    stopping = stop_requested or threading.Event()
    previous_handlers: dict[int, Any] = {}

    def request_stop(_signum, _frame) -> None:
        stopping.set()

    for signum in (signal.SIGTERM, signal.SIGINT):
        previous_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, request_stop)
    last_error: str | None = None
    try:
        while not stopping.is_set():
            try:
                decision = schedule_decision()
                service_state, action = reconcile(controller, decision)
                if action:
                    _log({
                        "supervisor_action": action,
                        **status_payload(decision, service_state),
                    })
                last_error = None
                stopping.wait(supervisor_sleep_seconds(decision))
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                try:
                    state = controller.state()
                    if state not in {"inactive", "failed"}:
                        controller.stop()
                except Exception as stop_exc:
                    error += f"; fail_closed_stop={type(stop_exc).__name__}: {stop_exc}"
                if error != last_error:
                    _log({
                        "supervisor_state": "FAIL_CLOSED",
                        "error": error,
                        "retry_seconds": ERROR_RETRY_SECONDS,
                        "target_unit": TARGET_UNIT,
                    })
                    last_error = error
                stopping.wait(ERROR_RETRY_SECONDS)
    finally:
        try:
            state = controller.state()
            if state not in {"inactive", "failed"}:
                controller.stop()
        finally:
            for signum, handler in previous_handlers.items():
                signal.signal(signum, handler)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Market-aware lifecycle control for the Clean-V2 IEX paper runner."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--daemon", action="store_true")
    mode.add_argument("--status", action="store_true")
    args = parser.parse_args(argv)
    controller = SystemdUserController()
    if args.status:
        decision = schedule_decision()
        print(json.dumps(
            status_payload(decision, controller.state()),
            indent=2,
            sort_keys=True,
        ))
        return 0
    run_supervisor(controller)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
