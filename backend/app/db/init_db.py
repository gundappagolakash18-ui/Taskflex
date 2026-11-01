"""Create all database tables from the SQLAlchemy metadata."""
from __future__ import annotations

from app.core.logging import get_logger

logger = get_logger("db.init")


def init_db() -> None:
    import app.models  # noqa: F401 -- register all mappers on Base.metadata
    from app.db.base import Base
    from app.db.session import engine

    Base.metadata.create_all(bind=engine)
    logger.info("database_schema_ready")
