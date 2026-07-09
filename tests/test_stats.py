"""Tests for the Stats screen (compute_stats + StatsWindow)."""

from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

from open_dive_log.db import apply_migrations, connect
from open_dive_log.repositories import dives
from open_dive_log.repositories.dives import DiveStats, compute_stats
from open_dive_log.ui.stats_window import _fmt_total_minutes
from open_dive_log.units import UnitSystem


# --------------------------------------------------------------------- repo
@pytest.fixture
def conn() -> sqlite3.Connection:
    """A fresh DB with migrations applied, autocommit (matches prod)."""
    with tempfile.TemporaryDirectory() as d:
        cm = connect(os.path.join(d, "stats_test.db"))
        c = cm.__enter__()
        apply_migrations(c)
        try:
            yield c
        finally:
            cm.__exit__(None, None, None)


def test_compute_stats_empty_db(conn: sqlite3.Connection) -> None:
    s = compute_stats(conn)
    assert s.dive_count == 0
    assert s.dive_time_count == 0
    assert s.longest_minutes is None
    assert s.shortest_minutes is None
    assert s.average_minutes is None
    assert s.total_minutes is None
    assert s.deepest_m is None
    assert s.average_depth_m is None
    assert s.distinct_sites == 0
    assert s.distinct_countries == 0


def test_compute_stats_counts_dives_with_no_time(conn: sqlite3.Connection) -> None:
    """`dive_count` includes dives with no recorded time; the
    time aggregates only see dives that have one."""
    dives.create(conn, dive_date="2026-07-01", dive_time_minutes=45)
    dives.create(conn, dive_date="2026-07-02")  # no time
    s = compute_stats(conn)
    assert s.dive_count == 2
    assert s.dive_time_count == 1
    assert s.longest_minutes == 45
    assert s.shortest_minutes == 45
    assert s.average_minutes == 45.0
    assert s.total_minutes == 45


def test_compute_stats_aggregates_time_correctly(conn: sqlite3.Connection) -> None:
    """Three dives with times 45, 60, 30 → min=30, max=60, avg=45.0,
    total=135."""
    dives.create(conn, dive_date="2026-07-01", dive_time_minutes=45)
    dives.create(conn, dive_date="2026-07-02", dive_time_minutes=60)
    dives.create(conn, dive_date="2026-07-03", dive_time_minutes=30)
    s = compute_stats(conn)
    assert s.longest_minutes == 60
    assert s.shortest_minutes == 30
    assert s.average_minutes == pytest.approx(45.0)
    assert s.total_minutes == 135


def _stats_with_total(total: int | None) -> DiveStats:
    """Build a DiveStats with only total_minutes populated — the
    other fields are irrelevant to _fmt_total_minutes."""
    return DiveStats(
        dive_count=1,
        dive_time_count=1,
        longest_minutes=total,
        shortest_minutes=total,
        average_minutes=float(total) if total is not None else None,
        total_minutes=total,
        deepest_m=None,
        average_depth_m=None,
        distinct_sites=0,
        distinct_countries=0,
    )


def test_fmt_total_minutes_under_60() -> None:
    """Under 60 minutes — show as plain minutes, the common case
    for a new diver with only a handful of dives."""
    assert _fmt_total_minutes(_stats_with_total(0), UnitSystem.METRIC) == "0 min"
    assert _fmt_total_minutes(_stats_with_total(1), UnitSystem.METRIC) == "1 min"
    assert _fmt_total_minutes(_stats_with_total(45), UnitSystem.METRIC) == "45 min"
    assert _fmt_total_minutes(_stats_with_total(59), UnitSystem.METRIC) == "59 min"


def test_fmt_total_minutes_60_to_119() -> None:
    """At 60 minutes the format flips to hours. 60 = "1 hr" (no
    trailing "0 min"). 90 = "1 hr 30 min"."""
    assert _fmt_total_minutes(_stats_with_total(60), UnitSystem.METRIC) == "1 hr"
    assert _fmt_total_minutes(_stats_with_total(75), UnitSystem.METRIC) == "1 hr 15 min"
    assert _fmt_total_minutes(_stats_with_total(90), UnitSystem.METRIC) == "1 hr 30 min"
    assert _fmt_total_minutes(_stats_with_total(119), UnitSystem.METRIC) == "1 hr 59 min"


