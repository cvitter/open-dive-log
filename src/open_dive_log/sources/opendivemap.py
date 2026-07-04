"""OpenDiveMap API client.

Free, public, ODbL-licensed dive site data. No auth required.
Docs: https://opendivemap.com/docs
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

API_BASE = "https://api.opendivemap.com/v1"
DEFAULT_USER_AGENT = "open-dive-log/0.0.1 (https://github.com/craigvitter/open-dive-log)"
DEFAULT_PAGE_SIZE = 1000  # API caps at 1000 per page


@dataclass(frozen=True, slots=True)
class ODMFeature:
    external_id: str
    name: str
    country_code: str | None
    country_name: str | None
    latitude: float | None
    longitude: float | None
    sea_mrgid: int | None
    environment: str | None
    topologies: tuple[str, ...]
    max_depth: int | None
    entry: str | None
    description: str | None
    description_wildlife: str | None
    tags: dict[str, Any]
    external_url: str | None


class OpenDiveMapError(RuntimeError):
    """Raised on any unrecoverable client error (non-2xx after retries, network)."""


def _http_json(url: str, *, user_agent: str, timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "application/geo+json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        raise OpenDiveMapError(f"HTTP {e.code} on {url}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise OpenDiveMapError(f"Network error on {url}: {e.reason}") from e
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        raise OpenDiveMapError(f"Invalid JSON from {url}: {e}") from e


def _feature_to_odm(feature: dict[str, Any]) -> ODMFeature:
    geom = feature.get("geometry") or {}
    coords = geom.get("coordinates") or [None, None]
    # GeoJSON is [lon, lat]
    lon, lat = (coords + [None, None])[:2]

    props = feature.get("properties") or {}
    tags = props.get("tags") or {}
    ext_id = props.get("id", "")
    external_url = f"https://opendivemap.com/explore?site={ext_id}" if ext_id else None

    return ODMFeature(
        external_id=ext_id,
        name=props.get("name", ""),
        country_code=props.get("country_code"),
        country_name=props.get("country_name"),
        latitude=float(lat) if lat is not None else None,
        longitude=float(lon) if lon is not None else None,
        sea_mrgid=props.get("sea_mrgid"),
        environment=props.get("environment"),
        topologies=tuple(props.get("topologies") or ()),
        max_depth=props.get("max_depth"),
        entry=props.get("entry"),
        description=_clean_str(tags.get("description")),
        description_wildlife=_clean_str(tags.get("description_wildlife")),
        tags=tags,
        external_url=external_url,
    )


def _clean_str(value: Any) -> str | None:
    """Normalize a tag value: strip, treat empty/whitespace-only as None."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    stripped = value.strip()
    return stripped or None


def iter_sites(
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout: float = 30.0,
) -> Iterator[ODMFeature]:
    """Yield every site from /v1/sites, following `links[].next` pagination.

    Raises OpenDiveMapError on transport or JSON errors. Callers should
    commit per-site (or per-page) to make this safe to interrupt and resume.
    """
    if page_size > 1000:
        # API caps at 1000; don't try to be clever.
        page_size = 1000

    url: str | None = f"{API_BASE}/sites?limit={page_size}"
    while url is not None:
        data = _http_json(url, user_agent=user_agent, timeout=timeout)
        for feature in data.get("features", []):
            yield _feature_to_odm(feature)
        # Follow the `next` link if present.
        next_link = next(
            (l["href"] for l in data.get("links", []) if l.get("rel") == "next"),
            None,
        )
        url = next_link


def get_stats(*, user_agent: str = DEFAULT_USER_AGENT, timeout: float = 30.0) -> dict[str, Any]:
    """GET /stats — useful for pre-flight logs."""
    return _http_json(f"{API_BASE}/stats", user_agent=user_agent, timeout=timeout)
