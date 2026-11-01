from pydantic import BaseModel, Field


class ExpenseDecisionRequest(BaseModel):
    """Optional note recorded with an approve/reject decision."""

    model_config = {
        "json_schema_extra": {"example": {"note": "Parking receipt looks correct."}}
    }

    note: str | None = Field(None, max_length=500)
