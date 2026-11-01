from typing import Generic, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, db: Session):
        self.db = db

    def get(self, entity_id: str) -> ModelT | None:
        return self.db.get(self.model, entity_id)

    def add(self, entity: ModelT) -> ModelT:
        self.db.add(entity)
        self.db.flush()
        return entity

    def delete(self, entity: ModelT) -> None:
        self.db.delete(entity)
        self.db.flush()

    def list(self, stmt: Select, page: int = 1, page_size: int = 20) -> tuple[list[ModelT], int]:
        count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
        total = self.db.execute(count_stmt).scalar_one()
        rows = self.db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).scalars().all()
        return list(rows), total
