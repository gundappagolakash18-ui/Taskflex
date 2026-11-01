from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.core.responses import success_response
from app.models import User
from app.services.location_service import get_geocoder, map_embed_url
from pydantic import BaseModel, Field

router = APIRouter(prefix="/location", tags=["location"])


class GeocodeRequest(BaseModel):
    query: str = Field(min_length=2, max_length=300)


@router.post("/geocode")
async def geocode(
    payload: GeocodeRequest,
    user: User = Depends(get_current_user),
):
    geocoder = get_geocoder()
    result = await geocoder.geocode(payload.query)
    if result is None:
        return success_response({"result": None}, message="No matching location found.")
    return success_response(
        {
            "result": {
                "display_name": result.display_name,
                "latitude": result.latitude,
                "longitude": result.longitude,
                "provider": result.provider,
                "map_embed_url": map_embed_url(result.latitude, result.longitude),
            }
        }
    )


@router.get("/map-url")
def map_url(
    latitude: float,
    longitude: float,
    zoom: int = 15,
    user: User = Depends(get_current_user),
):
    return success_response({"url": map_embed_url(latitude, longitude, zoom)})
