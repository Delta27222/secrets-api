"""
Service Token models para autenticación programática.

Almacenado: token_secret cifrado con CSFLE
Hash: SHA256 para búsqueda sin exponer token
"""

from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field
from .dbmodel import DBModelMixin, PyObjectId
from .rwmodel import RWModel


class ServiceTokenBase(RWModel):
    """Base token fields"""
    name: str = Field(..., description="Nombre del token")
    description: Optional[str] = Field(None, alias='description')
    scopes: List[str] = Field(..., description="Permisos: secrets:read, projects:list, etc")
    status: str = Field(default="active", description="active, revoked, expired, pending_rotation")
    is_active: bool = Field(default=True)
    rotated: bool = Field(default=False, description="Si fue rotado previamente")
    environment_id: Optional[PyObjectId] = Field(None, alias='environmentId', description="Ambiente restringido (None = todos)")


class ServiceTokenCreate(ServiceTokenBase):
    """Token creation request"""
    expires_in_days: Optional[int] = Field(default=90, ge=1, le=365, alias='expiresInDays')
    project_id: Optional[PyObjectId] = Field(None, alias='projectId')
    rate_limit: Optional[dict] = Field(None)


class ServiceTokenResponse(ServiceTokenBase):
    """Token response (sin secret)"""
    token_id: str = Field(..., alias='tokenId')
    project_id: Optional[PyObjectId] = Field(None, alias='projectId')  # None = token de sistema (global)
    owner_id: PyObjectId = Field(..., alias='ownerId')
    created_at: datetime = Field(..., alias='createdAt')
    expires_at: datetime = Field(..., alias='expiresAt')
    last_used_at: Optional[datetime] = Field(None, alias='lastUsedAt')
    request_count: int = Field(default=0)

    class Config:
        from_attributes = True
        populate_by_name = True


class ServiceTokenCreateResponse(ServiceTokenResponse):
    """Respuesta de creación (con token_secret mostrado UNA VEZ)"""
    token_secret: str = Field(..., alias='tokenSecret', description="Token completo (solo mostrado al crear)")
    warning: str = "Guarda este token. No podrás verlo nuevamente."


class ServiceTokenInDB(DBModelMixin, ServiceTokenResponse):
    """Token completo en BD (con fields internos)"""
    token_hash: str = Field(..., alias='tokenHash')
    token_secret: Optional[str] = Field(None, alias='tokenSecret')  # Cifrado con CSFLE
    rate_limit: dict = Field(default_factory=dict)
    revoked_at: Optional[datetime] = Field(None, alias='revokedAt')
    revoked_by: Optional[PyObjectId] = Field(None, alias='revokedBy')
    revocation_reason: Optional[str] = Field(None, alias='revocationReason')
    last_used_by_ip: Optional[str] = Field(None, alias='lastUsedByIp')
    organization_id: Optional[PyObjectId] = Field(None, alias='organizationId')  # Opcional, para auditoría
    metadata: Optional[dict] = None

    class Config:
        from_attributes = True
        populate_by_name = True


class ServiceTokenRotation(RWModel):
    """Historial de rotaciones"""
    token_id: str = Field(..., alias='tokenId')
    old_token_hash: str = Field(..., alias='oldTokenHash')
    new_token_hash: str = Field(..., alias='newTokenHash')
    rotation_reason: str = Field(..., alias='rotationReason')
    rotated_at: datetime = Field(..., alias='rotatedAt')
    rotated_by: Optional[PyObjectId] = Field(None, alias='rotatedBy')
    grace_period_until: Optional[datetime] = Field(None, alias='gracePeriodUntil')

    class Config:
        from_attributes = True
        populate_by_name = True


class ServiceTokenUsage(RWModel):
    """Estadísticas de uso"""
    request_count: int = Field(default=0)
    last_used_at: Optional[datetime] = Field(None, alias='lastUsedAt')
    last_used_by_ip: Optional[str] = Field(None, alias='lastUsedByIp')
    requests_today: int = Field(default=0)
    requests_this_hour: int = Field(default=0)

    class Config:
        populate_by_name = True
