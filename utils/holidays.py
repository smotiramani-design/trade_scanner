"""
utils/holidays.py — US market holiday calendar.

NYSE observes the following holidays each year:
  New Year's Day, MLK Day, Presidents' Day, Good Friday,
  Memorial Day, Juneteenth, Independence Day, Labor Day,
  Thanksgiving Day, Christmas Day.

When a holiday falls on Saturday, NYSE closes the preceding Friday.
When it falls on Sunday, NYSE closes the following Monday.

Usage:
    from utils.holidays import is_market_holiday
    if is_market_holiday():
        sys.exit("Market closed — holiday")
"""
from datetime import date, timedelta
from typing import Set
import logging

log = logging.getLogger(__name__)


def _easter(year: int) -> date:
    """Compute Easter Sunday using the Anonymous Gregorian algorithm."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _good_friday(year: int) -> date:
    return _easter(year) - timedelta(days=2)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """Return the nth occurrence of weekday (0=Mon) in given month/year."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + (n - 1) * 7)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    """Return the last occurrence of weekday in given month/year."""
    # Go to end of month, walk back
    if month == 12:
        last = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    offset = (last.weekday() - weekday) % 7
    return last - timedelta(days=offset)


def _observed(d: date) -> date:
    """
    NYSE holiday observance rule:
      Saturday holiday → observed Friday
      Sunday holiday   → observed Monday
    """
    if d.weekday() == 5:   # Saturday
        return d - timedelta(days=1)
    if d.weekday() == 6:   # Sunday
        return d + timedelta(days=1)
    return d


def nyse_holidays(year: int) -> Set[date]:
    """Return the set of NYSE market holidays for a given year."""
    holidays = set()

    def add(d: date) -> None:
        holidays.add(_observed(d))

    # Fixed-date holidays
    add(date(year, 1, 1))   # New Year's Day
    add(date(year, 6, 19))  # Juneteenth National Independence Day (since 2022)
    add(date(year, 7, 4))   # Independence Day
    add(date(year, 12, 25)) # Christmas Day

    # Floating holidays
    add(_nth_weekday(year, 1, 0, 3))   # MLK Day (3rd Monday of January)
    add(_nth_weekday(year, 2, 0, 3))   # Presidents' Day (3rd Monday of February)
    add(_good_friday(year))             # Good Friday
    add(_last_weekday(year, 5, 0))      # Memorial Day (last Monday of May)
    add(_nth_weekday(year, 9, 0, 1))   # Labor Day (1st Monday of September)
    add(_nth_weekday(year, 11, 3, 4))  # Thanksgiving (4th Thursday of November)

    return holidays


_CACHE: dict = {}   # {year: Set[date]}


def is_market_holiday(check_date: date = None) -> bool:
    """
    Return True if the given date (default: today) is a NYSE market holiday.
    Results are cached per year so subsequent calls in the same process are instant.
    """
    d = check_date or date.today()
    year = d.year
    if year not in _CACHE:
        _CACHE[year] = nyse_holidays(year)
        log.debug("Loaded %d NYSE holidays for %d", len(_CACHE[year]), year)
    result = d in _CACHE[year]
    if result:
        log.info("Today (%s) is a NYSE market holiday — scan skipped", d.isoformat())
    return result


def get_holidays_this_year() -> Set[date]:
    """Return all NYSE holidays for the current year."""
    return nyse_holidays(date.today().year)


if __name__ == "__main__":
    from datetime import date
    year = date.today().year
    print(f"\nNYSE holidays for {year}:")
    for h in sorted(nyse_holidays(year)):
        print(f"  {h.strftime('%a %b %d, %Y')}")
    print(f"\nToday is {'a holiday' if is_market_holiday() else 'a trading day'}.")
