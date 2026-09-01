"""Dependency-free United States equity-market session calendar."""

from __future__ import annotations

from datetime import (
    date,
    datetime,
    time,
    timedelta,
    tzinfo,
)
from dataclasses import dataclass


ZERO = timedelta(0)
HOUR = timedelta(hours=1)


def _first_sunday_on_or_after(moment: datetime) -> datetime:
    days_to_go = 6 - moment.weekday()

    if days_to_go:
        moment += timedelta(days=days_to_go)

    return moment


def _us_dst_range(year: int) -> tuple[datetime, datetime]:
    """
    Return United States daylight-saving boundaries.

    The current federal rules, in effect since 2007, start daylight
    time on the second Sunday in March and end it on the first Sunday
    in November. QPX only operates on contemporary market dates.
    """
    march_template = datetime(year, 3, 8, 2)
    november_template = datetime(year, 11, 1, 2)

    return (
        _first_sunday_on_or_after(march_template),
        _first_sunday_on_or_after(november_template),
    )


class EasternMarketTime(tzinfo):
    """
    America/New_York without depending on an installed tzdata package.

    This follows the post-2007 United States daylight-saving rules and
    implements fold-aware UTC conversion for the repeated autumn hour.
    """

    standard_offset = timedelta(hours=-5)

    def tzname(self, moment: datetime | None) -> str:
        return "EDT" if self.dst(moment) else "EST"

    def utcoffset(
        self,
        moment: datetime | None,
    ) -> timedelta:
        return self.standard_offset + self.dst(moment)

    def dst(
        self,
        moment: datetime | None,
    ) -> timedelta:
        if moment is None or moment.tzinfo is None:
            return ZERO

        start, end = _us_dst_range(moment.year)
        start = start.replace(tzinfo=self)
        end = end.replace(tzinfo=self)

        if start + HOUR <= moment < end - HOUR:
            return HOUR

        if end - HOUR <= moment < end:
            return ZERO if moment.fold else HOUR

        if start <= moment < start + HOUR:
            return HOUR if moment.fold else ZERO

        return ZERO

    def fromutc(self, moment: datetime) -> datetime:
        if moment.tzinfo is not self:
            raise ValueError(
                "fromutc requires a datetime using this timezone."
            )

        start, end = _us_dst_range(moment.year)
        start = start.replace(tzinfo=self)
        end = end.replace(tzinfo=self)
        standard_time = moment + self.standard_offset
        daylight_time = standard_time + HOUR

        if end <= daylight_time < end + HOUR:
            return standard_time.replace(fold=1)

        if standard_time < start or daylight_time >= end:
            return standard_time

        if start <= standard_time < end - HOUR:
            return daylight_time

        return standard_time


NEW_YORK = EasternMarketTime()
DEFAULT_READY_TIME = time(17, 15)
REGULAR_SESSION_OPEN = time(9, 30)
REGULAR_SESSION_CLOSE = time(16, 0)
EARLY_SESSION_CLOSE = time(13, 0)


@dataclass(frozen=True, slots=True)
class MarketSession:
    trading_date: date
    regular_open: datetime
    regular_close: datetime
    early_close: bool


def _observed(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)

    if day.weekday() == 6:
        return day + timedelta(days=1)

    return day


def _nth_weekday(
    year: int,
    month: int,
    weekday: int,
    occurrence: int,
) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7

    return first + timedelta(
        days=offset + ((occurrence - 1) * 7)
    )


def _last_weekday(
    year: int,
    month: int,
    weekday: int,
) -> date:
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)

    current = next_month - timedelta(days=1)

    while current.weekday() != weekday:
        current -= timedelta(days=1)

    return current


def _easter_sunday(year: int) -> date:
    """Gregorian computus."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (
        (19 * a)
        + b
        - d
        - g
        + 15
    ) % 30
    i = c // 4
    k = c % 4
    l = (
        32
        + (2 * e)
        + (2 * i)
        - h
        - k
    ) % 7
    m = (a + (11 * h) + (22 * l)) // 451
    month = (h + l - (7 * m) + 114) // 31
    day = (
        (h + l - (7 * m) + 114) % 31
    ) + 1

    return date(year, month, day)


def market_holidays(year: int) -> frozenset[date]:
    holidays = {
        _observed(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _easter_sunday(year) - timedelta(days=2),
        _last_weekday(year, 5, 0),
        _observed(date(year, 6, 19)),
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        _observed(date(year, 12, 25)),
    }

    next_new_year = _observed(date(year + 1, 1, 1))

    if next_new_year.year == year:
        holidays.add(next_new_year)

    return frozenset(holidays)


def is_market_session(day: date) -> bool:
    return (
        day.weekday() < 5
        and day not in market_holidays(day.year)
    )


def previous_market_session(
    day: date,
    *,
    include_day: bool = False,
) -> date:
    current = (
        day
        if include_day
        else day - timedelta(days=1)
    )

    while not is_market_session(current):
        current -= timedelta(days=1)

    return current



def next_market_session(
    day: date,
    *,
    include_day: bool = False,
) -> date:
    current = (
        day
        if include_day
        else day + timedelta(days=1)
    )

    while not is_market_session(current):
        current += timedelta(days=1)

    return current


def _thanksgiving_day(year: int) -> date:
    return _nth_weekday(year, 11, 3, 4)


def is_early_close_session(day: date) -> bool:
    """Return the established QPX/NYSE standard early-close classification."""
    if not is_market_session(day):
        return False
    return (
        day == _thanksgiving_day(day.year) + timedelta(days=1)
        or (day.month, day.day) == (7, 3)
        or (day.month, day.day) == (12, 24)
    )


def market_session(day: date) -> MarketSession:
    """Return fail-closed, timezone-aware regular-session endpoints."""
    if not is_market_session(day):
        raise ValueError(f"Not a QPX market session: {day.isoformat()}")
    early_close = is_early_close_session(day)
    close = EARLY_SESSION_CLOSE if early_close else REGULAR_SESSION_CLOSE
    return MarketSession(
        trading_date=day,
        regular_open=datetime.combine(day, REGULAR_SESSION_OPEN, tzinfo=NEW_YORK),
        regular_close=datetime.combine(day, close, tzinfo=NEW_YORK),
        early_close=early_close,
    )


def latest_completed_session(
    current: datetime | None = None,
    *,
    ready_time: time = DEFAULT_READY_TIME,
) -> tuple[date, str]:
    """
    Return the newest session expected to have stable daily data.

    The runner waits until 17:15 New York time, providing a buffer
    after the regular close before requiring the current daily bar.
    """
    moment = current or datetime.now(tz=NEW_YORK)

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=NEW_YORK)
    else:
        moment = moment.astimezone(NEW_YORK)

    today = moment.date()
    wall_clock = moment.time().replace(tzinfo=None)

    if is_market_session(today):
        if wall_clock >= ready_time:
            return today, "SESSION_READY"

        return (
            previous_market_session(today),
            "WAITING_FOR_MARKET_DATA",
        )

    return (
        previous_market_session(today),
        "NON_SESSION_DAY",
    )
