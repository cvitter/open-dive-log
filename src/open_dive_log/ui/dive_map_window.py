"""Dive map window — one marker per dive on a slippy-map tile background.

Architecture (QGraphicsView subclass):

  * The scene coordinate system is *tile space at zoom z*: a
    point ``(tx, ty)`` corresponds to a position on the world
    map at integer zoom ``z``. Tiles are 256x256 in scene
    units; the visible area is a window into this space.
  * ``_render_visible_tiles()`` runs whenever the viewport
    changes: it asks the tile cache for the (z, x, y) triples
    that cover the visible rect, and adds a ``QGraphicsPixmapItem``
    for each. Missing tiles are queued for network fetch.
  * Markers are ``QGraphicsEllipseItem`` (or ``QGraphicsItem``
    subclass) positioned at
    ``(lon_to_tile_x(lon, z), lat_to_tile_y(lat, z))``.
  * The window has a status bar with a ``QComboBox`` for
    zoom level and a label for the current cursor lat/lon
    + offline status.
  * Pan: drag the viewport. Zoom: mouse wheel (zooms in at
    the cursor position).

The window owns its own ``QNetworkAccessManager`` for tile
fetches. We don't share the application's network manager
because the tile fetches are bulk, parallel, and can be
cancelled when the user pans away from a pending tile.

Filter sync: ``MainWindow`` calls :meth:`set_filter` when the
dive list's filter changes. The map re-fetches markers and
re-renders.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QObject,
    QPointF,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QPainter,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QComboBox,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from open_dive_log.repositories.dives import DiveMapPoint, list_for_map
from open_dive_log.ui.dive_table_model import DiveFilter
from open_dive_log.ui.map_tile_cache import (
    OSM_ATTRIBUTION,
    OSM_TILE_URL,
    MapTileCache,
    lat_to_tile_y,
    lon_to_tile_x,
    tile_x_to_lon,
    tile_y_to_lat,
)

if TYPE_CHECKING:
    from open_dive_log.ui.dive_add_edit_dialog import DiveAddEditDialog

logger = logging.getLogger(__name__)

# Slippy-map tile edge in scene units at any zoom level.
TILE_SIZE = 256

# Default zoom when the window opens. z=4 is the whole
# world; z=8 covers a country; z=12 a region. Dives are
# geographic, not local, so the user can see all their
# dives in one viewport at z=4.
DEFAULT_ZOOM = 4
MIN_ZOOM = 2
MAX_ZOOM = 16

# Marker size in scene units. Independent of zoom because
# ``QGraphicsView`` zooms the scene; we counter-scale the
# marker so it stays roughly 8px on screen at any zoom.
MARKER_RADIUS = 6


class _MapView(QGraphicsView):
    """A QGraphicsView that signals when it scrolls.

    We don't override the actual scroll behavior; we
    observe ``scrollContentsBy`` and emit nothing — the
    ``DiveMapWindow`` wires its throttled tile re-render
    to this signal. The default behavior is exactly what
    we want (smooth pan by scrollbars, hand-drag by
    ScrollHandDrag mode); we just need the callback hook.

    The throttle lives in the window, not the view, because
    the window owns the tile cache and the QTimer.
    """

    contents_scrolled = Signal(int, int)

    def scrollContentsBy(self, dx: int, dy: int) -> None:  # noqa: N802 (Qt API)
        super().scrollContentsBy(dx, dy)
        self.contents_scrolled.emit(dx, dy)


class _DiveMarker(QGraphicsEllipseItem):
    """A single dive marker on the map.

    Carries a reference to the :class:`DiveMapPoint` it
    represents so the click handler can find the dive id.
    The marker is a colored dot with a thin border. The
    color is fixed in v0 (deferring topology color-coding
    to a follow-up).
    """

    def __init__(self, point: DiveMapPoint, parent: QGraphicsItem | None = None) -> None:
        super().__init__(
            -MARKER_RADIUS, -MARKER_RADIUS,
            2 * MARKER_RADIUS, 2 * MARKER_RADIUS,
            parent,
        )
        self._point = point
        # Position in tile space at the current zoom.
        # The actual position is set by the window after
        # creation; we set the visual style here.
        self.setBrush(QBrush(QColor(30, 144, 255)))   # dodger blue
        self.setPen(QPen(QColor(255, 255, 255), 1.5))
        self.setZValue(10)  # above tiles
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(self._tooltip_text())

    @property
    def point(self) -> DiveMapPoint:
        return self._point

    def _tooltip_text(self) -> str:
        p = self._point
        depth = f"{p.max_depth_m:.0f} m" if p.max_depth_m is not None else "?"
        return (
            f"Dive #{p.display_dive_number} · {p.dive_date} · "
            f"{p.site_name} · {depth}"
        )


class DiveMapWindow(QMainWindow):
    """A standalone map window showing one marker per dive.

    Listens to filter changes via :meth:`set_filter` and
    re-renders markers accordingly. Tile fetches happen in
    the background; the map is interactive while tiles load
    (the user sees a graticule or partial tiles).

    Tiles are pulled from OpenStreetMap and cached on disk
    via :class:`MapTileCache`. The cache is a per-user
    persistent store; once a tile is fetched, it never
    re-fetches (unless OSM revises the tile, which is rare).
    """

    # Emitted when the user wants to open a dive dialog.
    # The MainWindow (or a parent window) connects this to
    # the existing ``DiveAddEditDialog`` constructor.
    open_dive_requested = Signal(int)

    def __init__(
        self,
        conn: sqlite3.Connection,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Dive Map")
        self.resize(900, 600)

        self._conn = conn
        self._filter = DiveFilter()
        self._zoom = DEFAULT_ZOOM
        self._cache = MapTileCache()
        self._nam = QNetworkAccessManager(self)
        self._pending_replies: dict[QNetworkReply, tuple[int, int, int]] = {}
        self._markers: list[_DiveMarker] = []
        self._tile_items: dict[tuple[int, int, int], QGraphicsPixmapItem] = {}
        self._offline = False
        self._dive_dialog: DiveAddEditDialog | None = None

        # Scene + view.
        self._scene = QGraphicsScene(self)
        self._scene.setBackgroundBrush(QBrush(QColor(240, 240, 240)))
        self._view = _MapView(self._scene, self)
        self._view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self._view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

        # Throttle tile re-renders on pan. A drag can fire
        # scrollContentsBy dozens of times per second; we
        # coalesce to one re-render per ~100ms via a
        # single-shot timer so the view stays smooth.
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(100)
        self._render_timer.timeout.connect(self._render_visible_tiles)
        # Wire the view's scroll signal to the throttler.
        # On any pan (scrollbar, hand-drag, keyboard) we
        # restart the 100ms timer; the actual re-render
        # only fires after the user stops moving for that
        # long.
        self._view.contents_scrolled.connect(self._on_scrolled)
        self._view.wheelEvent = self._wheel_event  # type: ignore[method-assign]

        # Status bar: zoom selector + offline indicator.
        bar = QStatusBar(self)
        self.setStatusBar(bar)
        self._zoom_combo = QComboBox()
        for z in range(MIN_ZOOM, MAX_ZOOM + 1):
            self._zoom_combo.addItem(f"Zoom {z}", z)
        self._zoom_combo.setCurrentIndex(self._zoom - MIN_ZOOM)
        self._zoom_combo.currentIndexChanged.connect(self._on_zoom_changed)
        self._cursor_label = QLabel("Hover the map for lat/lon")
        self._offline_label = QLabel("")
        bar_layout = QHBoxLayout()
        bar_layout.addWidget(QLabel("Zoom:"))
        bar_layout.addWidget(self._zoom_combo)
        bar_layout.addStretch(1)
        bar_layout.addWidget(self._cursor_label)
        bar_layout.addWidget(self._offline_label)
        bar_widget = QWidget()
        bar_widget.setLayout(bar_layout)
        bar.addPermanentWidget(bar_widget)

        # Center the view on the world at the default zoom.
        layout = QVBoxLayout()
        layout.addWidget(self._view)
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        # Center the initial view on the world.
        world_tiles = 1 << self._zoom
        self._scene.setSceneRect(
            0, 0,
            TILE_SIZE * world_tiles,
            TILE_SIZE * world_tiles,
        )
        # Center on the world midpoint, no transform.
        # ``fitInView`` would set a transform that sticks
        # and breaks pan/zoom on subsequent zoom changes.
        self._view.resetTransform()
        self._view.centerOn(
            QPointF(
                TILE_SIZE * world_tiles / 2,
                TILE_SIZE * world_tiles / 2,
            ),
        )

        # Tile fetched successfully → store + render.
        self._nam.finished.connect(self._on_tile_finished)

        # Cursor tracking for the status bar.
        self._view.setMouseTracking(True)
        self._scene.installEventFilter(self)

        # Render markers immediately so the user sees pins
        # the moment the window opens, even before any
        # explicit set_filter call. Uses the initial empty
        # filter (all dives with geo data).
        self._render_markers()

    # --- Public API ----------------------------------------------------
    def set_filter(self, f: DiveFilter) -> None:
        """Apply a new filter and re-render the markers.

        Called by ``MainWindow`` when the dive list's filter
        changes. Cheap: the marker set is small (max ~100s)
        so we just re-query and rebuild. We always re-render
        even when the filter is unchanged — the cost is one
        SQL query, and the alternative (an equality check)
        is fragile: ``DiveFilter() == DiveFilter()`` is True
        but the map may not have rendered yet on first call.
        """
        self._filter = f
        self._render_markers()

    def set_conn(self, conn: sqlite3.Connection) -> None:
        """Replace the DB connection. Used when the user opens
        a different logbook in the same session (not in v0,
        but kept here for symmetry with the other windows).
        """
        self._conn = conn
        self._render_markers()

    def center_on_dive(self, dive_id: int) -> None:
        """Pan/zoom the map to center on a specific dive marker.

        Used by the dive list's "Show on Map" right-click
        action. If the dive is not in the current filter, the
        marker is added ad-hoc.
        """
        for marker in self._markers:
            if marker.point.id == dive_id:
                self._view.centerOn(marker)
                return
        # Not in current marker set — fetch the dive and add it.
        from open_dive_log.repositories.dives import get_full
        dive = get_full(self._conn, dive_id)
        if dive is None:
            return
        # Find the first site with lat/lon (same logic as
        # list_for_map, but for a single dive).
        site_row = self._conn.execute(
            """
            SELECT s.id, s.name, s.latitude, s.longitude
            FROM dive_site ds
            JOIN site s ON s.id = ds.site_id
            WHERE ds.dive_id = ?
              AND s.latitude IS NOT NULL AND s.longitude IS NOT NULL
            ORDER BY ds.site_order ASC, ds.site_id ASC
            LIMIT 1
            """,
            (dive_id,),
        ).fetchone()
        if site_row is None:
            return
        point = DiveMapPoint(
            id=dive_id,
            display_dive_number=0,  # not used for centering
            dive_date=dive.dive_date,
            site_name=site_row["name"],
            latitude=float(site_row["latitude"]),
            longitude=float(site_row["longitude"]),
            max_depth_m=dive.max_depth_m,
        )
        marker = _DiveMarker(point)
        marker.setPos(
            lon_to_tile_x(point.longitude, self._zoom) * TILE_SIZE,
            lat_to_tile_y(point.latitude, self._zoom) * TILE_SIZE,
        )
        marker.setData(0, dive_id)
        marker.mousePressEvent = lambda ev, m=marker: self._on_marker_clicked(m, ev)  # type: ignore[method-assign]
        self._scene.addItem(marker)
        self._markers.append(marker)
        self._view.centerOn(marker)

    # --- Rendering ----------------------------------------------------
    def _render_markers(self) -> None:
        """Re-query the DB and re-place markers."""
        for marker in self._markers:
            self._scene.removeItem(marker)
        self._markers = []
        points = list_for_map(
            self._conn,
            site_name_substring=self._filter.site_name_substring or None,
            country_code=self._filter.country_code or None,
            date_from=self._filter.date_from or None,
            date_to=self._filter.date_to or None,
            notes_substring=self._filter.notes_substring or None,
        )
        for p in points:
            m = _DiveMarker(p)
            m.setPos(
                lon_to_tile_x(p.longitude, self._zoom) * TILE_SIZE,
                lat_to_tile_y(p.latitude, self._zoom) * TILE_SIZE,
            )
            # Connect click via the item's data role so the
            # view can dispatch without subclassing.
            m.setData(0, p.id)
            m.mousePressEvent = lambda ev, marker=m: self._on_marker_clicked(marker, ev)  # type: ignore[method-assign]
            self._scene.addItem(m)
            self._markers.append(m)
        self._update_status()

    def _center_on_world(self) -> None:
        """Reset the view to the world at the current zoom.

        Centers the view on the world midpoint WITHOUT
        applying a transform. We deliberately avoid
        ``fitInView`` because it leaves a sticky transform
        that breaks subsequent pan/zoom — the world ends
        up at the wrong scale and panning feels sluggish.
        """
        world_tiles = 1 << self._zoom
        self._scene.setSceneRect(
            0, 0,
            TILE_SIZE * world_tiles,
            TILE_SIZE * world_tiles,
        )
        self._view.resetTransform()
        self._view.centerOn(
            QPointF(
                TILE_SIZE * world_tiles / 2,
                TILE_SIZE * world_tiles / 2,
            ),
        )

    def _on_zoom_changed(self, _index: int) -> None:
        z = self._zoom_combo.currentData()
        if z is None:
            return
        self._zoom = int(z)
        self._clear_tiles()
        self._center_on_world()
        self._render_markers()
        self._render_visible_tiles()

    def _clear_tiles(self) -> None:
        for item in self._tile_items.values():
            self._scene.removeItem(item)
        self._tile_items = {}

    def _render_visible_tiles(self) -> None:
        """Add ``QGraphicsPixmapItem`` for every tile in the
        current viewport, queueing network fetches for the
        ones not on disk.
        """
        # Compute the visible rect in tile coordinates.
        visible = self._view.mapToScene(self._view.viewport().rect()).boundingRect()
        z = self._zoom
        if visible.isEmpty():
            return
        x_min = max(0, int(visible.left() / TILE_SIZE))
        x_max = min((1 << z) - 1, int(visible.right() / TILE_SIZE))
        y_min = max(0, int(visible.top() / TILE_SIZE))
        y_max = min((1 << z) - 1, int(visible.bottom() / TILE_SIZE))
        for x in range(x_min, x_max + 1):
            for y in range(y_min, y_max + 1):
                key = (z, x, y)
                if key in self._tile_items:
                    continue
                path = self._cache.lookup(z, x, y)
                if path is not None:
                    pix = QPixmap(str(path))
                    if not pix.isNull():
                        item = QGraphicsPixmapItem(pix)
                        item.setPos(x * TILE_SIZE, y * TILE_SIZE)
                        item.setZValue(-1)
                        self._scene.addItem(item)
                        self._tile_items[key] = item
                        continue
                # Not on disk — fetch.
                self._fetch_tile(z, x, y)
        # Add OSM attribution overlay.
        self._update_attribution()

    def _fetch_tile(self, z: int, x: int, y: int) -> None:
        url = QUrl(OSM_TILE_URL.format(z=z, x=x, y=y))
        req = QNetworkRequest(url)
        req.setRawHeader(b"User-Agent", b"open-dive-log/0.0.1 (dive-map)")
        reply = self._nam.get(req)
        self._pending_replies[reply] = (z, x, y)
        reply.errorOccurred.connect(self._on_tile_error)

    def _on_tile_finished(self, reply: QNetworkReply) -> None:
        coords = self._pending_replies.pop(reply, None)
        if coords is None:
            return
        z, x, y = coords
        if reply.error() != QNetworkReply.NetworkError.NoError:
            return
        payload = bytes(reply.readAll())
        if not payload:
            return
        self._cache.store(z, x, y, payload)
        if (z, x, y) not in self._tile_items:
            pix = QPixmap()
            if pix.loadFromData(payload):
                item = QGraphicsPixmapItem(pix)
                item.setPos(x * TILE_SIZE, y * TILE_SIZE)
                item.setZValue(-1)
                self._scene.addItem(item)
                self._tile_items[(z, x, y)] = item

    def _on_tile_error(self, reply: QNetworkReply, _err) -> None:
        self._pending_replies.pop(reply, None)
        # First error → enter offline mode for the rest of the session.
        if not self._offline:
            self._offline = True
            self._offline_label.setText("Offline — no tiles loaded")
            self._update_status()

    def _update_attribution(self) -> None:
        # Remove any existing attribution item and re-add. (We
        # use a label-like text item instead of a QGraphicsTextItem
        # so it's tiny.)
        # The attribution is required by OSM's tile usage policy.
        # We add it as a small QGraphicsSimpleTextItem anchored
        # to the bottom-right of the scene.
        from PySide6.QtWidgets import QGraphicsSimpleTextItem
        for item in self._scene.items():
            if isinstance(item, QGraphicsSimpleTextItem) and item.text() == OSM_ATTRIBUTION:
                self._scene.removeItem(item)
        attr = QGraphicsSimpleTextItem(OSM_ATTRIBUTION)
        attr.setBrush(QBrush(QColor(80, 80, 80)))
        attr.setZValue(20)
        # Place at the bottom-right of the current scene rect.
        rect = self._scene.sceneRect()
        attr.setPos(rect.right() - 200, rect.bottom() - 20)
        self._scene.addItem(attr)

    def _update_status(self) -> None:
        if self._offline:
            self._offline_label.setText("Offline — no tiles loaded")
        else:
            self._offline_label.setText("")

    # --- Events --------------------------------------------------------
    def _wheel_event(self, event: QWheelEvent) -> None:
        """Zoom in/out at the cursor position.

        Standard slippy-map pattern: ``Ctrl+wheel`` or
        ``wheel alone`` (the latter is what most users
        expect on a Mac trackpad) changes the zoom level,
        and we re-anchor the view so the world-position
        under the cursor stays under the cursor after zoom.
        """
        delta = event.angleDelta().y()
        if delta == 0:
            return
        old_zoom = self._zoom
        if delta > 0 and self._zoom < MAX_ZOOM:
            self._zoom += 1
        elif delta < 0 and self._zoom > MIN_ZOOM:
            self._zoom -= 1
        if self._zoom == old_zoom:
            return
        # Capture the world position under the cursor before
        # the zoom change so we can re-anchor.
        scene_pos = self._view.mapToScene(event.position().toPoint())
        self._zoom_combo.blockSignals(True)
        self._zoom_combo.setCurrentIndex(self._zoom - MIN_ZOOM)
        self._zoom_combo.blockSignals(False)
        self._clear_tiles()
        self._center_on_world()
        self._render_markers()
        # Re-anchor.
        new_scene_pos = self._view.mapToScene(event.position().toPoint())
        delta_scene = new_scene_pos - scene_pos
        self._view.translate(delta_scene.x(), delta_scene.y())
        self._render_visible_tiles()

    def _on_marker_clicked(self, marker: _DiveMarker, event) -> None:
        """Open a popup with the dive info and an 'Open dive' button.

        Implementation note: we use ``QToolTip`` for the
        one-line summary (cheap, native) and an inline
        ``QGraphicsProxyWidget`` for the full popup. The
        proxy approach lets the user click "Open dive"
        without leaving the map.
        """
        # For v0, just emit the signal; the parent window
        # (MainWindow) connects this to the existing
        # DiveAddEditDialog constructor.
        from PySide6.QtWidgets import QGraphicsSceneMouseEvent
        if (
            isinstance(event, QGraphicsSceneMouseEvent)
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self.open_dive_requested.emit(marker.point.id)
        super(_DiveMarker, marker).mousePressEvent(event)

    def eventFilter(self, watched: QObject, event) -> bool:
        # Update the cursor lat/lon in the status bar.
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Type.MouseMove and watched is self._scene:
            scene_pos = event.scenePos()
            lon = tile_x_to_lon(scene_pos.x() / TILE_SIZE, self._zoom)
            lat = tile_y_to_lat(scene_pos.y() / TILE_SIZE, self._zoom)
            if -180 <= lon <= 180 and -90 <= lat <= 90:
                self._cursor_label.setText(f"Lat {lat:.3f} · Lon {lon:.3f}")
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # The visible viewport changes; throttle the
        # re-render so a window drag doesn't thrash tile
        # fetches.
        self._render_timer.start()

    def _on_scrolled(self, _dx: int, _dy: int) -> None:
        """Pan/zoom completed (or in progress): schedule a
        throttled tile re-render.
        """
        self._render_timer.start()
