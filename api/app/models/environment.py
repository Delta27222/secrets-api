from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .dbmodel import DBModelMixin, PyObjectId
from .rwmodel import RWModel


class EnvironmentBaseForCreate(BaseModel):
    project_id: str = Field(..., description="ID del proyecto asociado")


class EnvironmentBase(BaseModel):
    name: str = Field(...,description="Nombre del entorno")
    slug: str = Field(..., description="Slug único para identificar el entorno")
    render_server_id: Optional[str] = Field(
        default=None, description="ID del servidor de renderizado asociado (opcional)"
    )
    render_token: Optional[str] = Field(
        default=None, description="Token para el servidor de renderizado (opcional)"
    )

class EnvironmentCreate(EnvironmentBaseForCreate, EnvironmentBase):
    secrets: Dict[str, Any] = Field(
        default={}, description="Diccionario de secretos")

class EnvironmentUpdate(BaseModel):
    """Modelo para actualizaciones que excluye project_id"""
    name: Optional[str] = Field(default=None,
                                description="Nombre del entorno")
    slug: Optional[str] = Field(default=None,
                                description="Slug único para identificar el entorno")
    secrets: Dict[str, Any] = Field(
        default={}, description="Diccionario de secretos")

class EnvironmentRenderData(BaseModel):
    render_server_id: Optional[str] = Field(
        default=None, description="ID del servidor de renderizado asociado (opcional)"
    )
    render_token: Optional[str] = Field(
        default=None, description="Token para el servidor de renderizado (opcional)"
    )

class EnvironmentRenderUpdate(EnvironmentRenderData):
    """Modelo para actualizaciones exclusivas de render -> render_token y render_server_id"""
    pass

class Environment(EnvironmentBase):
    project_id: str = Field(..., description="ID del proyecto asociado")
    secrets: Dict[str, Any] = Field(default={})

    class Config:
        from_attributes = True


class EnvironmentInDB(DBModelMixin, Environment):
    class Config:
        from_attributes = True


class ManyEnvironmentsInResponse(BaseModel):
    environments: List[EnvironmentInDB]
    environments_count: int