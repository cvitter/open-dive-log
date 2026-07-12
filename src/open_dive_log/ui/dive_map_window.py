"""Dive map window — one marker per dive on a slippy-map tile background.

The shared infrastructure (status bar, tile cache, render
pipeline, zoom/pan/fit/reset math, click dispatch) lives in
:class:`open_dive_log.ui.map_window_base.MapWindowBase`.
This file owns only what's dive-specific:

* The :class:`_DiveMarker` ``QGraphicsEllipseItem``
  subclass with the per-dive tooltip text.
* The ``list_for_map`` data query in
  :meth:`_render_markers`.
* The :class:`open_dive_requested` signal and the
  :meth:`_on_marker_clicked` handler that defers via
  ``QTimer.singleShot(0, ...)``.
* The :meth:`center_on_dive` "show this dive on the
  map" helper used by the dive list's right-click
  action.

Architecture invariant: a marker is positioned at
``(lon_to_tile_x(point.lon, z) * TILE_SIZE,
lat_to_tile_y(point.lat, z) * TILE_SIZE)`` in scene
coordinates (the base re-positions all markers on
every zoom change).

This file is the result of the issue #7 refactor
(extracting the shared dive-map and site-map code into
a common base). Prior versions of this class (PRs
#26/#27) held all the infrastructure inline.
"""

from __future__ import annotations

import logging
import sqlite3

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QPen
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QWidget,
)

from open_dive_log.repositories.dives import (
    DiveMapPoint,
    get_full,
    list_for_map,
)
from open_dive_log.ui.dive_table_model import DiveFilter
from open_dive_log.ui.map_window_base import (
    MARKER_RADIUS,
    MapWindowBase,
)

logger = logging.getLogger(__name__)


class _DiveMarker(QGraphicsEllipseItem):
    """A single dive marker on the map.

    Carries a reference to the :class:`DiveMapPoint` it
    represents so the click handler can find the dive id.
    The id is also stored via ``setData(0, ...)`` so the
    base class's event filter can find it from a generic
    ``QGraphicsEllipseItem`` (without needing to know
    about this subclass).
    """

    def __init__(
        self,
        point: DiveMapPoint,
        parent: QGraphicsItem | None = None,
    ) -> None:
        super().__init__(
            -MARKER_RADIUS, -MARKER_RADIUS,
            MARKER_RADIUS * 2, MARKER_RADIUS * 2,
            parent,
        )
        # Solid blue fill with a white border so the
        # marker stands out against any tile color.
        self.setBrush(QBrush(QColor(31, 119, 180)))
        self.setPen(QPen(QColor(255, 255, 255), 1.5))
        self.setZValue(10)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Set ``_point`` *before* the tooltip — the
        # tooltip text is computed from the point.
        self.setData(0, point.id)
        self.point = point
        self.setToolTip(self._tooltip_text())

    def _tooltip_text(self) -> str:
        p = self.point
        bits = [f"Dive #{p.display_dive_number}", p.dive_date, p.site_name]
        if p.max_depth_m is not None:
            bits.append(f"to {p.max_depth_m:.0f}m")
        return " · ".join(bits)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        """Accept the press so the scene's view of the
        press event routes to the right item.

        The actual dialog dispatch happens at the scene
        level in :meth:`MapWindowBase.eventFilter` —
        not here. We accept the event so Qt doesn't
        re-fire it on the parent item (the
        ``QGraphicsItem`` default would otherwise set
        the mouse-grabber state, which caused the
        "dialog re-opens" bug fixed in PR #27).
        """
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
        else:
            super().mousePressEvent(event)


class DiveMapWindow(MapWindowBase):
    """A standalone map window showing one marker per dive.

    Listens to filter changes via :meth:`set_filter` and
    re-renders markers accordingly. Tile fetches happen in
    the background; the map is interactive while tiles
    load (the user sees a graticule or partial tiles).
    """

    WINDOW_TITLE = "Dive Map"

    # Emitted when the user wants to open a dive dialog.
    # ``MainWindow`` connects this to the existing
    # ``DiveAddEditDialog`` constructor.
    open_dive_requested = Signal(int)

    def __init__(
        self,
        conn: sqlite3.Connection,
        parent: QWidget | None = None,
        initial_size=None,
    ) -> None:
        # Use the base's machinery. We need ``_filter``
        # set up *before* the base calls
        # ``_render_markers`` in its constructor.
        self._filter = DiveFilter()
        super().__init__(conn, parent, initial_size)

    def set_filter(self, f: DiveFilter) -> None:
        """Apply a new filter and re-render the markers.

        Called by ``MainWindow`` when the dive list's
        filter changes. Cheap: the marker set is small
        (max ~100s) so we just re-query and rebuild.
        We always re-render even when the filter is
        unchanged — the cost is one SQL query, and the
        alternative (an equality check) is fragile:
        ``DiveFilter() == DiveFilter()`` is True but
        the map may not have rendered yet on first call.
        """
        self._filter = f
        self._render_markers()

    def center_on_dive(self, dive_id: int) -> None:
        """Pan/zoom the map to center on a specific
        dive marker.

        Used by the dive list's "Show on Map"
        right-click action. If the dive is not in the
        current filter, the marker is added ad-hoc.
        """
        for marker in self._markers:
            if marker.point.id == dive_id:
                self._view.centerOn(marker)
                return
        # Not in current marker set — fetch the dive
        # and add it.
        dive = get_full(self._conn, dive_id)
        if dive is None:
            return
        # Find the first site with lat/lon (same logic
        # as list_for_map, but for a single dive).
        site_row = self._conn.execute(
            """
            SELECT s.id, s.name, s.latitude, s.longitude
            FROM dive_site ds
            JOIN site s ON s.id = ds.site_id
            WHERE ds.dive_id = ?
              AND s.latitude IS NOT NULL
              AND s.longitude IS NOT NULL
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
        self._place_marker(
            marker, point.longitude, point.latitude,
        )
        self._view.centerOn(marker)

    # ---- Subclass hooks (overridden) ---------------------------------

    def _render_markers(self) -> None:
        """Re-query the data layer and re-place markers.

        Removes the existing markers, queries
        ``dives.list_for_map`` with the current filter,
        and adds a :class:`_DiveMarker` for each result.
        """
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
            self._place_marker(m, p.longitude, p.latitude)
        self._update_status()

    def _on_marker_clicked(self, dive_id: int) -> None:
        """A marker was clicked.

        Defers via ``QTimer.singleShot(0, ...)`` so the
        press event is fully consumed before any modal
        dialog opens — without the deferral, Qt can
        re-fire the press after the dialog returns,
        causing a re-open loop. Emits
        :attr:`open_dive_requested`; ``MainWindow``
        connects this to ``DiveAddEditDialog`` in
        edit mode.
        """
        QTimer.singleShot(
            0,
            lambda: self.open_dive_requested.emit(dive_id),
        )
