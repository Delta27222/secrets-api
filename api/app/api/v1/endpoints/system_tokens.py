"""
System Service Tokens - tokens de servicio GLOBALES (sin proyecto).

Usados para operaciones de sistema como la rotación de llaves ejecutada por
el Lambda Worker. A diferencia de los tokens normales, NO están atados a un
proyecto (project_id = None) y por eso pueden operar sobre cualquiera.

Seguridad: solo los emails en SYSTEM_ADMIN_EMAILS (config) pueden crearlos.
"""

from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status
from bson import ObjectId
from pydantic import BaseModel, Field

from datetime import datetime

from ....core.auth import get_current_user
from ....core.config import (
    SYSTEM_ADMIN_EMAILS,
    database_name,
    service_tokens_collection_name,
)
from ....core.service_auth import Scope
from ....db.mongodb import AsyncIOMotorClient, get_database
from ....models.user import UserInDB
from ....models.service_token import ServiceTokenCreateResponse, ServiceTokenResponse
from ....services.service_tokens import ServiceTokenGenerator

router = APIRouter(tags=["system-tokens"])


class SystemTokenCreate(BaseModel):
    """Payload para crear un token de sistema."""
    name: str = Field(..., description="Nombre descriptivo del token")
    description: Optional[str] = Field(None)
    scopes: List[str] = Field(
        default_factory=lambda: [Scope.KEYS_ROTATE.value],
        description="Scopes del token (default: keys:rotate)",
    )
    expires_in_days: int = Field(default=365, ge=1, le=3650)


async def require_system_admin(
    current_user: UserInDB = Depends(get_current_user),
) -> UserInDB:
    """Permite solo a emails en SYSTEM_ADMIN_EMAILS crear tokens de sistema."""
    if not SYSTEM_ADMIN_EMAILS:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SYSTEM_ADMIN_EMAILS no configurado en el servidor",
        )
    email = (current_user.email or "").lower()
    if email not in SYSTEM_ADMIN_EMAILS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No autorizado para crear tokens de sistema",
        )
    return current_user


@router.post("/system-tokens", response_model=ServiceTokenCreateResponse)
async def create_system_token(
    payload: SystemTokenCreate = Body(...),
    current_user: UserInDB = Depends(require_system_admin),
    db: AsyncIOMotorClient = Depends(get_database),
):
    """
    Crea un token de servicio de sistema (global, sin proyecto).

    Requiere que el email del usuario esté en SYSTEM_ADMIN_EMAILS.
    El token_secret se muestra UNA sola vez — guárdalo (va en el Lambda).
    """
    try:
        result = await ServiceTokenGenerator.generate_token(
            db=db,
            project_id=None,  # token de sistema: sin proyecto
            owner_id=ObjectId(current_user.id),
            name=payload.name,
            scopes=payload.scopes,
            expires_in_days=payload.expires_in_days,
            description=payload.description,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")


@router.get("/system-tokens", response_model=list[ServiceTokenResponse])
async def list_system_tokens(
    current_user: UserInDB = Depends(require_system_admin),
    db: AsyncIOMotorClient = Depends(get_database),
):
    """Lista los tokens de sistema activos (project_id = None)."""
    tokens = await db[database_name][service_tokens_collection_name].find(
        {"project_id": None, "is_active": True}
    ).sort("created_at", -1).to_list(None)

    return [ServiceTokenResponse(**t) for t in tokens]


@router.delete("/system-tokens/{token_id}", status_code=204)
async def revoke_system_token(
    token_id: str,
    current_user: UserInDB = Depends(require_system_admin),
    db: AsyncIOMotorClient = Depends(get_database),
):
    """Revoca inmediatamente un token de sistema."""
    result = await db[database_name][service_tokens_collection_name].update_one(
        {"token_id": token_id, "project_id": None, "is_active": True},
        {
            "$set": {
                "status": "revoked",
                "is_active": False,
                "revoked_at": datetime.utcnow(),
                "revoked_by": ObjectId(current_user.id),
                "revocation_reason": "manual",
            }
        },
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Token no encontrado o ya revocado")
