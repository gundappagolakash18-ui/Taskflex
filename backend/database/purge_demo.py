"""One-off maintenance script: purge every demo/test account and all business
content from the database so the app can go live with only real accounts.

Kept: the real accounts listed in ``KEEP_EMAILS`` (their wallets and profile
counters are reset to zero), plus reference data — ``skills`` and
``system_settings`` are untouched.

Run standalone from backend/ against whatever DATABASE_URL points at::

    python -m database.purge_demo

Idempotent — running it again on an already-clean database is a no-op.
"""
from __future__ import annotations

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.models import (
    AuditLog,
    Conversation,
    CustomerProfile,
    Dispute,
    EmailOtp,
    Message,
    Notification,
    Payment,
    Rating,
    Review,
    SavedLocation,
    Task,
    TaskAssignment,
    TaskLocation,
    TaskOffer,
    TaskRequirement,
    TaskStatusHistory,
    Transaction,
    User,
    VerificationDocument,
    Wallet,
    WorkerAvailability,
    WorkerProfile,
    WorkerSkill,
)

KEEP_EMAILS = (
    "admin@taskflex.dev",
    "gundappagolakash18@gmail.com",
    "kohliviraaaat18@gmail.com",
)

# Content tables wiped completely (children before parents).
CONTENT_MODELS = (
    Message,
    Conversation,
    Notification,
    AuditLog,
    Transaction,
    Dispute,
    Rating,
    Review,
    TaskOffer,
    TaskAssignment,
    TaskStatusHistory,
    TaskLocation,
    TaskRequirement,
    Payment,
    Task,
    VerificationDocument,
    SavedLocation,
    EmailOtp,
)


def _count(db: Session, model) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def purge_demo_data(db: Session) -> dict:
    before = {
        "users": _count(db, User),
        "tasks": _count(db, Task),
        "payments": _count(db, Payment),
        "conversations": _count(db, Conversation),
        "messages": _count(db, Message),
        "notifications": _count(db, Notification),
        "transactions": _count(db, Transaction),
        "verification_documents": _count(db, VerificationDocument),
    }

    kept_ids = list(db.scalars(select(User.id).where(User.email.in_(KEEP_EMAILS))).all())
    missing = set(KEEP_EMAILS) - set(db.scalars(select(User.email).where(User.email.in_(KEEP_EMAILS))).all())
    if missing:
        print(f"WARNING: keep-list emails not found in this database: {sorted(missing)}")
    kept_users = db.scalars(select(User).where(User.id.in_(kept_ids))).all()
    print("Keeping accounts:")
    for user in kept_users:
        print(f"  {user.email}  ({user.role}, {user.full_name})")

    doomed_ids = list(db.scalars(select(User.id).where(User.id.notin_(kept_ids))).all())
    doomed_profiles = list(
        db.scalars(select(WorkerProfile.id).where(WorkerProfile.user_id.in_(doomed_ids))).all()
    ) if doomed_ids else []

    # 1 — all business content, regardless of owner (everything here is demo data).
    deleted_content: dict[str, int] = {}
    for model in CONTENT_MODELS:
        result = db.execute(delete(model))
        deleted_content[model.__tablename__] = result.rowcount or 0

    # 2 — account-owned extras for the accounts being removed.
    if doomed_ids:
        deleted_content["worker_skills"] = db.execute(
            delete(WorkerSkill).where(WorkerSkill.worker_profile_id.in_(doomed_profiles))
        ).rowcount or 0
        deleted_content["worker_availability"] = db.execute(
            delete(WorkerAvailability).where(WorkerAvailability.worker_profile_id.in_(doomed_profiles))
        ).rowcount or 0
        deleted_content["worker_profiles"] = db.execute(
            delete(WorkerProfile).where(WorkerProfile.user_id.in_(doomed_ids))
        ).rowcount or 0
        deleted_content["customer_profiles"] = db.execute(
            delete(CustomerProfile).where(CustomerProfile.user_id.in_(doomed_ids))
        ).rowcount or 0
        deleted_content["wallets"] = db.execute(
            delete(Wallet).where(Wallet.user_id.in_(doomed_ids))
        ).rowcount or 0
        deleted_users = db.execute(delete(User).where(User.id.in_(doomed_ids))).rowcount or 0
    else:
        deleted_users = 0

    # 3 — reset the kept accounts to a clean slate.
    db.execute(
        update(Wallet)
        .where(Wallet.user_id.in_(kept_ids))
        .values(balance=0.0, total_earned=0.0, total_spent=0.0)
    )
    db.execute(
        update(WorkerProfile)
        .where(WorkerProfile.user_id.in_(kept_ids))
        .values(
            total_earnings=0.0,
            completed_tasks_count=0,
            cancelled_tasks_count=0,
            rating_average=0.0,
            rating_count=0,
            is_online=False,
        )
    )
    db.execute(
        update(CustomerProfile)
        .where(CustomerProfile.user_id.in_(kept_ids))
        .values(total_tasks_posted=0, total_spent=0.0)
    )

    # Make sure every kept account has a wallet row.
    wallet_owners = set(db.scalars(select(Wallet.user_id).where(Wallet.user_id.in_(kept_ids))).all())
    for user in kept_users:
        if user.id not in wallet_owners:
            db.add(Wallet(user_id=user.id, balance=0.0, total_earned=0.0, total_spent=0.0))

    db.flush()
    after = {
        "users": _count(db, User),
        "tasks": _count(db, Task),
        "payments": _count(db, Payment),
        "conversations": _count(db, Conversation),
        "messages": _count(db, Message),
        "notifications": _count(db, Notification),
        "transactions": _count(db, Transaction),
        "verification_documents": _count(db, VerificationDocument),
    }
    return {
        "kept": [u.email for u in kept_users],
        "deleted_users": deleted_users,
        "deleted_content": deleted_content,
        "before": before,
        "after": after,
    }


def main() -> None:
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        summary = purge_demo_data(db)
        db.commit()
        print()
        print("Deleted rows:")
        for table, count in summary["deleted_content"].items():
            if count:
                print(f"  {table}: {count}")
        print(f"  users: {summary['deleted_users']}")
        print()
        print(f"Row counts  before -> after: {summary['before']} -> {summary['after']}")
        print("Purge complete.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
