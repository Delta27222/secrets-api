from typing import Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field

from .dbmodel import DBModelMixin, PyObjectId


class EncryptionKeyBase(BaseModel):
    key_id: str = Field(..., description="ID único de la llave")
    project_id: Optional[str] = Field(None, description="ID del proyecto (None = global)")
    version: int = Field(..., description="Número de versión")
    algorithm: str = Field(default="Fernet", description="Algoritmo de encriptación")
    key_size_bits: int = Field(default=256, description="Tamaño de la llave en bits")
    status: str = Field(
        default="pending",
        description="Estado: pending, active, deprecated, expired"
    )
    is_primary: bool = Field(default=False, description="Es la llave activa para encriptar")
    rotation_reason: Optional[str] = Field(
        None,
        description="Razón de rotación: scheduled, compromised, manual"
    )
    previous_key_id: Optional[str] = Field(None, description="ID de la llave anterior")


class EncryptionKeyCreate(EncryptionKeyBase):
    key_material: str = Field(..., description="Material criptográfico (Fernet key codificada)")


class EncryptionKey(EncryptionKeyBase):
    key_material: str = Field(..., description="Material criptográfico (Fernet key codificada)")
    created_at: datetime = Field(..., description="Fecha de creación")
    activated_at: Optional[datetime] = Field(None, description="Fecha de activación")
    rotated_at: Optional[datetime] = Field(None, description="Fecha de rotación")
    deactivated_at: Optional[datetime] = Field(None, description="Fecha de desactivación")
    expires_at: Optional[datetime] = Field(None, description="Fecha de expiración")
    created_by: Optional[PyObjectId] = Field(None, description="Usuario que creó la llave")
    metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Metadata adicional (environment, region, backup_location, etc)"
    )

    class Config:
        from_attributes = True


class EncryptionKeyInDB(DBModelMixin, EncryptionKey):
    class Config:
        from_attributes = True


class EncryptionKeyResponse(BaseModel):
    key_id: str
    version: int
    status: str
    is_primary: bool
    algorithm: str
    created_at: datetime
    activated_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    # No incluir key_material en respuestas
