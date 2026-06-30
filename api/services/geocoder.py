import httpx

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"


async def reverse_geocode(lat: float, lon: float) -> str | None:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            NOMINATIM_URL,
            params={"lat": lat, "lon": lon, "format": "jsonv2", "accept-language": "ru"},
            headers={"User-Agent": "fuel-monitor/1.0"},
        )
        r.raise_for_status()
        addr = r.json().get("address", {})
        return addr.get("city") or addr.get("town") or addr.get("village")
