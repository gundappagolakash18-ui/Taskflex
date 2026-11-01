from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginationParams(BaseModel):
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


class PaginationMeta(BaseModel):
    total: int
    page: int
    page_size: int
    pages: int


class PaginatedData(BaseModel, Generic[T]):
    items: list[T]
    pagination: PaginationMeta


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorEnvelope(BaseModel):
    success: bool = False
    error: ErrorDetail


class SuccessEnvelope(BaseModel):
    success: bool = True
    data: Any = None
    message: str | None = None


def paginate_meta(total: int, page: int, page_size: int) -> PaginationMeta:
    return PaginationMeta(
        total=total, page=page, page_size=page_size, pages=(total + page_size - 1) // page_size
    )


def paginate(items: list[T], page: int = 1, page_size: int = 20) -> tuple[list[T], int]:
    """Slice an already-sorted list into a page, returning (items, total)."""
    total = len(items)
    start = (max(page, 1) - 1) * page_size
    return items[start : start + page_size], total
