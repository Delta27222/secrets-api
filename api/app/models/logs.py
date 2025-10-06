from __future__ import annotations

from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel
from sqlalchemy import String, Float, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class LogORM(Base):
    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    target_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    target_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    action: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    details: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    execution_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class LogModel(BaseModel):
    id: int
    user_id: Optional[str]
    target_id: Optional[str]
    target_type: Optional[str]
    action: Optional[str]
    details: Optional[str]
    execution_time: Optional[float]
    date: datetime

    @classmethod
    def from_orm(cls, orm_obj: LogORM) -> "LogModel":
        return cls(
            id=orm_obj.id,
            user_id=orm_obj.user_id,
            target_id=orm_obj.target_id,
            target_type=orm_obj.target_type,
            action=orm_obj.action,
            details=orm_obj.details,
            execution_time=orm_obj.execution_time,
            date=orm_obj.date,
        )


class LogResponse(BaseModel):
    """Modelo Pydantic para respuestas de QuestDB"""
    id: str
    user: str
    action: str
    date: datetime
    targetType: str
    idTarget: str
    details: Optional[str] = None
    execution_time: Optional[str] = None  # QuestDB devuelve como string

    class Config:
        from_attributes = True


class PaginationMeta(BaseModel):
    page: int
    per_page: int
    total: int
    total_pages: int


class PaginatedLogsResponse(BaseModel):
    data: List[LogResponse]
    meta: PaginationMeta

