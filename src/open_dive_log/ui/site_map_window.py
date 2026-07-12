"""Site map window — one marker per site on a slippy-map tile background.

Architecture: shares :class:`MapWindowBase` with
:class:`open_dive_log.ui.dive_map_window.DiveMapWindow`. The
base owns the tile cache, status bar, zoom/pan/fit/reset math,
and the click dispatch. This file owns only what's site-specific:

* The :class:`_SiteMarker` ``QGraphicsEllipseItem``
  subclass with the per-site tooltip and the
  environment-coded color.
* The :class:`SiteMapWindow` subclass with the
  ``open_site_requested`` signal and the
  ``list_for_map`` query in :meth:`_render_markers`.
* The environment-to-color palette
  (:func:`environment_color`).

The user picks "show all my dive sites geographically" —
for trip planning, region exploration, or just remembering
where they've been. Sites are static: there's no
chronological numbering, no buddy list, no conditions. The
tooltip is "Site: {name} · {country} · {max_depth_m}m" and
the marker is colored by ``lookup_site_environment.id``.

This file is the implementation of issue #7, parallel to
the dive map (issue #25 / PRs #26 / #27).
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

from open_dive_log.repositories.sites import (
    SiteMapPoint,
    list_for_map,
)
from open_dive_log.ui.map_window_base import MapWindowBase

logger = logging.getLogger(__name__)


# Marker radius for site markers. Slightly smaller
# than the dive marker because there are ~100x more
# sites than dives; we want a dense scatter to remain
# readable.
SITE_MARKER_RADIUS = 5


# Environment color palette. One color per
# ``lookup_site_environment.id``. The palette is
# color-blind safe (distinct hues, not just lightness).
# Sites with ``environment_id IS NULL`` get the
# "unknown" gray. The mapping is module-level (not
# in the class) because it's a pure data table and
# subclass code can override :func:`environment_color`
# for custom palettes.
#
# The ids match the ``lookup_site_environment`` table
# seeded by ``002_opendivemap.sql``:
#   1=ocean, 2=lake, 3=river, 4=spring,
#   5=quarry, 6=fjord, 7=pool, 8=other.
ENVIRONMENT_COLORS: dict[int, str] = {
    1: "#1f77b4",  # ocean — blue
    2: "#2ca02c",  # lake — green
    3: "#17becf",  # river — cyan
    4: "#9467bd",  # spring — purple
    5: "#7f7f7f",  # quarry — gray
    6: "#0a3d62",  # fjord — dark blue
    7: "#ff7f0e",  # pool — orange
    8: "#bcbd22",  # other — olive
}
UNKNOWN_ENVIRONMENT_COLOR = "#d62728"  # red — visible but
# distinct from any natural environment, so missing data
# is visually obvious.


def environment_color(environment_id: int | None) -> QColor:
    """Return the marker color for a site with the given
    ``lookup_site_environment.id``.

    Unknown / NULL environments get
    :data:`UNKNOWN_ENVIRONMENT_COLOR` (red) so missing
    data is visible at a glance.
    """
    if environment_id is None:
        return QColor(UNKNOWN_ENVIRONMENT_COLOR)
    hex_str = ENVIRONMENT_COLORS.get(
        environment_id, UNKNOWN_ENVIRONMENT_COLOR,
    )
    return QColor(hex_str)


class _SiteMarker(QGraphicsEllipseItem):
    """A single site marker on the map.

    Carries a reference to the :class:`SiteMapPoint` it
    represents. The id is also stored via ``setData(0, ...)``
    so the base class's event filter can find it from a
    generic ``QGraphicsEllipseItem`` (without needing to
    know about this subclass).
    """

    def __init__(
        self,
        point: SiteMapPoint,
        parent: QGraphicsItem | None = None,
    ) -> None:
        super().__init__(
            -SITE_MARKER_RADIUS, -SITE_MARKER_RADIUS,
            SITE_MARKER_RADIUS * 2, SITE_MARKER_RADIUS * 2,
            parent,
        )
        color = environment_color(point.environment_id)
        self.setBrush(QBrush(color))
        # White border so the marker stands out against
        # the tile color underneath. A 1.0 px pen is
        # enough at the smaller site-marker radius.
        self.setPen(QPen(QColor(255, 255, 255), 1.0))
        self.setZValue(10)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Set ``point`` *before* the tooltip — the
        # tooltip text is computed from the point.
        self.setData(0, point.id)
        self.point = point
        self.setToolTip(self._tooltip_text())

    def _tooltip_text(self) -> str:
        p = self.point
        bits: list[str] = [p.name]
        if p.country_code:
            bits.append(p.country_code)
        elif p.country:
            bits.append(p.country)
        if p.region:
            bits.append(p.region)
        if p.max_depth_m is not None:
            bits.append(f"to {p.max_depth_m:.0f}m")
        if p.environment_name:
            bits.append(p.environment_name)
        return " · ".join(bits)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        """Accept the press so the scene's view of the
        press event routes to the right item.

        Same pattern as :class:`_DiveMarker`: the actual
        dialog dispatch happens at the scene level
        (see :meth:`MapWindowBase.eventFilter`). We just
        accept the event here so Qt doesn't fall through
        to ``QGraphicsItem``'s default and re-fire the
        press after the modal dialog returns.
        """
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
        else:
            super().mousePressEvent(event)


class SiteMapWindow(MapWindowBase):
    """A standalone map window showing one marker per site.

    Listens to filter changes via :meth:`set_filter` and
    re-renders markers accordingly. Tile fetches happen in
    the background; the map is interactive while tiles
    load (the user sees a graticule or partial tiles).

    Tiles are pulled from OpenStreetMap and cached on disk
    via :class:`MapTileCache`. The cache is a per-user
    persistent store; once a tile is fetched, it never
    re-fetches (unless OSM revises the tile, which is rare).
    """

    WINDOW_TITLE = "Site Map"

    # Emitted when the user wants to open a site dialog.
    # ``MainWindow`` connects this to the existing
    # ``SiteAddEditDialog`` constructor in edit mode.
    open_site_requested = Signal(int)

    def __init__(
        self,
        conn: sqlite3.Connection,
        parent: QWidget | None = None,
        initial_size=None,
    ) -> None:
        # The base class calls ``_render_markers`` in
        # its constructor; that call goes through the
        # standard MRO so the subclass's override runs.
        # No need to set up ``_filter`` before super,
        # because we render with the empty filter
        # (which is the default — all sites with
        # geo data) on first construction.
        super().__init__(conn, parent, initial_size)

    def set_filter(self, f) -> None:
        """Apply a new filter and re-render the markers.

        Called by ``MainWindow`` when the sites list's
        filter changes. ``f`` is a
        :class:`open_dive_log.ui.sites_list_window.SiteFilter`
        dataclass; we accept it without an explicit
        type hint so the import doesn't force a
        circular dependency between the two windows.
        """
        self._filter = f
        self._render_markers()

    # ---- Subclass hooks (overridden) ---------------------------------

    def _render_markers(self) -> None:
        """Re-query the data layer and re-place markers.

        Removes the existing markers, queries
        :func:`open_dive_log.repositories.sites.list_for_map`
        with the current filter, and adds a
        :class:`_SiteMarker` for each result.
        """
        for marker in self._markers:
            self._scene.removeItem(marker)
        self._markers = []
        # ``_filter`` may not be set on the very first
        # call (before ``set_filter`` is invoked) — use
        # a fresh empty filter in that case. Sites
        # without lat/lon are excluded by the SQL, not
        # by the filter.
        f = getattr(self, "_filter", None)
        kwargs = {}
        if f is not None:
            kwargs = {
                "country_code": f.country_code or None,
                "region": f.region or None,
                "environment_id": f.environment_id,
                "entry_id": f.entry_id,
            }
        points = list_for_map(self._conn, **kwargs)
        for p in points:
            m = _SiteMarker(p)
            self._place_marker(m, p.longitude, p.latitude)
        self._update_status()

    def _on_marker_clicked(self, site_id: int) -> None:
        """A marker was clicked.

        Defers via ``QTimer.singleShot(0, ...)`` so the
        press event is fully consumed before any modal
        dialog opens (same fix as the dive map — the
        deferral prevents the "dialog re-opens" loop).
        Emits :attr:`open_site_requested`;
        ``MainWindow`` connects this to
        ``SiteAddEditDialog`` in edit mode.
        """
        QTimer.singleShot(
            0,
            lambda: self.open_site_requested.emit(site_id),
        )
