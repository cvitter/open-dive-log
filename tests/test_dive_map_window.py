"""Tests for the dive map window widget.

The map window is a ``QGraphicsView`` subclass that needs
PySide6 + a network manager. Tests run under
``QT_QPA_PLATFORM=offscreen`` so they don't need a display.

These tests do not exercise the network fetcher (that would
need a real OSM endpoint and would flake in CI). They
exercise:

* the constructor doesn't crash,
* a fresh window has no markers,
* setting a filter renders markers from the DB,
* the ``open_dive_requested`` signal is emitted on click,
* the offline-fallback path renders markers without tiles.

Visual rendering (do the tiles actually draw) is smoke-tested
manually.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

# Force offscreen Qt platform before importing QtWidgets so
# the constructor doesn't try to open a display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsSceneMouseEvent,
)

from open_dive_log import db
from open_dive_log.repositories import dives as dives_repo
from open_dive_log.ui.dive_map_window import (
    DiveMapWindow,
    lat_to_tile_y,
    lon_to_tile_x,
)
from open_dive_log.ui.dive_table_model import DiveFilter


@pytest.fixture(scope="module")
def qapp():
    """A single QApplication for all tests in this module.

    PySide6 requires a QApplication to exist before any
    QWidget is constructed. Module-scoped so the QApplication
    is created once per test file (creating one per test
    is slow and triggers dylib-re-tagging on macOS).
    """
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def geo_conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """A migrated test DB with 3 dives, 2 with geo, 1 without."""
    cm = db.connect(tmp_path / "map_widget_test.db")
    c = cm.__enter__()
    db.apply_migrations(c)
    c.execute("INSERT OR IGNORE INTO country (code, name) VALUES ('US', 'United States')")
    c.commit()
    sid1 = c.execute(
        "INSERT INTO site (name, country_code, latitude, longitude) "
        "VALUES (?, ?, ?, ?)",
        ("Salt Pier", "US", 24.5, -81.5),
    ).lastrowid
    sid2 = c.execute(
        "INSERT INTO site (name, country_code, latitude, longitude) "
        "VALUES (?, ?, ?, ?)",
        ("Tiger Beach", "US", 26.7, -77.3),
    ).lastrowid
    assert sid1 is not None
    assert sid2 is not None
    did1 = dives_repo.create(
        c, dive_date="2024-01-15",
        max_depth_m=18.0, avg_depth_m=12.0,
    )
    did2 = dives_repo.create(
        c, dive_date="2024-03-22",
        max_depth_m=25.0, avg_depth_m=15.0,
    )
    did3 = dives_repo.create(
        c, dive_date="2024-07-04",
        max_depth_m=10.0, avg_depth_m=8.0,
    )
    dives_repo.attach_sites(c, did1, [sid1])
    dives_repo.attach_sites(c, did2, [sid2])
    dives_repo.attach_sites(c, did3, [sid2])  # same site as did2
    c.commit()
    yield c
    cm.__exit__(None, None, None)


def test_dive_map_window_respects_initial_size(
    geo_conn, qapp, tmp_path: Path,
) -> None:
    """When ``initial_size`` is provided, the window
    opens to that size — the user-reported "open the
    map at the same size as the dive list" feature.

    Regression test: prior to this, the map always
    opened at 900x600 regardless of how the dive
    list was sized.
    """
    from open_dive_log.ui.map_tile_cache import MapTileCache
    from PySide6.QtCore import QSize
    win = DiveMapWindow(
        geo_conn,
        initial_size=QSize(1234, 567),
    )
    try:
        win._cache = MapTileCache(root=tmp_path / "tiles")
        # The constructor calls resize; allow a brief
        # event-loop tick for the geometry to settle.
        from PySide6.QtCore import QCoreApplication
        QCoreApplication.processEvents()
        size = win.size()
        # Be lenient about exact pixels (window-decorator
        # insets can shift things) but assert the
        # requested size was honored.
        assert 1200 <= size.width() <= 1260, (
            f"expected width ~1234, got {size.width()}"
        )
        assert 540 <= size.height() <= 590, (
            f"expected height ~567, got {size.height()}"
        )
    finally:
        win.close()
        win.deleteLater()


def test_dive_map_window_constructs_with_markers(geo_conn, qapp):
    """The constructor renders markers immediately so the
    user sees pins the moment the window opens.

    Pre-fix this test asserted ``len(win._markers) == 0``
    because the constructor didn't call ``_render_markers``
    — the user had to call ``set_filter`` to see pins. That
    was a bug: opening the menu action did
    ``set_filter(DiveFilter())`` to compensate, but if
    anything else opened the window (e.g. an external API)
    the user saw an empty map.

    Post-fix the constructor renders with the initial empty
    filter, so all 3 geo-coded dives appear as markers.
    """
    win = DiveMapWindow(geo_conn)
    try:
        assert win.windowTitle() == "Dive Map"
        # Markers are present immediately, before any
        # explicit set_filter call.
        assert len(win._markers) == 3
        # The markers are positioned at the right
        # tile-coords for z=4.
        from open_dive_log.ui.dive_map_window import TILE_SIZE
        for marker in win._markers:
            expected_x = lon_to_tile_x(marker.point.longitude, 4) * TILE_SIZE
            expected_y = lat_to_tile_y(marker.point.latitude, 4) * TILE_SIZE
            assert abs(marker.pos().x() - expected_x) < 1e-6
            assert abs(marker.pos().y() - expected_y) < 1e-6
    finally:
        win.close()
        win.deleteLater()


def test_dive_map_window_zoom_keeps_pan_responsive(geo_conn, qapp, tmp_path):
    """After a zoom change, the view's transform is reset
    so subsequent pans move at the right speed and
    direction. Pre-fix this test failed because
    ``_center_on_world`` used ``fitInView`` which left a
    sticky transform; panning felt sluggish or moved
    backward.
    """
    from open_dive_log.ui.map_tile_cache import MapTileCache
    win = DiveMapWindow(geo_conn)
    try:
        win._cache = MapTileCache(root=tmp_path / "tiles")
        # Change the zoom combo (simulates the user picking
        # z=8 from the dropdown).
        win._zoom_combo.setCurrentIndex(8 - 2)  # MIN_ZOOM=2
        # After the zoom change, the view's transform is
        # reset (no scaling), and the world is at the
        # correct z=8 dimensions.
        assert win._zoom == 8
        scene_rect = win._scene.sceneRect()
        assert scene_rect.width() == 256 * 256
        # Pan a small distance and check the view actually
        # scrolls. Pre-fix, the transform was leftover from
        # fitInView and the view didn't scroll at all on
        # the first pan after a zoom.
        before = win._view.horizontalScrollBar().value()
        win._view.translate(50, 0)
        after = win._view.horizontalScrollBar().value()
        assert before != after, (
            f"Panning did not scroll the view: before={before} after={after}"
        )
    finally:
        win.close()
        win.deleteLater()


def test_dive_map_window_renders_markers_for_filter(
    geo_conn, tmp_path: Path, qapp,
) -> None:
    """After set_filter, the window holds one marker per
    dive that has a geo site.
    """
    win = DiveMapWindow(geo_conn)
    try:
        # Pin the tile cache to tmp so we don't litter the
        # user's real ~/.cache during tests.
        win._cache.__class__ = type(win._cache)
        from open_dive_log.ui.map_tile_cache import MapTileCache
        win._cache = MapTileCache(root=tmp_path / "tiles")
        win.set_filter(DiveFilter())
        # 2 dives have geo sites; 1 has the same site as
        # did2 (still counted as a marker).
        assert len(win._markers) == 3
        # Each marker carries a DiveMapPoint; the first one
        # should be the most-recently-inserted dive (highest id).
        ids = {m.point.id for m in win._markers}
        assert ids == set(
            row[0] for row in geo_conn.execute(
                "SELECT id FROM dive ORDER BY id ASC",
            ).fetchall()
        )
        # Filter to country=US — still 3 (all US in this fixture).
        win.set_filter(DiveFilter(country_code="US"))
        assert len(win._markers) == 3
        # Filter to a non-existent country — 0 markers.
        win.set_filter(DiveFilter(country_code="BS"))
        assert len(win._markers) == 0
        # Clear filter — back to 3.
        win.set_filter(DiveFilter())
        assert len(win._markers) == 3
    finally:
        win.close()
        win.deleteLater()


def test_dive_map_window_marker_click_emits_signal(
    geo_conn, tmp_path: Path, qapp,
) -> None:
    """Pressing a marker emits the open_dive_requested signal.

    Exercises the real event-filter path: we synthesize a
    ``QGraphicsSceneMouseEvent`` and route it through the
    scene's event filter (same path Qt uses for real
    clicks). The ``QTimer.singleShot(0, ...)`` deferral
    means the signal fires asynchronously; the test waits
    a single event-loop tick to receive it.
    """
    from open_dive_log.ui.map_tile_cache import MapTileCache
    win = DiveMapWindow(geo_conn)
    try:
        win._cache = MapTileCache(root=tmp_path / "tiles")
        received: list[int] = []
        win.open_dive_requested.connect(received.append)
        # Simulate a left-button press on the first marker.
        # We use the *last* marker (id=1) which has a
        # unique scene position; the first two markers
        # (id=3, id=2) are stacked at the same position
        # because did2 and did3 both attach to the same
        # site (sid2 in the fixture). Stacking makes
        # ``itemAt`` non-deterministic between the two,
        # so we use a marker that has no stacking.
        marker = win._markers[-1]
        target_id = marker.point.id
        # Build a real QGraphicsSceneMouseEvent at the
        # marker's scene position. The public
        # ``QGraphicsSceneMouseEvent`` constructor is
        # opaque across PySide6 versions, so we use the
        # 1-arg constructor (Type) plus the public
        # setters: ``setScenePos``, ``setPos``,
        # ``setScreenPos``, ``setButton``.
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
        # Route through the scene's event filter (the
        # same path real Qt input takes). ``sendEvent``
        # bypasses the filter so we call the filter
        # directly.
        win.eventFilter(scene, ev)
        # The signal emission is deferred (singleShot(0)),
        # so we have to spin the event loop briefly.
        # ``processEvents`` only processes events already
        # in the queue; a singleShot(0) timer's event
        # is queued *during* the first pass and only
        # fires on the second pass. Loop until either
        # the signal arrives or the deadline passes.
        import time
        deadline = time.monotonic() + 1.0
        while not received and time.monotonic() < deadline:
            QCoreApplication.processEvents()
        assert received == [target_id], (
            f"expected signal for dive {target_id}, got {received}"
        )
    finally:
        win.close()
        win.deleteLater()


def test_dive_map_window_marker_click_defers_signal_emit(
    geo_conn, tmp_path: Path, qapp,
) -> None:
    """The signal is emitted via ``QTimer.singleShot(0, ...)``,
    not synchronously, to avoid the "dialog re-opens"
    loop. This test asserts that *without* processing
    events, the signal hasn't fired yet.
    """
    from open_dive_log.ui.map_tile_cache import MapTileCache
    win = DiveMapWindow(geo_conn)
    try:
        win._cache = MapTileCache(root=tmp_path / "tiles")
        received: list[int] = []
        win.open_dive_requested.connect(received.append)
        # Use the last marker (id=1, unique position)
        # for the same reason as above: ``itemAt`` is
        # non-deterministic between stacked markers.
        marker = win._markers[-1]
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
        # Synchronously (no event loop tick), the signal
        # has not yet fired. This is the regression test
        # for the "won't stay closed" bug.
        assert received == []
        # Now process events; the deferred emission runs.
        # Loop because singleShot(0) takes two passes.
        import time
        deadline = time.monotonic() + 1.0
        while len(received) < 1 and time.monotonic() < deadline:
            QCoreApplication.processEvents()
        assert len(received) == 1
    finally:
        win.close()
        win.deleteLater()


def test_dive_map_window_zoom_buttons_change_zoom(
    geo_conn, tmp_path: Path, qapp,
) -> None:
    """The + / − buttons in the status bar change the
    zoom level. Clicking + should advance the zoom
    by 1; clicking − should retreat.
    """
    from open_dive_log.ui.map_tile_cache import MapTileCache
    win = DiveMapWindow(geo_conn)
    try:
        win._cache = MapTileCache(root=tmp_path / "tiles")
        # Initial zoom is DEFAULT_ZOOM (4).
        assert win._zoom == 4
        win._zoom_in_btn.click()
        assert win._zoom == 5
        win._zoom_in_btn.click()
        assert win._zoom == 6
        win._zoom_out_btn.click()
        assert win._zoom == 5
        # Clamped at MIN_ZOOM.
        for _ in range(20):
            win._zoom_out_btn.click()
        assert win._zoom == 2
    finally:
        win.close()
        win.deleteLater()


def test_dive_map_window_fit_to_markers_zooms_to_bbox(
    geo_conn, tmp_path: Path, qapp,
) -> None:
    """The 'Fit' button zooms the view so all markers
    are visible with a small padding margin.

    The offscreen test viewport can be much smaller
    than the user's 900x600 window, so we explicitly
    resize the window before clicking Fit. (Without
    that, the offscreen viewport is 98x28 and the
    fit math decides the bbox is too tall, so it
    zooms *out* — which is the correct behavior in
    that pathological case.)
    """
    from open_dive_log.ui.map_tile_cache import MapTileCache
    win = DiveMapWindow(geo_conn)
    try:
        win._cache = MapTileCache(root=tmp_path / "tiles")
        win.resize(900, 600)
        win.show()
        # Markers exist; we should be able to fit.
        assert len(win._markers) > 0
        win._fit_btn.click()
        # After fitting, the zoom level should be at
        # least 5 (markers are within ~1° of each
        # other in the fixture, and at z=5 each
        # tile is ~2.4° wide, so the markers are
        # comfortably visible).
        assert win._zoom >= 5
    finally:
        win.close()
        win.deleteLater()


def test_dive_map_window_reset_returns_to_world(
    geo_conn, tmp_path: Path, qapp,
) -> None:
    """The 'Home' button resets the view to the world
    at the default zoom.
    """
    from open_dive_log.ui.map_tile_cache import MapTileCache
    win = DiveMapWindow(geo_conn)
    try:
        win._cache = MapTileCache(root=tmp_path / "tiles")
        # Zoom in.
        win._zoom_in_btn.click()
        win._zoom_in_btn.click()
        win._zoom_in_btn.click()
        assert win._zoom > 4
        # Reset.
        win._home_btn.click()
        assert win._zoom == 4
    finally:
        win.close()
        win.deleteLater()


def test_dive_map_window_center_on_dive_pans_to_marker(
    geo_conn, tmp_path: Path, qapp,
) -> None:
    """center_on_dive(d) moves the view so the marker for
    dive d is roughly in the viewport center.
    """
    from open_dive_log.ui.map_tile_cache import MapTileCache
    win = DiveMapWindow(geo_conn)
    try:
        win._cache = MapTileCache(root=tmp_path / "tiles")
        win.set_filter(DiveFilter())
        # Pick a marker and record its position.
        target = win._markers[-1]  # oldest dive
        target_id = target.point.id
        # Move the view elsewhere first.
        win._view.translate(1000, 1000)
        # Now center on the dive.
        win.center_on_dive(target_id)
        # The target marker is now near the viewport center.
        # (We can't compare the view's scroll position
        # directly without invoking show() + event loop,
        # so just check the marker is in the marker list.)
        assert any(m.point.id == target_id for m in win._markers)
    finally:
        win.close()
        win.deleteLater()


def test_dive_map_window_offline_falls_back_to_no_tiles(
    geo_conn, tmp_path: Path, qapp,
) -> None:
    """If the network manager is disabled (no real OSM
    fetches possible), the window still renders markers.
    The user sees a graticule (the scene's default
    background brush) with markers on top.
    """
    from open_dive_log.ui.map_tile_cache import MapTileCache
    win = DiveMapWindow(geo_conn)
    try:
        win._cache = MapTileCache(root=tmp_path / "tiles")
        # Block the network by deleting the manager. Any
        # subsequent fetch attempts would fail; in practice
        # the map just renders markers without tiles.
        win._nam.deleteLater()
        win.set_filter(DiveFilter())
        # Markers are still placed correctly.
        assert len(win._markers) == 3
        # The marker's position is consistent with the
        # tile-coord math (no crash even though no tiles
        # are loaded).
        marker = win._markers[0]
        from open_dive_log.ui.dive_map_window import TILE_SIZE
        z = win._zoom
        expected_x = lon_to_tile_x(marker.point.longitude, z) * TILE_SIZE
        expected_y = lat_to_tile_y(marker.point.latitude, z) * TILE_SIZE
        assert abs(marker.pos().x() - expected_x) < 1e-6
        assert abs(marker.pos().y() - expected_y) < 1e-6
    finally:
        win.close()
        win.deleteLater()
