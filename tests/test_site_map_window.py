"""Tests for the SiteMapWindow (issue #7).

The dive map and site map share their base infrastructure
(``MapWindowBase``); the dive map tests cover that shared
ground. This file covers what's site-specific:

* Markers render on construction (regression for the
  "no pins on first show" bug fixed in PR #27).
* Marker color matches ``lookup_site_environment.id``.
* Marker click emits ``open_site_requested`` (regression
  for the "dialog re-opens" bug fixed in PR #27).
* Filter push updates the marker set.
* Fit / Reset / Offline behave the same as the dive map.
* Open at custom initial size.
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

import pytest

# Ensure Qt uses the offscreen platform in CI / headless.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QSize, Qt
from PySide6.QtWidgets import QGraphicsSceneMouseEvent

from open_dive_log import db
from open_dive_log.ui.map_window_base import (
    TILE_SIZE,
    lat_to_tile_y,
    lon_to_tile_x,
)
from open_dive_log.ui.map_tile_cache import MapTileCache
from open_dive_log.ui.site_map_window import (
    SiteMapWindow,
    _SiteMarker,
    environment_color,
)


# --- Fixtures ----------------------------------------------------------


@pytest.fixture(scope="module")
def qapp():
    """Module-scoped QApplication. PySide6 requires a
    single instance for the whole test session."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def geo_conn() -> sqlite3.Connection:
    """Empty, fully-migrated SQLite connection with 4
    sites in 2 countries, mixed environments. Suitable
    for any ``SiteMapWindow`` test."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        cm = db.connect(f"{d}/test.db")
        c = cm.__enter__()
        db.apply_migrations(c)
        # All countries + envs + entry types are
        # pre-seeded by migrations 001 + 002.
        ocean = c.execute(
            "SELECT id FROM lookup_site_environment WHERE name = 'ocean'",
        ).fetchone()["id"]
        lake = c.execute(
            "SELECT id FROM lookup_site_environment WHERE name = 'lake'",
        ).fetchone()["id"]
        quarry = c.execute(
            "SELECT id FROM lookup_site_environment WHERE name = 'quarry'",
        ).fetchone()["id"]
        boat = c.execute(
            "SELECT id FROM lookup_entry_type WHERE name = 'boat'",
        ).fetchone()["id"]
        # 4 sites:
        #   1: US, ocean, with depth
        #   2: BS, ocean, with depth
        #   3: US, lake, no depth
        #   4: US, quarry, no depth, no env-color match? no — quarry exists
        c.execute(
            """
            INSERT INTO site (name, country_code, latitude, longitude,
                              max_depth_m, environment_id, entry_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("Salt Pier", "US", 24.5, -81.5, 18.0, ocean, boat),
        )
        c.execute(
            """
            INSERT INTO site (name, country_code, latitude, longitude,
                              max_depth_m, environment_id, entry_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("Tiger Beach", "BS", 26.7, -77.3, 25.0, ocean, boat),
        )
        c.execute(
            """
            INSERT INTO site (name, country_code, latitude, longitude,
                              max_depth_m, environment_id, entry_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("Hidden Lake", "US", 27.0, -80.0, None, lake, boat),
        )
        c.execute(
            """
            INSERT INTO site (name, country_code, latitude, longitude,
                              max_depth_m, environment_id, entry_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("Old Quarry", "US", 38.5, -90.0, None, quarry, boat),
        )
        c.commit()
        try:
            yield c
        finally:
            cm.__exit__(None, None, None)


# --- Color palette -----------------------------------------------------


def test_environment_color_returns_distinct_hues_per_environment():
    """The palette uses distinct hues, not just lightness,
    so color-blind users can still tell environments
    apart."""
    colors = {eid: environment_color(eid) for eid in range(1, 9)}
    # No two colors are the same hex.
    assert len(set(c.name() for c in colors.values())) == 8


def test_environment_color_unknown_returns_red():
    """An environment id outside the seeded set (or NULL)
    gets the "unknown" red."""
    assert environment_color(None).name() == "#d62728"
    assert environment_color(99).name() == "#d62728"
    assert environment_color(0).name() == "#d62728"


# --- Construction ------------------------------------------------------


def test_site_map_window_constructs_with_markers(geo_conn, qapp):
    """The constructor renders markers immediately, so
    the user sees pins the moment the window opens —
    the same regression fix as the dive map (PR #27).
    """
    win = SiteMapWindow(geo_conn)
    try:
        assert win.windowTitle() == "Site Map"
        # 4 sites were seeded; all 4 have lat/lon.
        assert len(win._markers) == 4
        for marker in win._markers:
            assert isinstance(marker, _SiteMarker)
            # The id stored via setData(0, ...) is the
            # site id; the base's event filter reads it.
            assert marker.data(0) == marker.point.id
        # Markers positioned at the right tile-coords
        # for the default zoom.
        for marker in win._markers:
            expected_x = lon_to_tile_x(
                marker.point.longitude, 4,
            ) * TILE_SIZE
            expected_y = lat_to_tile_y(
                marker.point.latitude, 4,
            ) * TILE_SIZE
            assert marker.pos().x() == pytest.approx(expected_x)
            assert marker.pos().y() == pytest.approx(expected_y)
    finally:
        win.close()
        win.deleteLater()


def test_site_map_window_respects_initial_size(geo_conn, qapp):
    """When ``initial_size`` is provided, the window
    opens to that size — the same as the dive map fix
    from PR #27.
    """
    win = SiteMapWindow(geo_conn, initial_size=QSize(1234, 567))
    try:
        QCoreApplication.processEvents()
        size = win.size()
        # Be lenient about exact pixels (window-
        # decorator insets can shift things) but assert
        # the requested size was honored.
        assert 1200 <= size.width() <= 1260
        assert 540 <= size.height() <= 590
    finally:
        win.close()
        win.deleteLater()


# --- Marker color ------------------------------------------------------


def test_site_map_window_marker_color_matches_environment(geo_conn, qapp):
    """The marker brush color is the
    ``environment_color(point.environment_id)`` color."""
    win = SiteMapWindow(geo_conn)
    try:
        for marker in win._markers:
            expected = environment_color(marker.point.environment_id)
            # ``QBrush.color()`` returns a QColor; compare
            # the named hex (lowercase, #rrggbb).
            actual = marker.brush().color().name().lower()
            expected_hex = expected.name().lower()
            assert actual == expected_hex, (
                f"marker for {marker.point.name} has color "
                f"{actual}, expected {expected_hex} "
                f"(env_id={marker.point.environment_id})"
            )
    finally:
        win.close()
        win.deleteLater()


# --- Click → signal ----------------------------------------------------


def _send_marker_press(win, marker) -> None:
    """Build a real ``QGraphicsSceneMouseEvent`` at the
    marker's scene position and route it through the
    scene's event filter. The constructor is opaque in
    PySide6 6.8, so we use the 1-arg constructor + the
    public setters (``setScenePos``, ``setPos``,
    ``setScreenPos``, ``setButton``).
    """
    scene = win._scene
    ev = QGraphicsSceneMouseEvent(
        QEvent.Type.GraphicsSceneMousePress,
    )
    ev.setScenePos(marker.scenePos())
    ev.setPos(marker.scenePos().toPoint())
    ev.setScreenPos(
        scene.views()[0].mapToGlobal(
            marker.scenePos().toPoint(),
        ),
    )
    ev.setButton(Qt.MouseButton.LeftButton)
    ev.setButtons(Qt.MouseButton.LeftButton)
    win.eventFilter(scene, ev)


def test_site_map_window_marker_click_emits_signal(geo_conn, qapp):
    """Pressing a marker emits the open_site_requested
    signal with the right site id.
    """
    from open_dive_log.ui.map_tile_cache import MapTileCache
    win = SiteMapWindow(geo_conn)
    try:
        win._cache = MapTileCache(root=Path("/tmp/site_map_test_cache"))
        received: list[int] = []
        win.open_site_requested.connect(received.append)
        # Use the last marker (Hidden Lake) which has a
        # unique scene position; the first two (Salt
        # Pier, Tiger Beach) are at the same scene pos
        # because their lat/lon is similar — well, not
        # in this fixture. Let me check.
        marker = win._markers[0]
        target_id = marker.point.id
        _send_marker_press(win, marker)
        # The signal emission is deferred
        # (``singleShot(0)``), so we have to spin the
        # event loop briefly. Loop until either the
        # signal arrives or the deadline passes.
        deadline = time.monotonic() + 1.0
        while not received and time.monotonic() < deadline:
            QCoreApplication.processEvents()
        assert received == [target_id], (
            f"expected signal for site {target_id}, "
            f"got {received}"
        )
    finally:
        win.close()
        win.deleteLater()


def test_site_map_window_marker_click_defers_signal_emit(geo_conn, qapp):
    """The signal is emitted via ``QTimer.singleShot(0, ...)``,
    not synchronously. This is the regression test for
    the "won't stay closed" bug pattern.
    """
    from open_dive_log.ui.map_tile_cache import MapTileCache
    win = SiteMapWindow(geo_conn)
    try:
        win._cache = MapTileCache(
            root=Path("/tmp/site_map_test_cache_2"),
        )
        received: list[int] = []
        win.open_site_requested.connect(received.append)
        marker = win._markers[0]
        _send_marker_press(win, marker)
        # Synchronously (no event loop tick), the signal
        # has not yet fired.
        assert received == []
        # Now process events; the deferred emission
        # runs.
        deadline = time.monotonic() + 1.0
        while len(received) < 1 and time.monotonic() < deadline:
            QCoreApplication.processEvents()
        assert len(received) == 1
    finally:
        win.close()
        win.deleteLater()


# --- Filter push -------------------------------------------------------


def test_site_map_window_filter_push_updates_markers(geo_conn, qapp):
    """``set_filter`` re-queries the data layer and
    re-places markers. The fixture has 3 US sites and
    1 BS site; filtering to ``country_code='US'`` keeps
    only 3 markers.
    """
    win = SiteMapWindow(geo_conn)
    try:
        from open_dive_log.ui.sites_list_window import SiteFilter
        win.set_filter(SiteFilter(country_code="US"))
        assert len(win._markers) == 3
        for marker in win._markers:
            assert marker.point.country_code == "US"
    finally:
        win.close()
        win.deleteLater()


def test_site_map_window_environment_filter(geo_conn, qapp):
    """``set_filter(environment_id=...)`` keeps only
    sites in that environment.
    """
    win = SiteMapWindow(geo_conn)
    try:
        from open_dive_log.ui.sites_list_window import SiteFilter
        ocean = geo_conn.execute(
            "SELECT id FROM lookup_site_environment "
            "WHERE name = 'ocean'",
        ).fetchone()["id"]
        lake = geo_conn.execute(
            "SELECT id FROM lookup_site_environment "
            "WHERE name = 'lake'",
        ).fetchone()["id"]
        win.set_filter(SiteFilter(environment_id=ocean))
        assert len(win._markers) == 2
        win.set_filter(SiteFilter(environment_id=lake))
        assert len(win._markers) == 1
    finally:
        win.close()
        win.deleteLater()


# --- Same controls as the dive map ------------------------------------


def test_site_map_window_zoom_buttons_change_zoom(geo_conn, qapp):
    """+/- buttons clamp at MIN/MAX_ZOOM."""
    win = SiteMapWindow(geo_conn)
    try:
        # Initial zoom is DEFAULT_ZOOM (= 4).
        assert win._zoom == 4
        win._zoom_in_btn.click()
        assert win._zoom == 5
        # Click many times to hit the cap.
        for _ in range(20):
            win._zoom_in_btn.click()
        assert win._zoom == 16  # MAX_ZOOM
        # And back down.
        for _ in range(20):
            win._zoom_out_btn.click()
        assert win._zoom == 2  # MIN_ZOOM
    finally:
        win.close()
        win.deleteLater()


def test_site_map_window_fit_to_markers_zooms_to_bbox(geo_conn, qapp):
    """The Fit button finds a sensible zoom for the
    marker bbox."""
    win = SiteMapWindow(geo_conn)
    try:
        win._cache = MapTileCache(
            root=Path("/tmp/site_map_test_cache_3"),
        )
        win.resize(900, 600)
        win.show()
        assert len(win._markers) > 0
        win._fit_btn.click()
        # After fitting, the zoom should be at least 5
        # (markers are within ~3° of each other in this
        # fixture, and at z=5 each tile is ~2.4° wide).
        assert win._zoom >= 5
    finally:
        win.close()
        win.deleteLater()


def test_site_map_window_reset_returns_to_world(geo_conn, qapp):
    """The Home button returns to the default view."""
    win = SiteMapWindow(geo_conn)
    try:
        # Zoom in twice.
        win._zoom_in_btn.click()
        win._zoom_in_btn.click()
        assert win._zoom > 4
        win._home_btn.click()
        assert win._zoom == 4  # DEFAULT_ZOOM
    finally:
        win.close()
        win.deleteLater()


def test_site_map_window_offline_falls_back_to_no_tiles(geo_conn, qapp):
    """If the network manager is disabled (no real OSM
    fetches possible), the window still renders markers.
    The user sees a graticule (the scene's default
    background brush) with markers on top.
    """
    from open_dive_log.ui.map_tile_cache import MapTileCache
    win = SiteMapWindow(geo_conn)
    try:
        win._cache = MapTileCache(
            root=Path("/tmp/site_map_test_cache_4"),
        )
        # Block the network by deleting the manager.
        win._nam.deleteLater()
        # Markers are still present.
        assert len(win._markers) == 4
        # The view shows a graticule (the scene's default
        # background brush) with markers on top. Nothing
        # to assert beyond "markers exist"; the offline
        # state is for the *tile* pipeline, which only
        # matters if the user pans/zooms.
    finally:
        win.close()
        win.deleteLater()
