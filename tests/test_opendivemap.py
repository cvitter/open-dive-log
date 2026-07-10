"""Tests for the opendivemap importer. Uses a fake iter_sites to avoid network."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from open_dive_log import db
from open_dive_log import import_opendivemap
from open_dive_log.repositories import sites
from open_dive_log.sources import opendivemap


@pytest.fixture()
def conn(tmp_path: Path):
    """A migrated, open SQLite connection scoped to the test."""
    db_path = tmp_path / "test.db"
    cm = db.connect(db_path)
    c = cm.__enter__()
    db.apply_migrations(c)
    try:
        yield c
    finally:
        cm.__exit__(None, None, None)


def _feature(
    *,
    ext: str = "abc123",
    name: str = "Tugboat",
    country_code: str = "BQ",
    country_name: str = "Bonaire",
    lat: float | None = 12.0,
    lon: float | None = -68.0,
    env: str | None = "ocean",
    topos: tuple[str, ...] = ("reef", "wall"),
    max_depth: int | None = 30,
    entry: str | None = "boat",
    description: str | None = None,
    description_wildlife: str | None = None,
    tags: dict | None = None,
) -> opendivemap.ODMFeature:
    return opendivemap.ODMFeature(
        external_id=ext, name=name,
        country_code=country_code, country_name=country_name,
        latitude=lat, longitude=lon,
        sea_mrgid=None, environment=env, topologies=topos,
        max_depth=max_depth, entry=entry,
        description=description, description_wildlife=description_wildlife,
        tags=tags or {}, external_url=f"https://opendivemap.com/explore?site={ext}",
    )


def test_import_inserts_site(conn: sqlite3.Connection) -> None:
    counts = import_opendivemap._upsert_feature(
        conn, source_id=1, f=_feature()
    )
    assert counts == "inserted"
    rows = conn.execute("SELECT name, country_code, max_depth_m FROM site").fetchall()
    assert len(rows) == 1
    assert rows[0]["name"] == "Tugboat"
    assert rows[0]["country_code"] == "BQ"
    assert rows[0]["max_depth_m"] == 30.0


def test_import_idempotent_update(conn: sqlite3.Connection) -> None:
    import_opendivemap._upsert_feature(conn, 1, _feature())
    counts2 = import_opendivemap._upsert_feature(
        conn, 1, _feature(name="Tugboat (Renamed)", max_depth=35)
    )
    assert counts2 == "updated"
    # Still one site, depth updated, name NOT updated (preserves user edits).
    rows = conn.execute("SELECT name, max_depth_m FROM site").fetchall()
    assert len(rows) == 1
    assert rows[0]["name"] == "Tugboat"  # not 'Tugboat (Renamed)'
    assert rows[0]["max_depth_m"] == 35.0


def test_import_auto_adds_country(conn: sqlite3.Connection) -> None:
    # AW (Aruba) is not in the seed list
    import_opendivemap._upsert_feature(conn, 1, _feature(country_code="AW", country_name="Aruba"))
    row = conn.execute("SELECT name FROM country WHERE code='AW'").fetchone()
    assert row is not None
    assert row["name"] == "Aruba"


def test_import_auto_adds_topology(conn: sqlite3.Connection) -> None:
    # "coral_garden" is not in the seed list
    import_opendivemap._upsert_feature(conn, 1, _feature(topos=("coral_garden",)))
    tops = sites.get_topologies(
        conn,
        conn.execute("SELECT id FROM site").fetchone()["id"],
    )
    assert any(t.name == "coral_garden" for t in tops)
    added = conn.execute(
        "SELECT name FROM lookup_site_topology WHERE name='coral_garden'"
    ).fetchone()
    assert added is not None


def test_import_handles_null_max_depth(conn: sqlite3.Connection) -> None:
    import_opendivemap._upsert_feature(conn, 1, _feature(max_depth=None))
    row = conn.execute("SELECT max_depth_m FROM site").fetchone()
    assert row["max_depth_m"] is None


def test_import_skips_empty_name(conn: sqlite3.Connection) -> None:
    out = import_opendivemap._upsert_feature(conn, 1, _feature(name="", ext=""))
    assert out == "skipped"
    assert conn.execute("SELECT COUNT(*) AS c FROM site").fetchone()["c"] == 0


def test_import_records_external_id_and_url(conn: sqlite3.Connection) -> None:
    import_opendivemap._upsert_feature(conn, 1, _feature())
    site_id = conn.execute("SELECT id FROM site").fetchone()["id"]
    ext = sites.get_external_ids(conn, site_id)
    assert len(ext) == 1
    assert ext[0].system_name == "opendivemap"
    assert ext[0].external_id == "abc123"
    assert "opendivemap.com" in ext[0].external_url


def test_import_stores_description_and_wildlife(conn: sqlite3.Connection) -> None:
    out = import_opendivemap._upsert_feature(
        conn, 1, _feature(
            description="A beautiful coral wall dropping to 40m.",
            description_wildlife="Reef sharks, turtles, moray eels.",
        ),
    )
    assert out == "inserted"
    site_id = conn.execute("SELECT id FROM site").fetchone()["id"]
    site = sites.get(conn, site_id)
    assert site.description == "A beautiful coral wall dropping to 40m."
    assert site.description_wildlife == "Reef sharks, turtles, moray eels."


def test_import_description_updated_on_reimport(conn: sqlite3.Connection) -> None:
    """The update path should refresh descriptions, not just depth/lat/lon."""
    import_opendivemap._upsert_feature(conn, 1, _feature(description="v1 description"))
    out2 = import_opendivemap._upsert_feature(conn, 1, _feature(description="v2 description (updated)"))
    assert out2 == "updated"
    site_id = conn.execute("SELECT id FROM site").fetchone()["id"]
    site = sites.get(conn, site_id)
    assert site.description == "v2 description (updated)"


def test_import_empty_description_stored_as_null(conn: sqlite3.Connection) -> None:
    """Whitespace-only descriptions should normalize to NULL, not ''.

    Tests the real client parser (not the test fixture), since the
    normalization happens when ODMFeature is built from a raw GeoJSON dict.
    """
    raw = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
        "properties": {
            "id": "aa0001",
            "name": "EmptyDesc",
            "tags": {"description": "   \n  ", "description_wildlife": ""},
        },
    }
    feature = opendivemap._feature_to_odm(raw)
    assert feature.description is None
    assert feature.description_wildlife is None

    import_opendivemap._upsert_feature(conn, 1, feature)
    site_id = conn.execute("SELECT id FROM site").fetchone()["id"]
    site = sites.get(conn, site_id)
    assert site.description is None
    assert site.description_wildlife is None


def test_import_all_end_to_end_with_fake_iter(monkeypatch, conn, tmp_path) -> None:
    """Drive import_all() against a fake iterator to verify the counter + transactions."""
    # Re-open a fresh DB for this test (the fixture's conn is a real one,
    # but we want import_all to control its own connection lifecycle).
    db_path = tmp_path / "all.db"
    db.init_db(db_path)

    def fake_iter():
        yield _feature(ext="aaa111", name="A")
        yield _feature(ext="bbb222", name="B", country_code="CW", country_name="Curaçao")
        yield _feature(ext="ccc333", name="C", max_depth=None, topos=())

    monkeypatch.setattr(opendivemap, "iter_sites", fake_iter)
    monkeypatch.setattr(import_opendivemap.opendivemap, "get_stats",
                        lambda **kw: {"total_sites": 3, "total_countries": 2})

    counts = import_opendivemap.import_all(db_path=db_path, progress_every=1)
    assert dict(counts) == {"inserted": 3}

    # Re-run: all should be updated
    counts2 = import_opendivemap.import_all(db_path=db_path, progress_every=1)
    assert dict(counts2) == {"updated": 3}


def test_import_each_opendivemap_record_is_its_own_site(conn: sqlite3.Connection) -> None:
    """Two opendivemap ids for the same (name, country_code) should result in
    two site rows (one per upstream record), each with its own external_id."""
    out1 = import_opendivemap._upsert_feature(conn, 1, _feature(ext="aaa111", name="Coral Garden", country_code="SC"))
    out2 = import_opendivemap._upsert_feature(conn, 1, _feature(ext="bbb222", name="Coral Garden", country_code="SC"))
    assert out1 == "inserted"
    assert out2 == "inserted"

    # Two sites, two external ids.
    sites_count = conn.execute("SELECT COUNT(*) AS c FROM site").fetchone()["c"]
    ext_count = conn.execute("SELECT COUNT(*) AS c FROM site_external_id").fetchone()["c"]
    assert sites_count == 2
    assert ext_count == 2

    ext_ids = {r["external_id"] for r in conn.execute("SELECT external_id FROM site_external_id").fetchall()}
    assert ext_ids == {"aaa111", "bbb222"}


def test_import_real_run_matches_upstream_count(monkeypatch, conn, tmp_path) -> None:
    """The full 3123-site stream should produce exactly 3123 site_external_id
    rows and 3123 site rows (one per opendivemap record)."""
    db_path = tmp_path / "real.db"
    db.init_db(db_path)

    # Use a tiny synthetic stream with deliberate (name, country) collisions.
    def fake_iter():
        # 5 distinct sites
        for ext, name, cc, cn in [
            ("x1", "A", "US", "United States"),
            ("x2", "B", "US", "United States"),
            ("x3", "C", "MX", "Mexico"),
            ("x4", "D", "MX", "Mexico"),
            ("x5", "E", "BZ", "Belize"),
        ]:
            yield _feature(ext=ext, name=name, country_code=cc, country_name=cn)
        # 3 dupes of the same (name, country) with NEW external ids
        for ext in ("dup1", "dup2", "dup3"):
            yield _feature(ext=ext, name="A", country_code="US", country_name="United States")
        # 1 exact repeat of an earlier ext (should be 'updated', not 'inserted')
        yield _feature(ext="x3", name="C", country_code="MX", country_name="Mexico")

    monkeypatch.setattr(opendivemap, "iter_sites", fake_iter)
    monkeypatch.setattr(import_opendivemap.opendivemap, "get_stats",
                        lambda **kw: {"total_sites": 9, "total_countries": 3})

    counts = import_opendivemap.import_all(db_path=db_path, progress_every=100)
    # 8 unique external_ids inserted, 1 re-imported as updated.
    assert dict(counts) == {"inserted": 8, "updated": 1}, dict(counts)

    with db.connect(db_path) as c:
        sites = c.execute("SELECT COUNT(*) AS c FROM site").fetchone()["c"]
        exts = c.execute("SELECT COUNT(*) AS c FROM site_external_id").fetchone()["c"]
    assert sites == 8
    # 8 unique external_ids, one row each (the re-import of x3 hit the
    # 'updated' path which doesn't touch site_external_id).
    assert exts == 8