def test_fmt_total_minutes_multi_hour() -> None:
    """Multiple hours: 120 = "2 hr", 135 = "2 hr 15 min", 1500 = "25 hr"."""
    assert _fmt_total_minutes(_stats_with_total(120), UnitSystem.METRIC) == "2 hr"
    assert _fmt_total_minutes(_stats_with_total(135), UnitSystem.METRIC) == "2 hr 15 min"
    assert _fmt_total_minutes(_stats_with_total(720), UnitSystem.METRIC) == "12 hr"
    assert _fmt_total_minutes(_stats_with_total(1500), UnitSystem.METRIC) == "25 hr"


def test_fmt_total_minutes_large_uses_thousands_separator() -> None:
    """For a heavy diver with thousands of minutes, the thousands
    separator should be applied to the hours portion."""
    # 10,000 minutes = 166 hr 40 min
    s = _stats_with_total(10_000)
    assert _fmt_total_minutes(s, UnitSystem.METRIC) == "166 hr 40 min"
    # Exact-hour case at large scale
    s = _stats_with_total(60 * 1000)
    assert _fmt_total_minutes(s, UnitSystem.METRIC) == "1,000 hr"


def test_fmt_total_minutes_none() -> None:
    """None total (no dives with time) → None display."""
    assert _fmt_total_minutes(_stats_with_total(None), UnitSystem.METRIC) is None


def test_compute_stats_aggregates_depth_correctly(conn: sqlite3.Connection) -> None:
    """Three dives with max_depth 18, 30, 12 → deepest=30, avg=20.0."""
    dives.create(conn, dive_date="2026-07-01", max_depth_m=18.0)
    dives.create(conn, dive_date="2026-07-02", max_depth_m=30.0)
    dives.create(conn, dive_date="2026-07-03", max_depth_m=12.0)
    s = compute_stats(conn)
    assert s.deepest_m == pytest.approx(30.0)
    assert s.average_depth_m == pytest.approx(20.0)


def test_compute_stats_ignores_null_depths(conn: sqlite3.Connection) -> None:
    """A dive with no max_depth shouldn't break the depth aggregates."""
    dives.create(conn, dive_date="2026-07-01", max_depth_m=20.0)
    dives.create(conn, dive_date="2026-07-02", max_depth_m=30.0)
    dives.create(conn, dive_date="2026-07-03")  # no max_depth
    s = compute_stats(conn)
    assert s.deepest_m == pytest.approx(30.0)
    assert s.average_depth_m == pytest.approx(25.0)
    assert s.dive_count == 3


def test_compute_stats_counts_distinct_sites(conn: sqlite3.Connection) -> None:
    """3 dives to 2 distinct sites."""
    from open_dive_log.repositories import sites as sites_repo

    # Country row required for site FK
    conn.execute(
        "INSERT OR IGNORE INTO country (code, name) VALUES (?, ?)",
        ("BQ", "Bonaire"),
    )

    s1 = sites_repo.find_or_create(conn, "Salt Pier", country_code="BQ")
    s2 = sites_repo.find_or_create(conn, "1000 Steps", country_code="BQ")

    d1 = dives.create(conn, dive_date="2026-07-01")
    dives.attach_sites(conn, d1, [s1.id])
    d2 = dives.create(conn, dive_date="2026-07-02")
    dives.attach_sites(conn, d2, [s2.id])
    d3 = dives.create(conn, dive_date="2026-07-03")
    dives.attach_sites(conn, d3, [s1.id])  # repeat

    s = compute_stats(conn)
    assert s.distinct_sites == 2
    assert s.distinct_countries == 1


