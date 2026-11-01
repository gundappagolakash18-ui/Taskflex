"""Maps/geocoding abstraction.

Real deployments would use Google Maps or MapMyIndia; the default provider
here queries OSM Nominatim (free, keyless, 1 req/s) and falls back to a small
offline gazetteer so demo mode never breaks without internet access.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from app.core.config import settings

logger = logging.getLogger("taskflex.location")

# A handful of seed cities so geocode works offline.
OFFLINE_GAZETTEER: dict[str, tuple[float, float]] = {
    "belagavi": (15.8497, 74.4977),
    "belgaum": (15.8497, 74.4977),
    "bengaluru": (12.9716, 77.5946),
    "bangalore": (12.9716, 77.5946),
    "mumbai": (19.0760, 72.8777),
    "pune": (18.5204, 73.8567),
    "delhi": (28.6139, 77.2090),
    "hyderabad": (17.3850, 78.4867),
    "chennai": (13.0827, 80.2707),
    "kolkata": (22.5726, 88.3639),
}


@dataclass
class GeocodeResult:
    display_name: str
    latitude: float
    longitude: float
    provider: str


class Geocoder(ABC):
    name: str = "base"

    @abstractmethod
    async def geocode(self, query: str) -> GeocodeResult | None: ...


class MockGeocoder(Geocoder):
    """Deterministic offline lookup — never touches the network."""

    name = "mock"

    async def geocode(self, query: str) -> GeocodeResult | None:
        text = (query or "").strip().lower()
        for key, (lat, lng) in OFFLINE_GAZETTEER.items():
            if key in text:
                return GeocodeResult(
                    display_name=query.strip().title(),
                    latitude=lat,
                    longitude=lng,
                    provider=self.name,
                )
        return None


class NominatimGeocoder(Geocoder):
    """OpenStreetMap Nominatim — free, requires a descriptive User-Agent."""

    name = "nominatim"

    def __init__(self, base_url: str | None = None, timeout: float = 6.0):
        self.base_url = base_url or "https://nominatim.openstreetmap.org"
        self.timeout = timeout

    async def geocode(self, query: str) -> GeocodeResult | None:
        if not query or not query.strip():
            return None
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/search",
                    params={"q": query.strip(), "format": "json", "limit": 1},
                    headers={"User-Agent": "TaskFlex/1.0 (demo marketplace)"},
                )
                response.raise_for_status()
                data = response.json()
        except Exception:
            logger.warning("nominatim_geocode_failed query=%s", query[:80])
            return None
        if not data:
            return None
        top = data[0]
        return GeocodeResult(
            display_name=top.get("display_name", query),
            latitude=float(top["lat"]),
            longitude=float(top["lon"]),
            provider=self.name,
        )


class ChainGeocoder(Geocoder):
    """Try providers in order; return the first hit. Nominatim → offline."""

    name = "chain"

    def __init__(self, providers: list[Geocoder] | None = None):
        if settings.maps_provider == "mock":
            self.providers: list[Geocoder] = [MockGeocoder()]
        else:
            self.providers = providers or [NominatimGeocoder(), MockGeocoder()]

    async def geocode(self, query: str) -> GeocodeResult | None:
        for provider in self.providers:
            try:
                result = await provider.geocode(query)
            except Exception:
                logger.exception("geocoder %s crashed", provider.name)
                result = None
            if result is not None:
                return result
        return None


_geocoder: Geocoder | None = None


def get_geocoder() -> Geocoder:
    global _geocoder
    if _geocoder is None:
        _geocoder = ChainGeocoder()
    return _geocoder


def map_embed_url(latitude: float, longitude: float, zoom: int = 15) -> str:
    """Keyless OpenStreetMap embed for the task-detail iframe."""
    delta = 0.008
    bbox = f"{longitude - delta}%2C{latitude - delta}%2C{longitude + delta}%2C{latitude + delta}"
    return (
        "https://www.openstreetmap.org/export/embed.html"
        f"?bbox={bbox}&layer=mapnik&marker={latitude}%2C{longitude}"
    )
