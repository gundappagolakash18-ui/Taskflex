from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.core.responses import success_response
from app.models import User
from app.schemas.rating import RatingCreate, RatingOut, ReviewOut
from app.services import RatingService, TaskService

router = APIRouter(tags=["ratings"])


@router.post("/ratings", status_code=201)
def submit_rating(
    payload: RatingCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task_service = TaskService(db)
    task = task_service.get_task_or_404(payload.task_id)
    service = RatingService(db)
    rating, tip_checkout = service.rate_task(task, user, payload)
    data = {"rating": RatingOut.model_validate(rating).model_dump(mode="json")}
    if tip_checkout is not None:
        data["payment"] = tip_checkout
    return success_response(
        data,
        message=(
            "Thanks for rating! Complete the tip checkout to send your gratuity."
            if tip_checkout is not None
            else "Thanks for rating your experience!"
        ),
        status_code=201,
    )


@router.get("/tasks/{task_id}/ratings")
def task_ratings(
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task_service = TaskService(db)
    task = task_service.get_task_or_404(task_id)
    service = RatingService(db)
    ratings = service.ratings_for_task(task, user)
    return success_response(
        {"items": [RatingOut.model_validate(r).model_dump(mode="json") for r in ratings]}
    )


@router.get("/workers/{worker_user_id}/reviews")
def worker_reviews(
    worker_user_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    service = RatingService(db)
    items, total = service.reviews_for(worker_user_id, page, page_size)
    data = []
    for review in items:
        out = ReviewOut.model_validate(review).model_dump(mode="json")
        out["author_name"] = review.author.full_name if review.author else "TaskFlex user"
        data.append(out)
    return success_response({"items": data, "total": total, "page": page, "page_size": page_size})


@router.get("/workers/{worker_user_id}/rating-summary")
def worker_rating_summary(worker_user_id: str, db: Session = Depends(get_db)):
    service = RatingService(db)
    return success_response({"summary": service.worker_rating_summary(worker_user_id)})
