import httpx
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)

async def reverse_geocode(lat: float, lng: float) -> str:
    """
    Utility to convert Lat/Lng to a human-readable address using Mappls API.
    Replicates the functionality of `geocoding.js`.
    """
    api_key = settings.NEXT_PUBLIC_MAPPLS_API_KEY or "c0ae557754e8913f692841c11b9d979c"
    if not api_key:
        logger.warning("NEXT_PUBLIC_MAPPLS_API_KEY is not set.")
        return "Unknown Location"

    url = f"https://apis.mappls.com/advancedmaps/v1/{api_key}/rev_geocode?lat={lat}&lng={lng}"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10.0)
            response.raise_for_status()
            data = response.json()

            # Mappls returns an array in "results". We want the "formatted_address"
            results = data.get("results", [])
            if results and len(results) > 0:
                return results[0].get("formatted_address", "Address not found")
            return "Unknown Location"
    except Exception as e:
        logger.error(f"[ReverseGeocode] Error: {str(e)}")
        return "Failed to fetch address"
