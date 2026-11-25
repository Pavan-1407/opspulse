"""Repository pattern.

`BaseRepository` is the abstract contract the service layer depends on; `SqlRepository`
is the SQLAlchemy implementation. Services never check concrete types (no isinstance()
branching) - swapping storage means writing another implementation of the same interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

T = TypeVar("T")


class BaseRepository(ABC, Generic[T]):
    @abstractmethod
    def get(self, id_: int) -> T | None: ...

    @abstractmethod
    def list(self, **filters: Any) -> Sequence[T]: ...

    @abstractmethod
    def add(self, obj: T) -> T: ...


class SqlRepository(BaseRepository[T]):
    model: type[T]

    def __init__(self, session: Session):
        self.session = session

    def get(self, id_: int) -> T | None:
        return self.session.get(self.model, id_)

    def list(self, **filters: Any) -> Sequence[T]:
        stmt = select(self.model)
        for k, v in filters.items():
            stmt = stmt.where(getattr(self.model, k) == v)
        return self.session.execute(stmt).unique().scalars().all()

    def add(self, obj: T) -> T:
        self.session.add(obj)
        self.session.flush()
        return obj
