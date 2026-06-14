from datetime import datetime
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
    vercel_project_id: Optional[str] = Field(
        default=None, description="ID del proyecto de Vercel asociado (opcional)"
    )
    vercel_token: Optional[str] = Field(
        default=None, description="Token para el proyecto de Vercel (opcional)"
    )
    vercel_target: Optional[List[str]] = Field(
        default=None, description="Targets para el proyecto de Vercel (opcional)"
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
    environment_id: Optional[str] = Field(default=None, description="ID del entorno (opcional)")
    render_server_id: Optional[str] = Field(
        default=None, description="ID del servidor de renderizado asociado (opcional)"
    )
    render_token: Optional[str] = Field(
        default=None, description="Token para el servidor de renderizado (opcional)"
    )

class EnvironmentRenderUpdate(EnvironmentRenderData):
    """Modelo para actualizaciones exclusivas de render -> render_token y render_server_id"""
    pass

class EnvironmentVercelData(BaseModel):
    environment_id: Optional[str] = Field(default=None, description="ID del entorno (opcional)")
    vercel_project_id: Optional[str] = Field(
        default=None, description="ID del proyecto de Vercel asociado (opcional)"
    )
    vercel_token: Optional[str] = Field(
        default=None, description="Token para el proyecto de Vercel (opcional)"
    )
    vercel_target: Optional[List[str]] = Field(
        default=None, description="Targets para el proyecto de Vercel (opcional)"
    )


class EnvironmentVercelUpdate(EnvironmentVercelData):
    """Modelo para actualizaciones exclusivas de Vercel -> vercel_project_id y vercel_token"""
    pass


class EnvironmentVercelTarget(BaseModel):
    vercel_target: Optional[List[str]] = Field(
        default=None, description="Targets para el proyecto de Vercel (opcional)"
    )

class SecretsEncryptionMetadata(BaseModel):
    key_version: Optional[int] = Field(default=None, description="Versión de la llave usada")
    encrypted_with_key_id: Optional[str] = Field(default=None, description="ID de la llave usada para encriptar")
    encrypted_at: Optional[datetime] = Field(default=None, description="Fecha de encriptación")
    requires_reencryption: bool = Field(default=False, description="Si requiere re-encriptación")


class Environment(EnvironmentBase):
    project_id: str = Field(..., description="ID del proyecto asociado")
    secrets: Dict[str, Any] = Field(default={})
    secrets_encryption: Optional[SecretsEncryptionMetadata] = Field(
        default=None, description="Metadata de encriptación de secretos"
    )

    class Config:
        from_attributes = True


class EnvironmentInDB(DBModelMixin, Environment):
    class Config:
        from_attributes = True


class ManyEnvironmentsInResponse(BaseModel):
    environments: List[EnvironmentInDB]
    environments_count: int