from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse


def success_response(data: Any = None, message: str | None = None, status_code: int = status.HTTP_200_OK) -> dict:
    body: dict[str, Any] = {"success": True, "data": data}
    if message:
        body["message"] = message
    return JSONResponse(status_code=status_code, content=body)


def paginated_response(items: list, total: int, page: int, page_size: int) -> dict:
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "success": True,
            "data": {
                "items": items,
                "pagination": {
                    "total": total,
                    "page": page,
                    "page_size": page_size,
                    "pages": (total + page_size - 1) // page_size if page_size else 0,
                },
            },
        },
    )
