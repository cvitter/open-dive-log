"""Tests for sites.list_for_map and the SiteMapPoint dataclass.

The site map (issue #7) is a parallel of the dive map (issue #25):
one marker per entity, filter-aware, click → dialog. This file
covers the *data* layer only — the window/UI is in
``test_site_map_window.py``.

Test setup note: the migration ``002_opendivemap.sql`` seeds all
eight ``lookup_site_environment`` rows, the three
``lookup_entry_type`` rows, and a long list of countries (US, BS,
MX, etc.). Tests use those pre-seeded ids directly instead of
re-inserting; the helpers below look them up.
"""

from __future__ import annotations

import sqlite3
import tempfile

import pytest

from open_dive_log import db
from open_dive_log.repositories import sites as sites_repo


@pytest.fixture
def conn() -> sqlite3.Connection:
    """Yield an empty, fully-migrated SQLite connection."""
    with tempfile.TemporaryDirectory() as d:
        cm = db.connect(f"{d}/map_data_test.db")
        c = cm.__enter__()
        db.apply_migrations(c)
        try:
            yield c
        finally:
            cm.__exit__(None, None, None)


def _env_id(conn: sqlite3.Connection, name: str) -> int:
    """Look up the pre-seeded ``lookup_site_environment.id``."""
    return conn.execute(
        "SELECT id FROM lookup_site_environment WHERE name = ?",
        (name,),
    ).fetchone()["id"]


def _entry_id(conn: sqlite3.Connection, name: str) -> int:
    """Look up the pre-seeded ``lookup_entry_type.id``."""
    return conn.execute(
        "SELECT id FROM lookup_entry_type WHERE name = ?",
        (name,),
    ).fetchone()["id"]


