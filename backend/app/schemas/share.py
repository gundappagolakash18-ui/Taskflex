from pydantic import BaseModel, Field


class ShareLinkCreate(BaseModel):
    expires_in_hours: int | None = Field(default=None, ge=1, le=8760)
    rotate: bool = False
