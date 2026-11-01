"""Seed the database with demo data when it is empty.

``main.py`` imports :func:`seed_if_empty` and calls it during startup when
``settings.seed_on_start`` is enabled.
"""
from __future__ import annotations

from sqlalchemy import func, select

from app.core.logging import get_logger

logger = get_logger("db.seed_runner")


def seed_if_empty() -> bool:
    """Create tables if needed and load demo data when the users table is empty."""
    from app.db.init_db import init_db
    from app.db.session import SessionLocal

    init_db()
    db = SessionLocal()
    try:
        from app.models import User
        from database.seed import seed_demo_data

        user_count = db.scalar(select(func.count()).select_from(User))
        if user_count:
            logger.info("seed_skipped_users_present", extra_fields={"user_count": int(user_count)})
            return False

        summary = seed_demo_data(db)
        db.commit()
        logger.info("seed_complete", extra_fields=summary)
        return True
    except Exception:
        db.rollback()
        logger.exception("seed_failed")
        raise
    finally:
        db.close()
