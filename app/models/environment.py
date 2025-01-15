from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .dbmodel import DBModelMixin, PyObjectId
from .rwmodel import RWModel


class EnvironmentBase(BaseModel):
    project_id: str = Field(..., description="ID del proyecto asociado")
    name: str = Field(...,
                      description="Nombre del entorno")

    slug: str = Field(...,
                      description="Slug único para identificar el entorno")


class EnvironmentCreate(EnvironmentBase):
    secrets: Dict[str, Any] = Field(
        default={}, description="Diccionario de secretos")


class Environment(EnvironmentBase):
    id: str
    secrets: Dict[str, Any] = Field(default={})

    class Config:
        from_attributes = True


class EnvironmentInDB(DBModelMixin, Environment):
    class Config:
        from_attributes = True


class ManyEnvironmentsInResponse(BaseModel):
    environments: List[EnvironmentInDB]
    environments_count: int
