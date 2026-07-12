"""
Service Tokens API endpoints.

Requiere autenticación JWT.
Admin/Owner del proyecto.
"""

from typing import Optional
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Header, Query, Path, status

from ....core.auth import get_current_user
from ....core.config import database_name, service_tokens_collection_name
from ....core.utils import create_aliased_response
from ....db.mongodb import AsyncIOMotorClient, get_database
from ....models.user import UserInDB
from ....models.service_token import (
    ServiceTokenCreate,
    ServiceTokenCreateResponse,
    ServiceTokenResponse,
    ServiceTokenInDB,
    ServiceTokenUsage
)
from ....services.service_tokens import ServiceTokenGenerator, ServiceTokenManager
from ....services.organization_members import is_admin_for_organization
from ....services.project_members import (
    get_project_member_by_user_id,
    is_project_admin
)
from ....services.projects import get_project_by_id
from ....services.environment import get_environment_by_id

router = APIRouter(
    tags=['service-tokens']
)


async def check_project_access(
    project_id: str = Path(...),
    current_user: UserInDB = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """Verifica que usuario sea miembro o admin del proyecto"""
    try:
        ObjectId(project_id)
    except:
        raise HTTPException(status_code=400, detail="Invalid project_id")

    # Obtener proyecto para verificar org
    project = await get_project_by_id(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Verificar: es admin de org O es miembro del proyecto O es admin del proyecto
    is_org_admin = await is_admin_for_organization(db, current_user.email, str(project.organization_id))
    is_member = await get_project_member_by_user_id(db, project_id, current_user.id)
    is_p_admin = await is_project_admin(db, project_id, current_user.id)

    if not (is_org_admin or is_member or is_p_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only project members can manage service tokens"
        )

    return ObjectId(project_id)


async def check_project_admin_access(
    project_id: str = Path(...),
    current_user: UserInDB = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database),
):
    """Solo admins/owners de la org o admins del proyecto pueden crear service tokens."""
    try:
        ObjectId(project_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid project_id")

    project = await get_project_by_id(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    is_org_admin = await is_admin_for_organization(
        db, current_user.email, str(project.organization_id)
    )
    is_p_admin = await is_project_admin(db, project_id, current_user.id)

    if not (is_org_admin or is_p_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only organization admins/owners or project admins can create service tokens",
        )

    return ObjectId(project_id)


@router.post("/projects/{project_id}/tokens", response_model=ServiceTokenCreateResponse)
async def create_service_token(
    payload: ServiceTokenCreate,
    project_id: ObjectId = Depends(check_project_admin_access),
    current_user: UserInDB = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    Crea nuevo token de servicio.

    Requiere ser admin/owner de la organización o admin del proyecto.
    Token se cifra con CSFLE.
    Se muestra UNA SOLA VEZ.
    """
    # Validar que el ambiente pertenezca al proyecto (si se especifica)
    env_id = None
    if payload.environment_id:
        env = await get_environment_by_id(db, str(payload.environment_id))
        if not env or str(env.project_id) != str(project_id):
            raise HTTPException(status_code=400, detail="Environment does not belong to this project")
        env_id = ObjectId(str(payload.environment_id))

    try:
        result = await ServiceTokenGenerator.generate_token(
            db=db,
            project_id=project_id,
            owner_id=ObjectId(current_user.id),
            name=payload.name,
            scopes=payload.scopes,
            expires_in_days=payload.expires_in_days or 90,
            description=payload.description,
            rate_limit=payload.rate_limit,
            environment_id=env_id
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")


@router.get("/projects/{project_id}/tokens", response_model=list[ServiceTokenResponse])
async def list_service_tokens(
    project_id: ObjectId = Depends(check_project_access),
    current_user: UserInDB = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """Lista tokens activos de un proyecto"""
    try:
        tokens = await ServiceTokenManager.list_tokens(
            db=db,
            project_id=project_id
        )
        return tokens
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_id}/tokens/{token_id}", response_model=ServiceTokenResponse)
async def get_service_token(
    token_id: str,
    project_id: ObjectId = Depends(check_project_access),
    current_user: UserInDB = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """Obtiene detalles de un token específico"""
    token_doc = await db[database_name][service_tokens_collection_name].find_one({
        "token_id": token_id,
        "project_id": project_id
    })

    if not token_doc:
        raise HTTPException(status_code=404, detail="Token not found")

    return ServiceTokenResponse(**token_doc)


@router.delete("/projects/{project_id}/tokens/{token_id}", status_code=204)
async def revoke_service_token(
    token_id: str,
    project_id: ObjectId = Depends(check_project_access),
    reason: str = Query("manual"),
    current_user: UserInDB = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """Revoca inmediatamente un token"""
    try:
        await ServiceTokenManager.revoke_token(
            db=db,
            token_id=token_id,
            project_id=project_id,
            revoked_by=current_user.id,
            reason=reason
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/projects/{project_id}/tokens/{token_id}/rotate", response_model=dict)
async def rotate_service_token(
    token_id: str,
    project_id: ObjectId = Depends(check_project_access),
    current_user: UserInDB = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """Rota token: genera nuevo, antiguo válido 5 minutos más"""
    try:
        new_token_id, new_token_secret = await ServiceTokenManager.rotate_token(
            db=db,
            token_id=token_id,
            project_id=project_id,
            rotated_by=current_user.id
        )

        return {
            "status": "success",
            "new_token_id": new_token_id,
            "new_token_secret": new_token_secret,
            "warning": "Guarda el nuevo token. El token antiguo ha sido revocado inmediatamente."
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_id}/tokens/{token_id}/usage", response_model=ServiceTokenUsage)
async def get_service_token_usage(
    token_id: str,
    project_id: ObjectId = Depends(check_project_access),
    current_user: UserInDB = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """Obtiene estadísticas de uso del token"""
    try:
        usage = await ServiceTokenManager.get_token_usage(
            db=db,
            token_id=token_id,
            project_id=project_id
        )
        return usage
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