def _seed_site(
    conn: sqlite3.Connection,
    name: str,
    *,
    country_code: str | None = None,
    region: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    max_depth_m: float | None = None,
    environment_id: int | None = None,
    entry_id: int | None = None,
) -> int:
    return conn.execute(
        """
        INSERT INTO site (
            name, country_code, region, latitude, longitude,
            max_depth_m, environment_id, entry_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (name, country_code, region, latitude, longitude,
         max_depth_m, environment_id, entry_id),
    ).lastrowid


def test_list_for_map_returns_one_point_per_geo_site(conn):
    """A site with non-null lat/lon shows up; one without is excluded."""
    ocean = _env_id(conn, "ocean")
    lake = _env_id(conn, "lake")
    boat = _entry_id(conn, "boat")

    # 3 sites: 2 geo + 1 without lat/lon
    sid1 = _seed_site(conn, "Salt Pier",
                      country_code="US",
                      latitude=24.5, longitude=-81.5,
                      max_depth_m=18.0,
                      environment_id=ocean,
                      entry_id=boat)
    sid2 = _seed_site(conn, "Tiger Beach",
                      country_code="BS",
                      latitude=26.7, longitude=-77.3,
                      max_depth_m=25.0,
                      environment_id=ocean,
                      entry_id=boat)
    _seed_site(conn, "Generic Lake",
               country_code="US",
               latitude=None, longitude=None,
               max_depth_m=10.0,
               environment_id=lake,
               entry_id=boat)
    conn.commit()

    points = sites_repo.list_for_map(conn)
    ids = {p.id for p in points}
    assert ids == {sid1, sid2}, (
        f"expected only the 2 geo sites, got {ids}"
    )


def test_list_for_map_includes_environment(conn):
    """``environment_id`` and ``environment_name`` are populated."""
    ocean = _env_id(conn, "ocean")
    lake = _env_id(conn, "lake")
    _seed_site(conn, "Salt Pier",
               country_code="US",
               latitude=24.5, longitude=-81.5,
               environment_id=ocean)
    _seed_site(conn, "Hidden Lake",
               country_code="US",
               latitude=42.0, longitude=-83.0,
               environment_id=lake)
    conn.commit()

    points = sites_repo.list_for_map(conn)
    by_id = {p.id: p for p in points}
    assert by_id[1].environment_id == ocean
    assert by_id[1].environment_name == "ocean"
    assert by_id[2].environment_id == lake
    assert by_id[2].environment_name == "lake"


def test_list_for_map_filters_by_country_code(conn):
    """``country_code=`` keeps only sites in that country."""
    _seed_site(conn, "US Site 1",
               country_code="US",
               latitude=24.5, longitude=-81.5)
    _seed_site(conn, "US Site 2",
               country_code="US",
               latitude=42.0, longitude=-83.0)
    _seed_site(conn, "BS Site 1",
               country_code="BS",
               latitude=26.7, longitude=-77.3)
    conn.commit()

    us = sites_repo.list_for_map(conn, country_code="US")
    assert {p.id for p in us} == {1, 2}
    bs = sites_repo.list_for_map(conn, country_code="BS")
    assert {p.id for p in bs} == {3}


def test_list_for_map_filters_by_environment(conn):
    """``environment_id=`` keeps only sites with that environment."""
    ocean = _env_id(conn, "ocean")
    lake = _env_id(conn, "lake")
    _seed_site(conn, "Salt Pier",
               country_code="US",
               latitude=24.5, longitude=-81.5,
               environment_id=ocean)
    _seed_site(conn, "Hidden Lake",
               country_code="US",
               latitude=42.0, longitude=-83.0,
               environment_id=lake)
    _seed_site(conn, "Unset Env",
               country_code="US",
               latitude=35.0, longitude=-110.0,
               environment_id=None)
    conn.commit()

    ocean_points = sites_repo.list_for_map(conn, environment_id=ocean)
    assert {p.id for p in ocean_points} == {1}
    lake_points = sites_repo.list_for_map(conn, environment_id=lake)
    assert {p.id for p in lake_points} == {2}


def test_list_for_map_filters_by_region(conn):
    """``region=`` keeps only sites with that region (free-text)."""
    _seed_site(conn, "Florida 1",
               country_code="US", region="South Florida",
               latitude=24.5, longitude=-81.5)
    _seed_site(conn, "Florida 2",
               country_code="US", region="South Florida",
               latitude=25.5, longitude=-80.5)
    _seed_site(conn, "Hawaii 1",
               country_code="US", region="Big Island",
               latitude=19.5, longitude=-155.5)
    conn.commit()

    fla = sites_repo.list_for_map(conn, region="South Florida")
    assert {p.id for p in fla} == {1, 2}
    hi = sites_repo.list_for_map(conn, region="Big Island")
    assert {p.id for p in hi} == {3}


def test_list_for_map_filters_compose_with_and(conn):
    """All four filter dimensions compose with AND, not OR."""
    ocean = _env_id(conn, "ocean")
    lake = _env_id(conn, "lake")
    _seed_site(conn, "US Ocean 1",
               country_code="US", region="Florida",
               latitude=24.5, longitude=-81.5,
               environment_id=ocean)
    _seed_site(conn, "US Lake 1",
               country_code="US", region="Florida",
               latitude=27.0, longitude=-80.0,
               environment_id=lake)
    _seed_site(conn, "BS Ocean 1",
               country_code="BS", region="Bahamas",
               latitude=26.7, longitude=-77.3,
               environment_id=ocean)
    _seed_site(conn, "US Ocean 2",
               country_code="US", region="Hawaii",
               latitude=19.5, longitude=-155.5,
               environment_id=ocean)
    conn.commit()

    pts = sites_repo.list_for_map(
        conn,
        country_code="US",
        region="Florida",
        environment_id=ocean,
    )
    # Only the US + Florida + ocean one
    assert {p.id for p in pts} == {1}


def test_list_for_map_returns_ordered_by_id_desc(conn):
    """The newest site comes first (matches the dive map's ordering)."""
    for i, lat in enumerate([24.5, 25.0, 26.0]):
        _seed_site(conn, f"Site {i}",
                   country_code="US",
                   latitude=lat, longitude=-81.0)
    conn.commit()

    pts = sites_repo.list_for_map(conn)
    assert [p.id for p in pts] == [3, 2, 1]


def test_list_for_map_handles_max_depth_null(conn):
    """``max_depth_m`` is optional; NULL is preserved, not defaulted."""
    _seed_site(conn, "With Depth",
               country_code="US",
               latitude=24.5, longitude=-81.5,
               max_depth_m=18.0)
    _seed_site(conn, "Without Depth",
               country_code="US",
               latitude=25.5, longitude=-80.5,
               max_depth_m=None)
    conn.commit()

    pts = sites_repo.list_for_map(conn)
    by_id = {p.id: p for p in pts}
    assert by_id[1].max_depth_m == 18.0
    assert by_id[2].max_depth_m is None


def test_list_for_map_handles_environment_null(conn):
    """``environment_id`` is optional; NULL → environment_name is None too."""
    _seed_site(conn, "No Env",
               country_code="US",
               latitude=24.5, longitude=-81.5,
               environment_id=None)
    conn.commit()

    pts = sites_repo.list_for_map(conn)
    assert len(pts) == 1
    assert pts[0].environment_id is None
    assert pts[0].environment_name is None