def test_compute_stats_counts_distinct_countries(conn: sqlite3.Connection) -> None:
    """Dives to 2 countries → 2 distinct countries."""
    from open_dive_log.repositories import sites as sites_repo

    conn.execute(
        "INSERT OR IGNORE INTO country (code, name) VALUES (?, ?)",
        ("BQ", "Bonaire"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO country (code, name) VALUES (?, ?)",
        ("MX", "Mexico"),
    )
    s1 = sites_repo.find_or_create(conn, "Salt Pier", country_code="BQ")
    s2 = sites_repo.find_or_create(conn, "Cenote", country_code="MX")

    d1 = dives.create(conn, dive_date="2026-07-01")
    dives.attach_sites(conn, d1, [s1.id])
    d2 = dives.create(conn, dive_date="2026-07-02")
    dives.attach_sites(conn, d2, [s2.id])

    s = compute_stats(conn)
    assert s.distinct_sites == 2
    assert s.distinct_countries == 2


def test_compute_stats_dive_with_no_sites_zero_sites_and_countries(
    conn: sqlite3.Connection,
) -> None:
    """A dive with no sites → 0 distinct sites/countries. Sanity
    check the SQL doesn't blow up on empty join."""
    dives.create(conn, dive_date="2026-07-01")
    s = compute_stats(conn)
    assert s.distinct_sites == 0
    assert s.distinct_countries == 0


# ----------------------------------------------------------------- window
def _subprocess_test(source: str, timeout: int = 30) -> "subprocess.CompletedProcess[str]":  # type: ignore[name-defined]
    """Run a Qt test source in a subprocess.

    The source should print "OK: ..." to indicate success. If the
    first line is "SKIP:" we treat the test as skipped. Otherwise
    non-zero exit or uncaught exception is a failure.
    """
    import subprocess
    import textwrap

    bootstrap = (
        "import os, sys\n"
        "os.environ.setdefault('QT_QPA_PLATFORM', 'cocoa')\n"
        "os.environ.setdefault('PYTHONPATH', 'src')\n"
    )
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    full = bootstrap + textwrap.dedent(source)
    return subprocess.run(
        [".venv/bin/python", "-c", full],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        timeout=timeout,
    )


def test_stats_window_constructs_empty_db() -> None:
    """A fresh DB with no dives produces an empty stats screen."""
    src = """
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    import os, tempfile
    from open_dive_log.db import connect, apply_migrations
    from open_dive_log.ui.stats_window import StatsWindow
    from open_dive_log.units import UnitSystem

    with tempfile.TemporaryDirectory() as d:
        cm = connect(os.path.join(d, "stats_empty.db"))
        c = cm.__enter__()
        apply_migrations(c)
        try:
            win = StatsWindow(c, unit_system=UnitSystem.METRIC)
            assert win.windowTitle().startswith("Stats")
            # Counts (Number of dives, Sites, Countries) are always
            # known: 0 in an empty DB.
            assert win._time_pairs[0][1].text() == "0"     # Number of dives
            assert win._place_pairs[0][1].text() == "0"    # Sites
            assert win._place_pairs[1][1].text() == "0"    # Countries
            # Aggregates (longest, shortest, average, total,
            # deepest, average depth) have no data → "—".
            time_aggregates = [val for _lbl, val in win._time_pairs[1:]]
            depth_aggregates = [val for _lbl, val in win._depth_pairs]
            assert all(t.text() == "—" for t in time_aggregates), (
                f"time_aggregates: {[t.text() for t in time_aggregates]}"
            )
            assert all(t.text() == "—" for t in depth_aggregates), (
                f"depth_aggregates: {[t.text() for t in depth_aggregates]}"
            )
            win.close()
        finally:
            cm.__exit__(None, None, None)
    print("OK: empty stats window shows 0 for counts and — for aggregates")
    """
    result = _subprocess_test(src)
    if result.stdout.startswith("SKIP:"):
        pytest.skip(result.stdout.strip())
    assert result.returncode == 0, (
        f"Subprocess failed (rc={result.returncode}):\n"
        f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    )
    assert "OK: empty stats window shows 0 for counts" in result.stdout


def test_stats_window_shows_populated_values() -> None:
    """After inserting 3 dives, the stats window should show the
    expected aggregates."""
    src = """
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    import os, tempfile
    from open_dive_log.db import connect, apply_migrations
    from open_dive_log.repositories import dives
    from open_dive_log.ui.stats_window import StatsWindow
    from open_dive_log.units import UnitSystem

    with tempfile.TemporaryDirectory() as d:
        cm = connect(os.path.join(d, "stats_pop.db"))
        c = cm.__enter__()
        apply_migrations(c)
        dives.create(c, dive_date="2026-07-01", dive_time_minutes=45, max_depth_m=18.0)
        dives.create(c, dive_date="2026-07-02", dive_time_minutes=60, max_depth_m=30.0)
        dives.create(c, dive_date="2026-07-03", dive_time_minutes=30, max_depth_m=12.0)
        try:
            win = StatsWindow(c, unit_system=UnitSystem.METRIC)
            # time_pairs: Number of dives, Longest, Shortest, Average, Total
            assert win._time_pairs[0][1].text() == "3", f"count {win._time_pairs[0][1].text()!r}"
            assert win._time_pairs[1][1].text() == "60 min"
            assert win._time_pairs[2][1].text() == "30 min"
            assert win._time_pairs[3][1].text() == "45.0 min"
            # 45 + 60 + 30 = 135 minutes → 2 hr 15 min (new format
            # kicks in at 60+ minutes, see _fmt_total_minutes)
            assert win._time_pairs[4][1].text() == "2 hr 15 min"
            # depth_pairs: Deepest, Average depth — metric
            assert win._depth_pairs[0][1].text() == "30 m"
            assert win._depth_pairs[1][1].text() == "20.0 m"
            # place_pairs: Sites, Countries (no sites attached here)
            assert win._place_pairs[0][1].text() == "0"
            assert win._place_pairs[1][1].text() == "0"
            win.close()
        finally:
            cm.__exit__(None, None, None)
    print("OK: stats window renders populated values")
    """
    result = _subprocess_test(src)
    if result.stdout.startswith("SKIP:"):
        pytest.skip(result.stdout.strip())
    assert result.returncode == 0, (
        f"Subprocess failed (rc={result.returncode}):\n"
        f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    )
    assert "OK: stats window renders populated values" in result.stdout


def test_stats_window_toggles_to_imperial() -> None:
    """set_unit_system(IMPERIAL) should convert depth values to feet
    and update the subtitle."""
    src = """
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    import os, tempfile
    from open_dive_log.db import connect, apply_migrations
    from open_dive_log.repositories import dives
    from open_dive_log.ui.stats_window import StatsWindow
    from open_dive_log.units import UnitSystem

    with tempfile.TemporaryDirectory() as d:
        cm = connect(os.path.join(d, "stats_imp.db"))
        c = cm.__enter__()
        apply_migrations(c)
        # 30 m → ~98.4 ft
        dives.create(c, dive_date="2026-07-01", max_depth_m=30.0)
        try:
            win = StatsWindow(c, unit_system=UnitSystem.METRIC)
            assert win._depth_pairs[0][1].text() == "30 m"

            # Toggle to imperial
            win.set_unit_system(UnitSystem.IMPERIAL)
            # 30 m * 3.28084 = 98.4252 → "98.4 ft" (one decimal)
            assert win._depth_pairs[0][1].text() == "98.4 ft", f"got {win._depth_pairs[0][1].text()!r}"
            # Subtitle should mention ft
            assert "ft" in win._subtitle.text().lower()

            # Toggle back to metric
            win.set_unit_system(UnitSystem.METRIC)
            assert win._depth_pairs[0][1].text() == "30 m"
            win.close()
        finally:
            cm.__exit__(None, None, None)
    print("OK: stats window toggles metric/imperial")
    """
    result = _subprocess_test(src)
    if result.stdout.startswith("SKIP:"):
        pytest.skip(result.stdout.strip())
    assert result.returncode == 0, (
        f"Subprocess failed (rc={result.returncode}):\n"
        f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    )
    assert "OK: stats window toggles metric/imperial" in result.stdout


def test_stats_window_refresh_picks_up_new_dives() -> None:
    """Adding a dive after the window opens → refresh() shows the
    new aggregate. Verifies the live-update hook is wired."""
    src = """
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    import os, tempfile
    from open_dive_log.db import connect, apply_migrations
    from open_dive_log.repositories import dives
    from open_dive_log.ui.stats_window import StatsWindow
    from open_dive_log.units import UnitSystem

    with tempfile.TemporaryDirectory() as d:
        cm = connect(os.path.join(d, "stats_refresh.db"))
        c = cm.__enter__()
        apply_migrations(c)
        try:
            win = StatsWindow(c, unit_system=UnitSystem.METRIC)
            # Initial: 0 dives
            assert win._time_pairs[0][1].text() == "0"

            # Add a dive and refresh
            dives.create(c, dive_date="2026-07-01", dive_time_minutes=45)
            win.refresh()
            assert win._time_pairs[0][1].text() == "1"
            assert win._time_pairs[1][1].text() == "45 min"

            # Add another
            dives.create(c, dive_date="2026-07-02", dive_time_minutes=30)
            win.refresh()
            assert win._time_pairs[0][1].text() == "2"
            assert win._time_pairs[1][1].text() == "45 min"
            assert win._time_pairs[2][1].text() == "30 min"
            win.close()
        finally:
            cm.__exit__(None, None, None)
    print("OK: stats window refresh picks up new dives")
    """
    result = _subprocess_test(src)
    if result.stdout.startswith("SKIP:"):
        pytest.skip(result.stdout.strip())
    assert result.returncode == 0, (
        f"Subprocess failed (rc={result.returncode}):\n"
        f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    )
    assert "OK: stats window refresh picks up new dives" in result.stdout
