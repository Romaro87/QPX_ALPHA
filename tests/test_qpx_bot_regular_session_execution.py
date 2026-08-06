import json
from datetime import date, datetime, time, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from qpx_bot.market_calendar import (
    NEW_YORK,
    next_market_session,
)
from qpx_bot.paper_state import (
    PaperState,
    PendingEntry,
    StateStore,
)
from qpx_bot.schedule import (
    build_qpx_cron_block,
)
from qpx_bot.session_execution import (
    OpeningQuote,
    SessionExecutionConfig,
    execute_regular_session,
    session_phase,
)


config = SessionExecutionConfig(
    schema_version=1,
    market_timezone="America/New_York",
    regular_session_open="09:30",
    opening_window_start="09:35",
    opening_window_end="10:30",
    regular_session_close="16:00",
    intraday_interval="1m",
    intraday_range="1d",
    maximum_gap_atr_multiple=1.5,
    maximum_quote_attempts=1,
    quote_timeout_seconds=1.0,
    extended_hours_enabled=False,
)
config.validate()

assert next_market_session(
    date(2026, 8, 6)
) == date(2026, 8, 7)

opening_time = datetime(
    2026,
    8,
    7,
    9,
    45,
    tzinfo=NEW_YORK,
)
assert (
    session_phase(
        opening_time,
        config,
    )
    == "OPENING_WINDOW"
)
assert (
    session_phase(
        datetime(
            2026,
            8,
            7,
            8,
            0,
            tzinfo=NEW_YORK,
        ),
        config,
    )
    == "PRE_MARKET"
)
assert (
    session_phase(
        datetime(
            2026,
            8,
            7,
            17,
            0,
            tzinfo=NEW_YORK,
        ),
        config,
    )
    == "AFTER_HOURS"
)

with TemporaryDirectory() as temporary_directory:
    root = Path(temporary_directory)
    paper_runtime = (
        root / "paper_runtime"
    )
    input_directory = (
        root / "data_inputs"
    )
    report_directory = (
        root / "reports"
    )
    input_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    (input_directory / "SWING.csv").write_text(
        (
            "Date,Open,High,Low,Close,Volume\n"
            "2026-08-06,100,101,99,100,3000000\n"
        ),
        encoding="utf-8",
    )
    (input_directory / "QDTE.csv").write_text(
        (
            "Date,Open,High,Low,Close,Volume\n"
            "2026-08-06,40,41,39,40,1500000\n"
        ),
        encoding="utf-8",
    )

    store = StateStore(paper_runtime)
    state = PaperState(
        state_id="regular-session-test",
        swing_symbol="XLK",
        income_symbol="QDTE",
        start_date=date(2026, 8, 1),
        starting_cash=10_000.0,
        swing_cash=6_000.0,
        tax_reserve_cash=0.0,
        total_contributions=10_000.0,
        realized_pnl=0.0,
        income_shares=100.0,
        income_cost=4_000.0,
        dividends_received=0.0,
        last_processed_date=date(2026, 8, 6),
        pending_entry=PendingEntry(
            order_id="entry-test-1",
            symbol="XLK",
            signal_date=date(2026, 8, 6),
            signal_atr=2.0,
        ),
        revision=2,
    )
    store.save(state)

    def quote_provider(
        symbol,
        current,
        execution_config,
    ):
        return OpeningQuote(
            symbol=symbol,
            session_date=date(2026, 8, 7),
            bar_time_market=datetime.combine(
                date(2026, 8, 7),
                time(9, 30),
                tzinfo=NEW_YORK,
            ),
            observed_at_utc=datetime.now(
                timezone.utc
            ).isoformat(),
            open_price=101.0,
            source="TEST_REGULAR_SESSION",
            extended_hours=False,
        )

    code, report = execute_regular_session(
        config=config,
        paper_runtime=paper_runtime,
        input_directory=input_directory,
        report_directory=report_directory,
        current=opening_time,
        quote_provider=quote_provider,
    )
    assert code == 0
    assert report.status == "FILLED"
    assert report.extended_hours is False
    assert report.market_phase == "OPENING_WINDOW"

    reloaded = store.load()
    assert reloaded.pending_entry is None
    assert reloaded.position is not None
    assert reloaded.position.entry_date == date(
        2026,
        8,
        7,
    )
    event_ids, _, records = (
        store.verify_journal()
    )
    assert records == 1
    assert event_ids

    payload = json.loads(
        (
            report_directory
            / "latest_session_execution.json"
        ).read_text(encoding="utf-8")
    )
    assert payload["extended_hours"] is False
    assert (
        payload["mode"]
        == "SIMULATED_REGULAR_SESSION_ONLY"
    )

    code, check = execute_regular_session(
        config=config,
        paper_runtime=paper_runtime,
        input_directory=input_directory,
        report_directory=report_directory,
        current=opening_time,
        check_only=True,
        quote_provider=quote_provider,
    )
    assert code == 0
    assert check.status == "CHECK_ONLY"

    analysis_script = (
        root / "QPX_TERMUX_DAILY.sh"
    )
    analysis_script.write_text(
        "#!/bin/sh\n",
        encoding="utf-8",
    )
    session_script = (
        root / "QPX_TERMUX_SESSION.sh"
    )
    session_script.write_text(
        "#!/bin/sh\n",
        encoding="utf-8",
    )
    block = build_qpx_cron_block(
        analysis_script,
        home=root,
        prefix=root / "usr",
    )
    assert "QPX_TERMUX_SESSION.sh" in block
    assert "*/15 6-12 * * 1-5" in block
    assert "15 16-23 * * 1-5" in block

print(
    "QPX Bot Regular-Session Execution PASS"
)
