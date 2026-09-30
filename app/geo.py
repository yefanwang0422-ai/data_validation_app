"""
Geocoding utilities for Business Insights geographic flow maps.

Goal:
- Convert address-like fields (city/state/postal/country) into latitude/longitude.
- Cache results to avoid repeated external calls and to improve performance.

Implementation notes:
- Uses OpenStreetMap Nominatim via geopy (no API key) by default.
- Respects a conservative rate limit (1 req/sec).
- Cache is stored per-project under data/run_logs/{project_id}/geocode_cache.json.

If you need a different geocoder (Google, Mapbox, etc.), swap the backend in `geocode_place`.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim


@dataclass(frozen=True)
class GeoInput:
    """Normalized input used for caching geocode results."""
    address_line_1: str = ""
    address_line_2: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""
    country: str = ""

    def cache_key(self) -> str:
        parts = [
            self.address_line_1.strip().lower(),
            self.address_line_2.strip().lower(),
            self.city.strip().lower(),
            self.state.strip().lower(),
            self.postal_code.strip().lower(),
            self.country.strip().lower(),
        ]
        # Keep key readable; JSON keys are fine for our use-case.
        return "|".join(parts)


def _cache_path(project_id: str) -> Path:
    # Use run_logs as a general per-project cache location (already exists in repo structure)
    return Path("data") / "run_logs" / project_id / "geocode_cache.json"


def load_geocode_cache(project_id: str) -> Dict[str, Dict[str, Any]]:
    path = _cache_path(project_id)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
        return {}
    except Exception:
        return {}


def save_geocode_cache(project_id: str, cache: Dict[str, Dict[str, Any]]) -> None:
    path = _cache_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, indent=2, ensure_ascii=False, default=str)


# Create a single geocoder instance (safe for typical FastAPI usage here)
_GEOCODER = Nominatim(user_agent="network-design-data-prep/1.0")
# Nominatim usage policy: keep requests modest. 1 req/sec is a safe default.
_GEOCODE = RateLimiter(_GEOCODER.geocode, min_delay_seconds=1.0, swallow_exceptions=True)


def geocode_place(query: str) -> Optional[Tuple[float, float]]:
    """Geocode a free-text query string (e.g., 'Austin, TX, USA')."""
    if not query.strip():
        return None
    loc = _GEOCODE(query)
    if not loc:
        return None
    try:
        return float(loc.latitude), float(loc.longitude)
    except Exception:
        return None


def geocode_geo_input(project_id: str, gi: GeoInput) -> Optional[Tuple[float, float]]:
    """Geocode a GeoInput with caching."""
    key = gi.cache_key()
    cache = load_geocode_cache(project_id)
    if key in cache:
        rec = cache[key]
        if rec.get("lat") is None or rec.get("lon") is None:
            return None
        return float(rec["lat"]), float(rec["lon"])

    # Build a query preferring the most stable fields first.
    parts = [gi.city, gi.state, gi.postal_code, gi.country]
    query = ", ".join([p for p in parts if p and str(p).strip()])

    coords = geocode_place(query)
    cache[key] = {
        "query": query,
        "lat": coords[0] if coords else None,
        "lon": coords[1] if coords else None,
        "ts": int(time.time()),
    }
    save_geocode_cache(project_id, cache)
    return coords
