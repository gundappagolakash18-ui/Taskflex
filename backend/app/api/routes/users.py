from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_customer
from app.api.serializers import serialize_auth_user
from app.db.session import get_db
from app.core.exceptions import ConflictException, NotFoundException
from app.core.responses import success_response
from app.models import AffinityType, SavedLocation, User
from app.repositories import PaymentRepository
from app.schemas.user import SavedLocationCreate, SavedLocationOut, UserUpdate, WalletOut
from app.services import AffinityService

router = APIRouter(tags=["users"])


@router.get("/users/me")
def get_profile(user: User = Depends(get_current_user)):
    return success_response({"user": serialize_auth_user(user)})


@router.patch("/users/me")
def update_profile(
    payload: UserUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return success_response({"user": serialize_auth_user(user)}, message="Profile updated.")


@router.get("/users/me/wallet")
def get_wallet(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    repo = PaymentRepository(db)
    wallet = repo.ensure_wallet(user.id)
    return success_response({"wallet": WalletOut.model_validate(wallet).model_dump()})


@router.get("/users/me/transactions")
def list_transactions(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    page: int = 1,
    page_size: int = 20,
):
    repo = PaymentRepository(db)
    items, total = repo.transactions_for(user.id, page=page, page_size=page_size)
    from app.schemas.user import TransactionOut

    data = [TransactionOut.model_validate(t).model_dump(mode="json") for t in items]
    return success_response({"items": data, "total": total, "page": page, "page_size": page_size})


@router.get("/users/me/locations")
def list_locations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(SavedLocation).filter(SavedLocation.user_id == user.id).order_by(SavedLocation.created_at).all()
    data = [SavedLocationOut.model_validate(r).model_dump(mode="json") for r in rows]
    return success_response({"items": data})


@router.post("/users/me/locations", status_code=201)
def create_location(
    payload: SavedLocationCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    exists = (
        db.query(SavedLocation)
        .filter(SavedLocation.user_id == user.id, SavedLocation.label == payload.label)
        .one_or_none()
    )
    if exists:
        raise ConflictException(f"You already have a saved location named '{payload.label}'.")
    row = SavedLocation(user_id=user.id, **payload.model_dump())
    if payload.is_default:
        for other in db.query(SavedLocation).filter(SavedLocation.user_id == user.id):
            other.is_default = False
    db.add(row)
    db.commit()
    db.refresh(row)
    return success_response({"location": SavedLocationOut.model_validate(row).model_dump(mode="json")},
                            message="Location saved.", status_code=201)


@router.delete("/users/me/locations/{location_id}")
def delete_location(
    location_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(SavedLocation).filter(SavedLocation.id == location_id).one_or_none()
    if row is None or row.user_id != user.id:
        raise NotFoundException("Saved location not found.")
    db.delete(row)
    db.commit()
    return success_response({"deleted": True}, message="Location removed.")


# ---------- preferred / blacklisted workers ----------


@router.get("/users/me/worker-affinities")
def list_worker_affinities(
    user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    data = AffinityService(db).list_for_customer(user)
    return success_response(data)


@router.post("/users/workers/{worker_id}/prefer")
def prefer_worker(
    worker_id: str,
    user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    AffinityService(db).set_affinity(user, worker_id, AffinityType.PREFERRED.value)
    return success_response(
        {"worker_id": worker_id, "affinity_type": AffinityType.PREFERRED.value},
        message="Preferred worker saved — they'll be matched first for your tasks.",
    )


@router.delete("/users/workers/{worker_id}/prefer")
def remove_preferred_worker(
    worker_id: str,
    user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    removed = AffinityService(db).remove_affinity(user, worker_id)
    return success_response(
        {"worker_id": worker_id, "removed": removed}, message="Preference removed."
    )


@router.post("/users/workers/{worker_id}/blacklist")
def blacklist_worker(
    worker_id: str,
    user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    AffinityService(db).set_affinity(user, worker_id, AffinityType.BLACKLISTED.value)
    return success_response(
        {"worker_id": worker_id, "affinity_type": AffinityType.BLACKLISTED.value},
        message="Worker blocked. They won't be offered your tasks again.",
    )


@router.delete("/users/workers/{worker_id}/blacklist")
def unblacklist_worker(
    worker_id: str,
    user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    removed = AffinityService(db).remove_affinity(user, worker_id)
    return success_response(
        {"worker_id": worker_id, "removed": removed}, message="Worker unblocked."
    )
