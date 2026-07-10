"""Tests for the dive table model (the Qt adapter for the list view).

The model layer is pure-Python-friendly through `load_rows()` — no
QApplication is needed. The full Qt model (`DiveTableModel.data()`)
is exercised by the in-process Qt tests under tests/test_sites.py
and the subprocess tests elsewhere.
"""
from __future__ import annotations

import pytest

from open_dive_log.repositories import dives
from open_dive_log.ui.dive_table_model import (
    COL_DIVE_NUM,
    DiveRow,
    load_rows,
)


def test_dive_row_carries_both_id_and_display_dive_number(
    fresh_db,
) -> None:
    """`DiveRow` exposes both the stable PK and the chronological
    display number. The model is the boundary between the data
    layer (which knows the SQL window function) and the UI (which
    only knows the model)."""
    d1 = dives.create(fresh_db, dive_date="2024-06-15")
    d2 = dives.create(fresh_db, dive_date="2026-06-15")
    d3 = dives.create(fresh_db, dive_date="2000-06-15")

    rows = load_rows(fresh_db)
    by_id = {r.id: r for r in rows}

    # The display numbers are chronological, not insertion-order.
    assert by_id[d3].display_dive_number == 1   # 2000
    assert by_id[d1].display_dive_number == 2   # 2024
    assert by_id[d2].display_dive_number == 3   # 2026

    # The internal id is still the autoincrement PK.
    assert by_id[d1].id == d1
    assert by_id[d2].id == d2
    assert by_id[d3].id == d3


def test_load_rows_returns_dive_row_with_all_fields(fresh_db) -> None:
    """Smoke test: every field on DiveRow gets populated."""
    dives.create(
        fresh_db,
        dive_date="2026-06-15",
        start_time="14:30",
        dive_time_minutes=45,
        max_depth_m=24.0,
        avg_depth_m=18.0,
        air_temp_c=28.0,
        water_temp_c=26.0,
        visibility_m=20.0,
        start_pressure_bar=200.0,
        end_pressure_bar=80.0,
    )
    [row] = load_rows(fresh_db)
    assert isinstance(row, DiveRow)
    assert row.id > 0
    assert row.display_dive_number == 1
    assert row.dive_date == "2026-06-15"
    assert row.bottom_time_min == 45
    assert row.max_depth_m == 24.0
    assert row.avg_depth_m == 18.0
    assert row.air_temp_c == 28.0
    assert row.water_temp_c == 26.0
    assert row.visibility_m == 20.0
    assert row.start_pressure_bar == 200.0
    assert row.end_pressure_bar == 80.0
    assert row.sites == ""  # no sites attached


def test_dive_num_column_index_is_zero() -> None:
    """The Dive # column is the first column by contract; the
    UI relies on this. If someone reorders the columns, the
    display logic in `data()` (which uses the constant) will
    keep working, but the visible order will change. Pin the
    position here so the change is intentional.
    """
    assert COL_DIVE_NUM == 0
