from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from qpx_bot.market_calendar import (
    NEW_YORK,
    is_market_session,
    latest_completed_session,
    market_holidays,
    previous_market_session,
)
from qpx_bot.operations import (
    OperationsState,
    load_operations_state,
    read_latest_csv_date,
    save_operations_state,
)
from qpx_bot.schedule import (
    CRON_BEGIN,
    CRON_END,
    build_qpx_cron_block,
    remove_qpx_cron_block,
)


assert not is_market_session(date(2026, 7, 3))
assert date(2026, 4, 3) in market_holidays(2026)
assert is_market_session(date(2026, 8, 6))
assert previous_market_session(
    date(2026, 7, 6)
) == date(2026, 7, 2)

before_close = datetime(
    2026,
    8,
    6,
    16,
    30,
    tzinfo=NEW_YORK,
)
session, status = latest_completed_session(before_close)
assert session == date(2026, 8, 5)
assert status == "WAITING_FOR_MARKET_DATA"

after_buffer = datetime(
    2026,
    8,
    6,
    17,
    16,
    tzinfo=NEW_YORK,
)
session, status = latest_completed_session(after_buffer)
assert session == date(2026, 8, 6)
assert status == "SESSION_READY"

winter_utc = datetime(
    2026,
    1,
    15,
    22,
    0,
    tzinfo=timezone.utc,
)
summer_utc = datetime(
    2026,
    7,
    15,
    21,
    0,
    tzinfo=timezone.utc,
)
assert winter_utc.astimezone(NEW_YORK).hour == 17
assert summer_utc.astimezone(NEW_YORK).hour == 17

with TemporaryDirectory() as temporary_directory:
    directory = Path(temporary_directory)
    state = OperationsState(
        last_successful_session="2026-08-05",
        consecutive_failures=2,
        paused=False,
        last_status="FAILED",
        last_message="test",
    )
    save_operations_state(directory, state)
    loaded = load_operations_state(directory)
    assert loaded.last_successful_session == "2026-08-05"
    assert loaded.consecutive_failures == 2

    csv_path = directory / "SWING.csv"
    csv_path.write_text(
        "Date,Open,High,Low,Close,Volume\n"
        "2026-08-04,1,2,0.5,1.5,100\n"
        "2026-08-06,1,2,0.5,1.5,100\n",
        encoding="utf-8",
    )
    assert read_latest_csv_date(csv_path) == date(2026, 8, 6)

    script = directory / "QPX_TERMUX_DAILY.sh"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    block = build_qpx_cron_block(
        script,
        home=directory,
        prefix=directory / "usr",
    )
    assert CRON_BEGIN in block
    assert CRON_END in block
    assert "15 16-23 * * 1-5" in block

    existing = (
        "5 1 * * * echo keep\n"
        + block
        + "\n10 2 * * * echo also-keep\n"
    )
    cleaned = remove_qpx_cron_block(existing)
    assert "echo keep" in cleaned
    assert "echo also-keep" in cleaned
    assert CRON_BEGIN not in cleaned

print("QPX Bot Automated Daily Operations PASS")
