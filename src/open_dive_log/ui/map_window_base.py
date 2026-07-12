"""Shared infrastructure for the dive and site map windows.

Both :class:`DiveMapWindow` and :class:`SiteMapWindow` are
slippy-map views: a ``QGraphicsScene`` whose units are
``TILE_SIZE``-pixel tiles at integer zoom ``z``, populated
with OSM tiles fetched from a per-user disk cache, and
decorated with one ``QGraphicsEllipseItem`` per data row
(dive or site).

What lives here (the parts that would be byte-for-byte
identical between the two windows):

* The ``_MapView`` ``QGraphicsView`` subclass with a
  throttled ``contents_scrolled`` signal — the throttle
  coalesces a flurry of pan events into one tile
  re-render.
* The status bar: zoom +/- buttons, a ``QComboBox`` for
  zoom level, a "Fit" button, a "Home" button, a
  cursor lat/lon label, and an offline indicator.
* Keyboard shortcuts: ``+``/``-`` zoom, ``F`` fits,
  ``Home`` resets, arrow keys pan by 1/4 of the viewport.
* The tile cache wiring (``MapTileCache``),
  ``QNetworkAccessManager``, the
  ``_render_visible_tiles`` / ``_fetch_tile`` /
  ``_on_tile_finished`` / ``_on_tile_error`` pipeline,
  the OSM attribution overlay.
* The zoom-at-cursor math, the fit-to-markers math, the
  reset-to-world math.
* The scene-level click dispatch via ``eventFilter``
  (handles both cursor tracking for the status bar and
  marker click → deferred signal emission).

What the subclass owns:

* The marker subclass (``_DiveMarker`` / ``_SiteMarker``)
  and any per-marker styling (color, size).
* The data query — i.e. which ``list_for_map`` to call
  with which filter shape.
* The click handler — i.e. which signal to emit
  (``open_dive_requested`` vs ``open_site_requested``).
* The window title.
* The default zoom (dives default to z=4 world; sites
  also default to z=4, but this is a subclass knob).

Subclass contract:

* Override :meth:`_render_markers` to query the data layer
  and place one ``QGraphicsEllipseItem`` per row.
* Override :meth:`_on_marker_clicked` to emit the
  subclass-specific signal (typically a single-shot
  ``QTimer.singleShot(0, ...)`).
* Set the class attribute :attr:`WINDOW_TITLE` to a
  human-readable string shown in the title bar.
* Set :attr:`_pending_replies` and :attr:`_tile_items` in
  the constructor (the base doesn't own them — they live
  on the subclass instance dict).

Architecture invariant: a marker is positioned at
``(lon_to_tile_x(point.lon, z) * TILE_SIZE,
lat_to_tile_y(point.lat, z) * TILE_SIZE)`` in scene
coordinates. The base re-positions all markers on every
zoom change (see :meth:`_on_zoom_changed` and
:meth:`_wheel_event`) — subclasses don't need to
re-implement this.

This file is the result of the issue #7 refactor
(extracting the shared dive-map and site-map code into
a common base). The dive map (PRs #26/#27) was the
first consumer; the site map (PR for issue #7) is the
second.
"""

from __future__ import annotations

import logging
import math
import sqlite3
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QObject,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QKeySequence,
    QPainter,
    QPixmap,
    QShortcut,
    QWheelEvent,
)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QComboBox,
    QGraphicsEllipseItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsSceneMouseEvent,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

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
    pass

logger = logging.getLogger(__name__)


# Slippy-map tile edge in scene units at any zoom level.
# A scene-coord position ``(x, y)`` corresponds to tile
# ``(x // TILE_SIZE, y // TILE_SIZE)`` at the current zoom.
TILE_SIZE = 256

# Default zoom when the window opens. z=4 is the whole
# world; z=8 covers a country; z=12 a region. Dives and
# sites are geographic, not local, so the user can see
# all their markers in one viewport at z=4.
DEFAULT_ZOOM = 4
MIN_ZOOM = 2
MAX_ZOOM = 16

# Marker radius in scene units. Independent of zoom
# because ``QGraphicsView`` zooms the scene; the marker
# stays a constant scene-units size.
MARKER_RADIUS = 6


