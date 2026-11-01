"""Shared pytest fixtures. Environment variables are set BEFORE any app import
so that the Settings singleton and the SQLAlchemy engine bind to the test
database, not a developer's local database."""

import itertools
import os
import pathlib
import shutil
from datetime import time

_TEST_DIR = pathlib.Path(__file__).resolve().parent
_TEST_DB_FILE = _TEST_DIR / ".pytest_taskflex.db"
_TEST_UPLOAD_DIR = _TEST_DIR / ".pytest_uploads"
if _TEST_DB_FILE.exists():
    _TEST_DB_FILE.unlink()
shutil.rmtree(_TEST_UPLOAD_DIR, ignore_errors=True)

os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_FILE.as_posix()}"
os.environ["UPLOAD_DIR"] = str(_TEST_UPLOAD_DIR)
os.environ["AI_PROVIDER"] = "mock"
os.environ["PAYMENT_PROVIDER"] = "mock"
os.environ["EMAIL_PROVIDER"] = "smtp"
os.environ["SMTP_USER"] = "taskflex-tests@example.com"
os.environ["SMTP_PASSWORD"] = "test-only-app-password"
os.environ["SEED_ON_START"] = "false"
os.environ["REDIS_URL"] = ""
# Never call the public OSRM server from tests; the snap layer is covered by
# unit tests with a stubbed HTTP client.
os.environ["TRACKING_MAP_MATCH_ENABLED"] = "false"

import bcrypt as _bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import engine
from app.main import app
from app.models import (
    CustomerProfile,
    Skill,
    User,
    Wallet,
    WorkerAvailability,
    WorkerProfile,
    WorkerSkill,
)

# bcrypt with 12 rounds is intentionally slow; tests do not need that cost.
_original_gensalt = _bcrypt.gensalt
_bcrypt.gensalt = lambda rounds=12, prefix=b"2b": _original_gensalt(rounds=4, prefix=prefix)

TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

_counter = itertools.count(1)


@pytest.fixture(autouse=True)
def database(monkeypatch):
    _reset_auth_rate_limiter()
    # Replace the `secrets` module reference INSIDE auth_service only — patching
    # secrets.randbelow directly would leak into every other module (e.g. the
    # 4-digit task handshake OTPs) because modules share the same object.
    import types

    monkeypatch.setattr(
        "app.services.auth_service.secrets",
        types.SimpleNamespace(randbelow=lambda _: 123456),
    )
    monkeypatch.setattr("app.services.auth_service.send_email_smtp", lambda *args, **kwargs: True)
    monkeypatch.setattr("app.notifications.channels.send_email_smtp", lambda *args, **kwargs: True)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    shutil.rmtree(_TEST_UPLOAD_DIR, ignore_errors=True)
    yield
    Base.metadata.drop_all(bind=engine)
    shutil.rmtree(_TEST_UPLOAD_DIR, ignore_errors=True)


def _reset_auth_rate_limiter():
    """The in-memory auth rate limiter (20 POSTs/min per IP) persists across
    tests; clear its window so every test starts from a clean slate."""
    from app.middleware import RateLimitMiddleware

    mw = app.middleware_stack
    while mw is not None:
        if isinstance(mw, RateLimitMiddleware):
            mw._hits.clear()
            return
        mw = getattr(mw, "app", None)


@pytest.fixture()
def db():
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client():
    # No context manager: the lifespan (and its seeding) must not run in tests.
    return TestClient(app)


def auth_headers(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id, user.role)}"}


def make_skill(db, name: str, *, category: str = "errand") -> Skill:
    skill = db.query(Skill).filter(Skill.slug == name.lower().replace(" ", "_")).one_or_none()
    if skill:
        return skill
    skill = Skill(name=name, slug=name.lower().replace(" ", "_"), category=category)
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


def make_user(
    db,
    role: str = "CUSTOMER",
    *,
    email: str | None = None,
    full_name: str | None = None,
    city: str = "Belagavi",
    is_active: bool = True,
    is_verified: bool = True,
    is_online: bool = True,
    latitude: float = 15.8497,
    longitude: float = 74.4977,
    radius_km: float = 8.0,
    skills: tuple[str, ...] = (),
) -> User:
    """Create a user (plus wallet/profile) directly in the database."""
    n = next(_counter)
    user = User(
        email=email or f"user{n}@test.dev",
        phone=f"+9198450{n:05d}",
        full_name=full_name or f"Test User {n}",
        password_hash=hash_password("Demo@1234"),
        role=role,
        city=city,
        is_active=is_active,
        is_email_verified=True,
    )
    db.add(user)
    db.flush()
    db.add(Wallet(user_id=user.id, balance=0, total_earned=0, total_spent=0))
    if role == "CUSTOMER":
        db.add(
            CustomerProfile(
                user_id=user.id,
                area="Hanji Nagar",
                default_latitude=latitude,
                default_longitude=longitude,
            )
        )
    elif role == "WORKER":
        profile = WorkerProfile(
            user_id=user.id,
            bio="Reliable errand runner based in Belagavi.",
            city=city,
            area="Hanji Nagar",
            latitude=latitude,
            longitude=longitude,
            experience_years=4,
            languages="English, Kannada, Hindi",
            is_online=is_online,
            is_verified=is_verified,
            verification_status="APPROVED" if is_verified else "PENDING",
            working_radius_km=radius_km,
        )
        db.add(profile)
        db.flush()
        for day in range(7):
            db.add(
                WorkerAvailability(
                    worker_profile_id=profile.id,
                    day_of_week=day,
                    start_time=time(0, 0),
                    end_time=time(23, 59),
                    is_available=True,
                )
            )
        for skill_name in skills:
            skill = make_skill(db, skill_name.replace("_", " ").title())
            db.add(WorkerSkill(worker_profile_id=profile.id, skill_id=skill.id, experience_level="EXPERIENCED"))
    db.commit()
    db.refresh(user)
    return user


def task_payload(**overrides) -> dict:
    payload = {
        "title": "Submit property documents at the sub-registrar office",
        "description": (
            "Collect the stamped affidavit from Hanji Nagar and submit it at the "
            "sub-registrar office before 5 PM today."
        ),
        "task_type": "document_submission",
        "urgency": "normal",
        "scheduled_date": "2026-10-10",
        "scheduled_time": "14:00",
        "estimated_duration_minutes": 90,
        "latitude": 15.8497,
        "longitude": 74.4977,
        "address_text": "12 MG Road, Hanji Nagar, Belagavi",
        "area_name": "Hanji Nagar",
        "city": "Belagavi",
        "budget": 350,
        "required_skills": ["document_submission"],
    }
    payload.update(overrides)
    return payload
