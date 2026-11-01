"""Disposable accounts for browser-driven E2E of the enterprise handshake.

Usage:
    python scripts/e2e_ui_fixture.py create
    python scripts/e2e_ui_fixture.py tokens
    python scripts/e2e_ui_fixture.py cleanup

The accounts use a fixed local-only password and are deleted by ``cleanup``
together with every task they created.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.security import create_access_token, hash_password
from app.db.session import SessionLocal
from app.models import (
    CustomerProfile,
    Skill,
    Task,
    User,
    Wallet,
    WorkerProfile,
    WorkerSkill,
)

CUSTOMER_EMAIL = "e2e-ui-customer@test.dev"
WORKER_EMAIL = "e2e-ui-worker@test.dev"
PASSWORD = "E2e@1234"


def _delete_existing(db) -> None:
    users = db.scalars(
        select(User).where(User.email.in_([CUSTOMER_EMAIL, WORKER_EMAIL]))
    ).all()
    for user in users:
        task_ids = [
            t.id
            for t in db.scalars(
                select(Task).where(
                    (Task.customer_id == user.id) | (Task.assigned_worker_id == user.id)
                )
            ).all()
        ]
        for task_id in task_ids:
            task = db.get(Task, task_id)
            if task is not None:
                db.delete(task)
                db.flush()
        db.delete(user)
        db.flush()


def create() -> None:
    db = SessionLocal()
    try:
        _delete_existing(db)

        customer = User(
            email=CUSTOMER_EMAIL,
            phone="+919900000101",
            full_name="E2E UI Customer",
            password_hash=hash_password(PASSWORD),
            role="CUSTOMER",
            city="Belagavi",
            is_active=True,
            is_email_verified=True,
        )
        worker = User(
            email=WORKER_EMAIL,
            phone="+919900000102",
            full_name="E2E UI Runner",
            password_hash=hash_password(PASSWORD),
            role="WORKER",
            city="Belagavi",
            is_active=True,
            is_email_verified=True,
        )
        db.add_all([customer, worker])
        db.flush()

        db.add(Wallet(user_id=customer.id, balance=5000, total_earned=0, total_spent=0))
        db.add(Wallet(user_id=worker.id, balance=0, total_earned=0, total_spent=0))
        db.add(
            CustomerProfile(
                user_id=customer.id,
                area="Hanji Nagar",
                default_latitude=15.8497,
                default_longitude=74.4977,
            )
        )
        worker_profile = WorkerProfile(
            user_id=worker.id,
            city="Belagavi",
            area="Hanji Nagar",
            latitude=15.8497,
            longitude=74.4977,
            experience_years=3,
            languages="English, Hindi",
            bio="E2E runner for the dual-OTP handshake.",
            is_online=True,
            is_verified=True,
            verification_status="APPROVED",
            working_radius_km=10.0,
        )
        db.add(worker_profile)
        db.flush()
        skill = db.scalar(select(Skill).where(Skill.slug == "document_submission"))
        if skill is not None:
            db.add(
                WorkerSkill(
                    worker_profile_id=worker_profile.id,
                    skill_id=skill.id,
                    experience_level="expert",
                )
            )
        db.commit()
        print(f"customer_token={create_access_token(customer.id, customer.role)}")
        print(f"worker_token={create_access_token(worker.id, worker.role)}")
        print(f"customer_id={customer.id}")
        print(f"worker_id={worker.id}")
    finally:
        db.close()


def tokens() -> None:
    db = SessionLocal()
    try:
        for email in (CUSTOMER_EMAIL, WORKER_EMAIL):
            user = db.scalar(select(User).where(User.email == email))
            if user is None:
                raise SystemExit(f"missing fixture user {email}; run create first")
            print(f"{user.role.lower()}_token={create_access_token(user.id, user.role)}")
            print(f"{user.role.lower()}_id={user.id}")
    finally:
        db.close()


def cleanup() -> None:
    db = SessionLocal()
    try:
        _delete_existing(db)
        db.commit()
        print("fixture cleaned")
    finally:
        db.close()


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "create"
    if command == "create":
        create()
    elif command == "tokens":
        tokens()
    elif command == "cleanup":
        cleanup()
    else:
        raise SystemExit(f"unknown command {command}")
