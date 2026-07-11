"""On-disk cache for OpenStreetMap raster tiles.

A "tile" is a 256x256 PNG that the slippy-map (Web Mercator)
projection uses to cover the world. The map widget fetches
tiles lazily as the user pans/zooms. Fetching a tile is
expensive (network round-trip); once fetched, the bytes are
stable for years (OSM tile revisions are rare and the
content doesn't change materially). So we cache them on
disk at the XDG cache home:

    ~/.cache/open-dive-log/tiles/{z}/{x}/{y}.png

On macOS without XDG_CACHE_HOME set, this resolves to
``~/Library/Caches/open-dive-log/tiles/`` (which is what
``platformdirs`` would do, but we don't take the dep).

The cache has two responsibilities:

1. **Lookup** — given a (z, x, y), return the local path if
   the tile is already on disk, else None.
2. **Store** — given a (z, x, y) and a byte payload, write
   the bytes to the right path and return the path.

Network fetching is *not* this module's job. The map widget
uses ``QNetworkAccessManager`` to fetch the bytes from
``tile.openstreetmap.org`` and then calls
:meth:`MapTileCache.store` to persist them. That separation
keeps this module testable without Qt's network stack.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

# OpenStreetMap's public tile server. The standard
# slippy-map URL pattern: /{z}/{x}/{y}.png. We hard-code
# the host here (not a config) because OSM is the only
# source we support in v0; switching to a different tile
# server is a one-line change.
OSM_TILE_URL: Final[str] = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"

# OSM requires attribution on every map that uses their
# tiles. We display this in the bottom-right of the map.
OSM_ATTRIBUTION: Final[str] = "© OpenStreetMap contributors"


def _default_cache_root() -> Path:
    """Return the on-disk cache root, creating it if missing.

    Honors ``$XDG_CACHE_HOME`` (Linux/BSD convention) and
    falls back to ``~/.cache/`` if it's not set. On macOS,
    the ``~/.cache/`` path is conventional but
    ``~/Library/Caches/`` is the OS-native choice; we use
    the former for cross-platform consistency. Users with
    strong macOS-native preferences can set
    ``$XDG_CACHE_HOME=$HOME/Library/Caches``.
    """
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        root = Path(xdg)
    else:
        root = Path.home() / ".cache"
    path = root / "open-dive-log" / "tiles"
    path.mkdir(parents=True, exist_ok=True)
    return path


class MapTileCache:
    """Filesystem-backed cache for slippy-map raster tiles.

    Usage:

        cache = MapTileCache()          # uses ~/.cache/open-dive-log/tiles
        path = cache.lookup(3, 4, 5)    # Path | None
        path = cache.store(3, 4, 5, png_bytes)
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or _default_cache_root()

    @property
    def root(self) -> Path:
        """The on-disk root directory used by this cache."""
        return self._root

    def _path_for(self, z: int, x: int, y: int) -> Path:
        """Compute the on-disk path for a tile.

        The standard slippy-map layout is ``{z}/{x}/{y}.png``.
        We shard by z to keep any one directory from getting
        too large (z=18 has 2^18 = 262144 directories; we
        wouldn't want all of them in one place).
        """
        if not (0 <= z <= 19):
            raise ValueError(f"zoom level out of range: {z}")
        if not (0 <= x < (1 << z)):
            raise ValueError(f"x out of range for z={z}: {x}")
        if not (0 <= y < (1 << z)):
            raise ValueError(f"y out of range for z={z}: {y}")
        return self._root / str(z) / str(x) / f"{y}.png"

    def lookup(self, z: int, x: int, y: int) -> Path | None:
        """Return the local path for a tile if it exists on disk,
        else None. Does not fetch.
        """
        try:
            path = self._path_for(z, x, y)
        except ValueError:
            return None
        return path if path.is_file() else None

    def store(self, z: int, x: int, y: int, payload: bytes) -> Path:
        """Persist a tile's bytes to disk. Returns the path.

        Creates parent directories as needed. Overwrites
        existing files (a tile revision from OSM is treated
        as the new authoritative copy).
        """
        path = self._path_for(z, x, y)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path

    def clear(self) -> int:
        """Delete all cached tiles. Returns the number of files
        removed. Used by tests and by a future
        'Tools > Clear Map Cache' menu action.
        """
        if not self._root.exists():
            return 0
        count = 0
        for p in self._root.rglob("*.png"):
            count += 1
            p.unlink()
        return count

    def size_bytes(self) -> int:
        """Total bytes used by cached tiles. Used by a future
        'Cache: N MB' status-bar indicator.
        """
        if not self._root.exists():
            return 0
        return sum(p.stat().st_size for p in self._root.rglob("*.png"))


def lon_to_tile_x(lon: float, z: int) -> float:
    """Convert a longitude to a fractional tile-x at zoom ``z``.

    The slippy-map convention maps ``[-180, +180]`` to
    ``[0, 2^z]`` in tile space. The result is fractional
    so a marker at exactly the tile boundary doesn't snap
    to a tile edge.
    """
    return (lon + 180.0) / 360.0 * (1 << z)


def lat_to_tile_y(lat: float, z: int) -> float:
    """Convert a latitude to a fractional tile-y at zoom ``z``.

    Uses the standard Web Mercator projection. Latitudes
    above ~85.05° or below ~-85.05° are clamped because
    the projection is undefined at the poles.
    """
    lat = max(min(lat, 85.05112878), -85.05112878)
    import math
    return (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * (1 << z)


def tile_x_to_lon(x: float, z: int) -> float:
    """Inverse of :func:`lon_to_tile_x`."""
    return x / (1 << z) * 360.0 - 180.0


def tile_y_to_lat(y: float, z: int) -> float:
    """Inverse of :func:`lat_to_tile_y`."""
    import math
    n = math.pi - 2.0 * math.pi * y / (1 << z)
    return math.degrees(math.atan(math.sinh(n)))
