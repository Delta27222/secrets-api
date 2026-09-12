from __future__ import annotations

from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel
from sqlalchemy import String, Float, DateTime, Integer
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
    # Resultado de la operación: null en los éxitos, poblado en los fallos.
    level: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    # Contexto de la petición.
    client_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    method: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)


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
    # QuestDB devuelve execution_time como DOUBLE (número). El front hace
    # parseFloat, así que un número sirve. Optional por si la fila viene sin él.
    execution_time: Optional[float] = None
    # Nulos en las filas anteriores al cambio de esquema y en los éxitos, así que
    # todos opcionales: el front tiene que tolerar su ausencia.
    level: Optional[str] = None
    status_code: Optional[int] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    client_ip: Optional[str] = None
    user_agent: Optional[str] = None
    method: Optional[str] = None
    request_id: Optional[str] = None

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

