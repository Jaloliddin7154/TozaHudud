import logging
import time

import aiohttp

from config import GEOCODE_CACHE_TTL_SEC, GEOCODE_CACHE_ROUND_DIGITS

logger = logging.getLogger(__name__)

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
_HEADERS = {"User-Agent": "toza_hudud_bot_v1"}
_TIMEOUT = aiohttp.ClientTimeout(total=6)

_cache: dict[tuple[float, float], tuple[float, dict]] = {}


def _cache_key(lat: float, lon: float) -> tuple[float, float]:
    return (
        round(lat, GEOCODE_CACHE_ROUND_DIGITS),
        round(lon, GEOCODE_CACHE_ROUND_DIGITS),
    )


async def reverse_geocode(lat: float, lon: float) -> dict:
    """
    Returns region, district, and full address from GPS coordinates.
    Uses aiohttp for true async HTTP — no threads, cancellable at any point.
    """
    key = _cache_key(lat, lon)
    now = time.time()

    cached = _cache.get(key)
    if cached and (now - cached[0]) < GEOCODE_CACHE_TTL_SEC:
        logger.debug("Geocode cache hit for %s", key)
        return cached[1]

    params = {
        "lat": lat,
        "lon": lon,
        "format": "json",
        "accept-language": "uz",
        "zoom": 14,
    }

    try:
        async with aiohttp.ClientSession(headers=_HEADERS, timeout=_TIMEOUT) as session:
            async with session.get(_NOMINATIM_URL, params=params) as resp:
                if resp.status != 200:
                    logger.warning("Nominatim returned HTTP %s", resp.status)
                    return {"region": "", "district": "", "address": "Noma'lum"}

                data = await resp.json(content_type=None)

        address = data.get("address", {})
        region = (
            address.get("state")
            or address.get("province")
            or address.get("region")
            or ""
        )
        district = (
            address.get("county")
            or address.get("city")
            or address.get("city_district")
            or address.get("town")
            or address.get("suburb")
            or ""
        )
        street = (
            address.get("road")
            or address.get("pedestrian")
            or address.get("footway")
            or address.get("neighbourhood")
            or address.get("quarter")
            or ""
        )
        address_str = ", ".join(p for p in [region, district, street] if p) or "Noma'lum"
        result = {
            "region": region,
            "district": district,
            "address": address_str,
        }
        _cache[key] = (now, result)
        return result

    except Exception as e:
        logger.error("Reverse geocode error: %s", e)
        return {"region": "", "district": "", "address": "Noma'lum"}