class _MapView(QGraphicsView):
    """A ``QGraphicsView`` that signals when it scrolls.

    We don't override the actual scroll behavior; we
    override ``scrollContentsBy`` to emit a custom
    signal that the window connects to a throttled
    tile re-render. A drag can fire scrollContentsBy
    dozens of times per second; we coalesce to one
    re-render per ~100ms via a single-shot timer
    (owned by the window) so the view stays smooth.
    """

    contents_scrolled = Signal(int, int)

    def scrollContentsBy(self, dx: int, dy: int) -> None:  # noqa: N802 (Qt API)
        super().scrollContentsBy(dx, dy)
        self.contents_scrolled.emit(dx, dy)


class MapWindowBase(QMainWindow):
    """Base class for the dive and site map windows.

    Subclasses set :attr:`WINDOW_TITLE` and override
    :meth:`_render_markers` + :meth:`_on_marker_clicked`.
    Everything else — the status bar, the shortcuts, the
    tile pipeline, the zoom/pan/fit/reset math, the
    click dispatch — is shared here.

    See the module docstring for the full contract.
    """

    # Subclasses override this. Also override the public
    # ``open_*_requested`` signal with a more specific
    # name (``open_dive_requested`` / ``open_site_requested``).
    WINDOW_TITLE = "Map"

    # Generic "open this item" signal. Subclasses should
    # re-alias this to a more specific name (e.g.
    # ``open_dive_requested = Signal(int)`` in the
    # subclass) but the base class implementation can
    # fall back to this if the subclass didn't.
    open_item_requested = Signal(int)

    # ---- Constructor --------------------------------------------------

    def __init__(
        self,
        conn: sqlite3.Connection,
        parent: QWidget | None = None,
        initial_size: QSize | None = None,
    ) -> None:
        """Set up the map window.

        Args:
            conn: An open SQLite connection. Subclasses
                pass this to their data-layer query.
            parent: Optional parent widget for centering.
            initial_size: Optional ``QSize`` for the
                window's initial geometry. If ``None``,
                defaults to 900x600 (the historical
                default). ``MainWindow`` passes its own
                current size so the map opens to the
                same dimensions as the list window.
        """
        super().__init__(parent)
        self.setWindowTitle(self.WINDOW_TITLE)
        # Default to 900x600 if no size was supplied.
        if initial_size is not None:
            self.resize(initial_size)
        else:
            self.resize(900, 600)

        self._conn = conn
        self._zoom = DEFAULT_ZOOM
        self._cache = MapTileCache()
        self._nam = QNetworkAccessManager(self)
        self._pending_replies: dict[QNetworkReply, tuple[int, int, int]] = {}
        self._markers: list[QGraphicsEllipseItem] = []
        self._tile_items: dict[tuple[int, int, int], QGraphicsPixmapItem] = {}
        self._offline = False

        # Scene + view.
        self._scene = QGraphicsScene(self)
        self._scene.setBackgroundBrush(QBrush(QColor(240, 240, 240)))
        self._view = _MapView(self._scene, self)
        self._view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self._view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._view.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse,
        )

        # Throttle tile re-renders on pan. A drag can
        # fire scrollContentsBy dozens of times per
        # second; we coalesce to one re-render per
        # ~100ms via a single-shot timer.
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(100)
        self._render_timer.timeout.connect(self._render_visible_tiles)
        self._view.contents_scrolled.connect(self._on_scrolled)
        self._view.wheelEvent = self._wheel_event  # type: ignore[method-assign]

        self._build_status_bar()
        self._build_keyboard_shortcuts()

        # Center widget: just the view, in a VBox layout.
        layout = QVBoxLayout()
        layout.addWidget(self._view)
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        # Center the initial view on the world at the
        # default zoom. ``fitInView`` would set a
        # transform that sticks and breaks pan/zoom on
        # subsequent zoom changes; ``centerOn`` doesn't.
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

        # Tile fetched successfully → store + render.
        self._nam.finished.connect(self._on_tile_finished)

        # Cursor tracking for the status bar.
        self._view.setMouseTracking(True)
        self._scene.installEventFilter(self)

        # Render markers immediately so the user sees
        # pins the moment the window opens, even before
        # any explicit set_filter call. The base class
        # calls the subclass's ``_render_markers`` via
        # the standard method-resolution order.
        self._render_markers()

    def _build_status_bar(self) -> None:
        """Build the status bar with zoom controls and
        cursor/offline indicators. Called by the
        constructor; subclasses that want a different
        layout can override."""
        bar = QStatusBar(self)
        self.setStatusBar(bar)
        self._zoom_out_btn = QPushButton("−")
        self._zoom_out_btn.setFixedWidth(28)
        self._zoom_out_btn.setToolTip("Zoom out (−)")
        self._zoom_out_btn.clicked.connect(lambda: self._zoom_by(-1))
        self._zoom_combo = QComboBox()
        for z in range(MIN_ZOOM, MAX_ZOOM + 1):
            self._zoom_combo.addItem(f"Zoom {z}", z)
        self._zoom_combo.setCurrentIndex(self._zoom - MIN_ZOOM)
        self._zoom_combo.currentIndexChanged.connect(self._on_zoom_changed)
        self._zoom_in_btn = QPushButton("+")
        self._zoom_in_btn.setFixedWidth(28)
        self._zoom_in_btn.setToolTip("Zoom in (+)")
        self._zoom_in_btn.clicked.connect(lambda: self._zoom_by(+1))
        self._fit_btn = QPushButton("Fit")
        self._fit_btn.setToolTip(
            "Zoom to fit all markers (F)",
        )
        self._fit_btn.clicked.connect(self._fit_to_markers)
        self._home_btn = QPushButton("Home")
        self._home_btn.setToolTip("Reset to the world view (Home)")
        self._home_btn.clicked.connect(self._reset_view)
        self._cursor_label = QLabel("Hover the map for lat/lon")
        self._offline_label = QLabel("")
        bar_layout = QHBoxLayout()
        bar_layout.addWidget(QLabel("Zoom:"))
        bar_layout.addWidget(self._zoom_out_btn)
        bar_layout.addWidget(self._zoom_combo)
        bar_layout.addWidget(self._zoom_in_btn)
        bar_layout.addWidget(self._fit_btn)
        bar_layout.addWidget(self._home_btn)
        bar_layout.addStretch(1)
        bar_layout.addWidget(self._cursor_label)
        bar_layout.addWidget(self._offline_label)
        bar_widget = QWidget()
        bar_widget.setLayout(bar_layout)
        bar.addPermanentWidget(bar_widget)

    def _build_keyboard_shortcuts(self) -> None:
        """Wire the +/-/F/Home/arrow shortcuts to their
        handlers. Subclasses can add more in their
        constructor (after super().__init__)."""
        self._shortcut_zoom_in = QShortcut(QKeySequence("+"), self)
        self._shortcut_zoom_in.activated.connect(
            lambda: self._zoom_by(+1),
        )
        self._shortcut_zoom_out = QShortcut(QKeySequence("-"), self)
        self._shortcut_zoom_out.activated.connect(
            lambda: self._zoom_by(-1),
        )
        self._shortcut_fit = QShortcut(QKeySequence("F"), self)
        self._shortcut_fit.activated.connect(self._fit_to_markers)
        self._shortcut_home = QShortcut(QKeySequence("Home"), self)
        self._shortcut_home.activated.connect(self._reset_view)
        self._arrow_shortcuts: list[QShortcut] = []
        for key, dx, dy in (
            (Qt.Key.Key_Left,   -1,  0),
            (Qt.Key.Key_Right,  +1,  0),
            (Qt.Key.Key_Up,      0, -1),
            (Qt.Key.Key_Down,    0, +1),
        ):
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(
                lambda d=dx, d2=dy: self._pan_by(d, d2),
            )
            self._arrow_shortcuts.append(sc)

    # ---- Public API ---------------------------------------------------

    def set_conn(self, conn: sqlite3.Connection) -> None:
        """Replace the DB connection. Used when the user
        opens a different logbook in the same session."""
        self._conn = conn
        self._render_markers()

    # ---- Subclass hooks (overridden) ----------------------------------

    def _render_markers(self) -> None:
        """Re-query the data layer and re-place markers.

        Subclasses MUST override. The base class
        implementation is a no-op (it doesn't know
        about the data layer). The override should:

        1. Remove all existing markers from the scene.
        2. Re-query the data layer (``list_for_map``).
        3. Add one ``QGraphicsEllipseItem`` subclass
           per data row, positioned at
           ``(lon_to_tile_x(lon, z) * TILE_SIZE,
           lat_to_tile_y(lat, z) * TILE_SIZE)``.
        4. Call ``self._update_status()`` (so the
           status bar shows the right marker count).
        """
        # The base has no data; this is just a hook.
        # Subclasses MUST override.

    def _on_marker_clicked(self, item_id: int) -> None:
        """A marker was clicked. Subclasses override
        to defer + emit the subclass-specific signal
        (``open_dive_requested`` / ``open_site_requested``).
        The base implementation emits the generic
        ``open_item_requested``."""
        QTimer.singleShot(
            0,
            lambda: self.open_item_requested.emit(item_id),
        )

    # ---- Marker placement helper --------------------------------------

    def _place_marker(
        self,
        marker: QGraphicsEllipseItem,
        longitude: float,
        latitude: float,
    ) -> None:
        """Position a marker at (lat, lon) and add it to
        the scene. Subclasses call this in their
        ``_render_markers`` override; the base owns the
        "convert (lat, lon) → scene coords" math so
        subclasses don't have to."""
        marker.setPos(
            lon_to_tile_x(longitude, self._zoom) * TILE_SIZE,
            lat_to_tile_y(latitude, self._zoom) * TILE_SIZE,
        )
        self._scene.addItem(marker)
        self._markers.append(marker)

    # ---- View math ----------------------------------------------------

    def _center_on_world(self) -> None:
        """Reset the view to the world at the current
        zoom. Uses ``centerOn`` (no transform) to avoid
        the sticky-transform problem ``fitInView``
        causes."""
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
        new_zoom = int(z)
        if new_zoom == self._zoom:
            return
        old_zoom = self._zoom
        self._zoom = new_zoom
        # Capture the world position at the viewport
        # center so we can re-center on the same lat/lon
        # after the zoom change.
        viewport_center_scene = self._view.mapToScene(
            self._view.viewport().rect().center(),
        )
        world_tiles = 1 << self._zoom
        self._scene.setSceneRect(
            0, 0,
            TILE_SIZE * world_tiles,
            TILE_SIZE * world_tiles,
        )
        # The marker positions are in tile-space *
        # TILE_SIZE; the actual pixel position of a
        # marker at (lat, lon) is
        # ``lon_to_tile_x(lon, zoom) * TILE_SIZE``, which
        # changes when zoom changes. Re-place every
        # marker.
        self._clear_tiles()
        self._render_markers()
        # Re-anchor on the same lat/lon at the new zoom.
        lat = tile_y_to_lat(
            viewport_center_scene.y() / TILE_SIZE,
            old_zoom,
        )
        lon = tile_x_to_lon(
            viewport_center_scene.x() / TILE_SIZE,
            old_zoom,
        )
        new_x = lon_to_tile_x(lon, self._zoom) * TILE_SIZE
        new_y = lat_to_tile_y(lat, self._zoom) * TILE_SIZE
        self._view.resetTransform()
        self._view.centerOn(QPointF(new_x, new_y))
        self._render_timer.start()

    def _zoom_by(self, delta: int) -> None:
        """Step the zoom by ``delta`` (+1 or -1).
        Bumps the zoom combo (clamped) and fires
        ``_on_zoom_changed`` via the combo's
        currentIndexChanged signal."""
        new_zoom = self._zoom + delta
        new_zoom = max(MIN_ZOOM, min(MAX_ZOOM, new_zoom))
        if new_zoom == self._zoom:
            return
        # Block the combo's signal so the wheel/button
        # path doesn't double-fire _on_zoom_changed.
        self._zoom_combo.blockSignals(True)
        self._zoom_combo.setCurrentIndex(new_zoom - MIN_ZOOM)
        self._zoom_combo.blockSignals(False)
        self._on_zoom_changed(new_zoom - MIN_ZOOM)

    def _pan_by(self, dx: int, dy: int) -> None:
        """Pan the view by (dx, dy) * 1/4 of the viewport.
        Holding an arrow key keeps firing the shortcut,
        so a long press = a long pan."""
        viewport = self._view.viewport().rect()
        step_x = int(viewport.width() / 4) * dx
        step_y = int(viewport.height() / 4) * dy
        self._view.translate(step_x, step_y)

    def _fit_to_markers(self) -> None:
        """Zoom + pan to show all current markers with
        a small padding margin. If there are no
        markers, this is a no-op."""
        if not self._markers:
            return
        bbox = QRectF()
        for m in self._markers:
            bbox = bbox.united(m.sceneBoundingRect())
        if bbox.isEmpty():
            return
        pad_x = bbox.width() * 0.1
        pad_y = bbox.height() * 0.1
        padded = bbox.adjusted(-pad_x, -pad_y, pad_x, pad_y)
        viewport = self._view.viewport().rect()
        if viewport.width() == 0 or viewport.height() == 0:
            return
        # Pick a target zoom so the bbox fills ~80% of
        # the viewport. The bbox width is in
        # current-zoom scene pixels. To make it fill
        # the viewport:
        #   bbox_w * 2^(target_zoom - current_zoom)
        #       = viewport_w / 0.8
        # Solving:
        #   target_zoom = current_zoom
        #       + log2(viewport_w / (bbox_w * 1.25))
        scale_x = viewport.width() / max(padded.width(), 1.0) / 1.25
        scale_y = viewport.height() / max(padded.height(), 1.0) / 1.25
        scale = min(scale_x, scale_y)
        if scale <= 0:
            return
        delta_zoom = math.log2(scale)
        target_zoom = max(
            MIN_ZOOM,
            min(MAX_ZOOM, int(round(self._zoom + delta_zoom))),
        )
        if target_zoom != self._zoom:
            self._zoom = target_zoom
            self._zoom_combo.blockSignals(True)
            self._zoom_combo.setCurrentIndex(target_zoom - MIN_ZOOM)
            self._zoom_combo.blockSignals(False)
        # Recompute the scene rect and marker positions
        # for the new zoom.
        self._clear_tiles()
        world_tiles = 1 << self._zoom
        self._scene.setSceneRect(
            0, 0,
            TILE_SIZE * world_tiles,
            TILE_SIZE * world_tiles,
        )
        self._render_markers()
        cx = (padded.left() + padded.right()) / 2
        cy = (padded.top() + padded.bottom()) / 2
        self._view.resetTransform()
        self._view.centerOn(QPointF(cx, cy))
        self._render_timer.start()

    def _reset_view(self) -> None:
        """Reset to the world at the default zoom."""
        if self._zoom != DEFAULT_ZOOM:
            self._zoom = DEFAULT_ZOOM
            self._zoom_combo.blockSignals(True)
            self._zoom_combo.setCurrentIndex(DEFAULT_ZOOM - MIN_ZOOM)
            self._zoom_combo.blockSignals(False)
        self._clear_tiles()
        self._center_on_world()
        self._render_markers()
        self._render_timer.start()

    # ---- Tile pipeline -----------------------------------------------

    def _clear_tiles(self) -> None:
        for item in self._tile_items.values():
            self._scene.removeItem(item)
        self._tile_items = {}

    def _render_visible_tiles(self) -> None:
        """Add a ``QGraphicsPixmapItem`` for every tile
        in the current viewport, queueing network
        fetches for the ones not on disk."""
        visible = self._view.mapToScene(
            self._view.viewport().rect(),
        ).boundingRect()
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
                self._fetch_tile(z, x, y)
        self._update_attribution()

    def _fetch_tile(self, z: int, x: int, y: int) -> None:
        url = QUrl(OSM_TILE_URL.format(z=z, x=x, y=y))
        req = QNetworkRequest(url)
        req.setRawHeader(
            b"User-Agent", b"open-dive-log/0.0.1 (map)",
        )
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
        # First error → enter offline mode for the
        # rest of the session.
        if not self._offline:
            self._offline = True
            self._offline_label.setText(
                "Offline — no tiles loaded",
            )
            self._update_status()

    def _update_attribution(self) -> None:
        """Place the OSM attribution overlay at the
        bottom-right of the scene. Required by OSM's
        tile usage policy."""
        for item in self._scene.items():
            if (
                isinstance(item, QGraphicsSimpleTextItem)
                and item.text() == OSM_ATTRIBUTION
            ):
                self._scene.removeItem(item)
        attr = QGraphicsSimpleTextItem(OSM_ATTRIBUTION)
        attr.setBrush(QBrush(QColor(80, 80, 80)))
        attr.setZValue(20)
        rect = self._scene.sceneRect()
        attr.setPos(rect.right() - 200, rect.bottom() - 20)
        self._scene.addItem(attr)

    def _update_status(self) -> None:
        """Update the status bar labels. Called by
        ``_on_tile_error`` and by subclasses'
        ``_render_markers`` overrides (so the marker
        count can be shown)."""
        if self._offline:
            self._offline_label.setText(
                "Offline — no tiles loaded",
            )
        else:
            self._offline_label.setText("")

    # ---- Events -------------------------------------------------------

    def _wheel_event(self, event: QWheelEvent) -> None:
        """Zoom in/out at the cursor position. Standard
        slippy-map behavior: the world position under
        the cursor stays under the cursor after the
        zoom change."""
        delta = event.angleDelta().y()
        if delta == 0:
            return
        old_zoom = self._zoom
        if delta > 0 and self._zoom < MAX_ZOOM:
            new_zoom = self._zoom + 1
        elif delta < 0 and self._zoom > MIN_ZOOM:
            new_zoom = self._zoom - 1
        else:
            return
        if new_zoom == old_zoom:
            return
        scene_pos = self._view.mapToScene(
            event.position().toPoint(),
        )
        self._zoom = new_zoom
        self._zoom_combo.blockSignals(True)
        self._zoom_combo.setCurrentIndex(self._zoom - MIN_ZOOM)
        self._zoom_combo.blockSignals(False)
        world_tiles = 1 << self._zoom
        self._scene.setSceneRect(
            0, 0,
            TILE_SIZE * world_tiles,
            TILE_SIZE * world_tiles,
        )
        self._clear_tiles()
        self._render_markers()
        # Convert the cursor's pre-zoom scene pos to
        # (lat, lon), then forward to the new zoom.
        lat = tile_y_to_lat(
            scene_pos.y() / TILE_SIZE, old_zoom,
        )
        lon = tile_x_to_lon(
            scene_pos.x() / TILE_SIZE, old_zoom,
        )
        new_x = lon_to_tile_x(lon, self._zoom) * TILE_SIZE
        new_y = lat_to_tile_y(lat, self._zoom) * TILE_SIZE
        self._view.resetTransform()
        self._view.centerOn(QPointF(new_x, new_y))
        cursor_viewport = event.position().toPoint()
        center_viewport = self._view.viewport().rect().center()
        # Translate so the world position that was at
        # the cursor's pre-zoom scene_pos is at the
        # cursor's *current* screen position. The
        # current screen position of the new scene pos
        # is at the view's center, so translate by
        # (center - cursor).
        self._view.translate(
            center_viewport.x() - cursor_viewport.x(),
            center_viewport.y() - cursor_viewport.y(),
        )
        self._render_timer.start()

    def eventFilter(self, watched: QObject, event) -> bool:
        """Scene-level event handler.

        Two responsibilities:

        1. **Cursor tracking** — on every
           ``GraphicsSceneMouseMove``, update the status
           bar's lat/lon label.

        2. **Marker click dispatch** — on every
           ``GraphicsSceneMousePress`` (left button),
           find the topmost item at the press pos and,
           if it's one of our markers, defer the click
           handler via ``QTimer.singleShot(0, ...)`` so
           the press event is fully consumed before any
           modal loop starts (this is the regression
           fix for the "dialog re-opens" bug).
        """
        from PySide6.QtCore import QEvent
        if watched is self._scene:
            if event.type() == QEvent.Type.GraphicsSceneMouseMove:
                scene_pos = event.scenePos()
                lon = tile_x_to_lon(
                    scene_pos.x() / TILE_SIZE, self._zoom,
                )
                lat = tile_y_to_lat(
                    scene_pos.y() / TILE_SIZE, self._zoom,
                )
                if -180 <= lon <= 180 and -90 <= lat <= 90:
                    self._cursor_label.setText(
                        f"Lat {lat:.3f} · Lon {lon:.3f}",
                    )
            elif (
                event.type() == QEvent.Type.GraphicsSceneMousePress
                and isinstance(event, QGraphicsSceneMouseEvent)
                and event.button() == Qt.MouseButton.LeftButton
            ):
                scene_pos = event.scenePos()
                item = self._scene.itemAt(
                    scene_pos, self._view.transform(),
                )
                if isinstance(item, QGraphicsEllipseItem):
                    # Defer the dialog open so the press
                    # event is fully consumed before Qt
                    # starts a modal event loop.
                    QTimer.singleShot(
                        0,
                        lambda i=item: self._on_marker_clicked(
                            int(i.data(0)),
                        ),
                    )
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        self._render_timer.start()

    def _on_scrolled(self, _dx: int, _dy: int) -> None:
        self._render_timer.start()
