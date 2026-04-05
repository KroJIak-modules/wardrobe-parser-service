"""
Base Repository pattern for data access layer.
"""

from typing import TypeVar, Generic, Optional
from sqlalchemy.orm import Session

T = TypeVar("T")


class BaseRepository(Generic[T]):
    """Generic base repository for all domain entities."""

    def __init__(self, session: Session, model_class: type[T]):
        self.session = session
        self.model_class = model_class

    def add(self, entity: T) -> T:
        """Add entity to session (does not commit)."""
        self.session.add(entity)
        return entity

    def create(self, **kwargs) -> T:
        """Create and add entity to session."""
        entity = self.model_class(**kwargs)
        self.session.add(entity)
        return entity

    def get_by_id(self, entity_id: int) -> Optional[T]:
        """Get entity by primary key ID."""
        return self.session.query(self.model_class).filter(
            self.model_class.id == entity_id
        ).first()

    def get_by_id_string(self, entity_id: str) -> Optional[T]:
        """Get entity by string ID (UUID)."""
        return self.session.query(self.model_class).filter(
            self.model_class.id == entity_id
        ).first()

    def update(self, entity: T, **kwargs) -> T:
        """Update entity with provided fields."""
        for key, value in kwargs.items():
            if hasattr(entity, key):
                setattr(entity, key, value)
        return entity

    def delete(self, entity: T) -> None:
        """Delete entity from session (hard delete)."""
        self.session.delete(entity)

    def query(self):
        """Get raw query builder for complex queries."""
        return self.session.query(self.model_class)

    def flush(self) -> None:
        """Flush pending changes to database."""
        self.session.flush()

    def commit(self) -> None:
        """Commit transaction."""
        self.session.commit()

    def rollback(self) -> None:
        """Rollback transaction."""
        self.session.rollback()
