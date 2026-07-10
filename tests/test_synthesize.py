from __future__ import annotations

import time
import pytest
from pathlib import Path

from open_dive_log import db
from open_dive_log.repositories import dives, sites
from open_dive_log.synthesize import generate_dives


def _seed_test_db(db_path: str | Path) -> None:
    """Create the minimal site fixture used by the synthesize tests."""
    with db.connect(db_path) as conn:
        db.apply_migrations(conn)
        sites.create(conn, name="Blue Hole", country_code="BS", latitude=24.0, longitude=-76.0)
        sites.create(conn, name="Manta Point", country_code="ID", latitude=-8.0, longitude=115.0)


def _load_dive_rows(db_path: str | Path) -> list[tuple[str, int | None, float | None]]:
    """Load generated dives through the repository."""
    with db.connect(db_path) as conn:
        dive_ids = [row.id for row in dives.list_recent(conn, limit=1000)]
        rows = [dives.get_full(conn, dive_id) for dive_id in dive_ids]
    return [
        (row.dive_date, row.dive_time_minutes, row.max_depth_m)
        for row in rows
        if row is not None
    ]


def test_generate_dives_creates_realistic_rows(tmp_path):
    """Synthetic dives should be created with realistic ranges and stored correctly."""
    db_path = tmp_path / "test.db"
    _seed_test_db(db_path)

    inserted = generate_dives(
        count=25,
        db_path=db_path,
        seed=42,
        site_ids=[1, 2],
        date_from="2020-01-01",
        date_to="2024-12-31",
        skip_confirmation=True
    )

    assert inserted == 25

    rows = _load_dive_rows(db_path)
    assert len(rows) == 25
    for dive_date, dive_time_minutes, max_depth_m in rows:
        assert 20 <= int(dive_time_minutes) <= 60
        assert 10.0 <= float(max_depth_m) <= 40.0
        assert "2020-01-01" <= dive_date <= "2024-12-31"


def test_generate_dives_completes_100_rows_under_five_seconds(tmp_path):
    """Generating 100 synthetic dives should stay comfortably under the target."""
    db_path = tmp_path / "perf.db"
    _seed_test_db(db_path)

    started = time.perf_counter()
    inserted = generate_dives(
        count=100,
        db_path=db_path,
        seed=7,
        site_ids=[1, 2],
        date_from="2020-01-01",
        date_to="2024-12-31",
        skip_confirmation=True
    )
    elapsed = time.perf_counter() - started

    assert inserted == 100
    assert elapsed < 5.0


def test_generate_dives_keeps_depth_values_within_expected_bounds(tmp_path):
    """Depth-related fields should stay within the intended realistic ranges."""
    db_path = tmp_path / "bounds.db"
    _seed_test_db(db_path)

    inserted = generate_dives(
        count=15,
        db_path=db_path,
        seed=99,
        site_ids=[1, 2],
        date_from="2020-01-01",
        date_to="2024-12-31",
        skip_confirmation=True
    )

    assert inserted == 15

    with db.connect(db_path) as conn:
        dive_ids = [row.id for row in dives.list_recent(conn, limit=1000)]
        rows = [dives.get_full(conn, dive_id) for dive_id in dive_ids]

    for row in rows:
        assert row is not None
        assert row.dive_time_minutes is not None
        assert row.max_depth_m is not None
        assert row.avg_depth_m is not None
        assert 20 <= row.dive_time_minutes <= 60
        assert 10.0 <= row.max_depth_m <= 40.0
        assert 8.0 <= row.avg_depth_m <= 32.0
        assert row.avg_depth_m <= row.max_depth_m


def test_generate_dives_is_reproducible_with_same_seed(tmp_path):
    """The same seed and input range should yield the same generated rows."""
    db_path_a = tmp_path / "a.db"
    db_path_b = tmp_path / "b.db"
    _seed_test_db(db_path_a)
    _seed_test_db(db_path_b)

    generate_dives(
        count=20,
        db_path=db_path_a,
        seed=123,
        site_ids=[1, 2],
        date_from="2020-01-01",
        date_to="2024-12-31",
        skip_confirmation=True
    )
    generate_dives(
        count=20,
        db_path=db_path_b,
        seed=123,
        site_ids=[1, 2],
        date_from="2020-01-01",
        date_to="2024-12-31",
        skip_confirmation=True
    )

    rows_a = _load_dive_rows(db_path_a)
    rows_b = _load_dive_rows(db_path_b)

    assert [tuple(row) for row in rows_a] == [tuple(row) for row in rows_b]


def test_generate_dives_refuses_empty_db_path(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_test_db(db_path)

    with pytest.raises(ValueError, match="DB path must be provided"):
        generate_dives(
            count=5,
            db_path=None,
            seed=42,
            site_ids=[1, 2],
            date_from="2020-01-01",
            date_to="2020-12-31",
            skip_confirmation=True,
        )


def test_generate_dives_refuses_non_empty_db_without_force(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_test_db(db_path)
    generate_dives(
        count=1,
        db_path=db_path,
        seed=1,
        site_ids=[1, 2],
        date_from="2020-01-01",
        date_to="2020-12-31",
        skip_confirmation=True,
    )

    with pytest.raises(ValueError, match="Dive table is not empty"):
        generate_dives(
            count=1,
            db_path=db_path,
            seed=2,
            site_ids=[1, 2],
            date_from="2020-01-01",
            date_to="2020-12-31",
            skip_confirmation=True,
        )
