"""
Service Token endpoints - Acceso programático via service tokens.

Replica funcionalidad de endpoints usuario pero valida service tokens y scopes.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from bson import ObjectId

from ....core.service_auth import (
    Scope,
    ServiceTokenInDB,
    require_scope,
)
from ....db.mongodb import AsyncIOMotorClient, get_database
from ....models.environment import EnvironmentInDB, ManyEnvironmentsInResponse
from ....models.organization import OrganizationInDB
from ....models.project import ProjectInDb, ManyProjectsInResponse
from ....models.dbmodel import PyObjectId
from ....core.utils import create_aliased_response
from ....services.environment import (
    get_environment_by_id,
    get_all_environments_by_project,
)
from ....services.organizations import get_organization_by_id
from ....services.projects import (
    get_project_by_id,
    get_all_projects,
)

router = APIRouter(
    prefix="/service",
    tags=["service"],
    dependencies=[],
)


def validate_environment_access(token: ServiceTokenInDB, environment_id: str):
    """Lanza 403 si el token está restringido a un ambiente diferente."""
    if token.environment_id and str(token.environment_id) != str(environment_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token is restricted to a different environment"
        )


# ============================================================================
# SECRETOS
# ============================================================================

class SecretsQuery:
    """Payload para operaciones con secretos"""
    secret_name: str
    secret_value: str


@router.get("/secrets", )
async def get_secrets(
    environment_id: str = Query(..., alias="environment", description="Environment ID"),
    db: AsyncIOMotorClient = Depends(get_database),
    token: ServiceTokenInDB = Depends(require_scope(Scope.SECRETS_READ)),
):
    """
    Obtiene secretos de un ambiente.

    Scopes requeridos: `secrets:read`
    """
    environment = await get_environment_by_id(db, environment_id)
    if not environment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Environment '{environment_id}' not found"
        )

    # Verificar acceso al proyecto
    if token.project_id and str(token.project_id) != str(environment.project_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token does not have access to this environment"
        )

    # Verificar acceso al ambiente específico
    validate_environment_access(token, environment_id)

    return {
        "environment_id": environment.id,
        "secrets": environment.secrets or {},
        "encryption_metadata": environment.secrets_encryption
    }


# Deshabilitado temporalmente — escritura de secretos vía service token
# @router.post("/secrets", )
# async def create_or_update_secrets(
#     environment_id: str = Query(..., alias="environment", description="Environment ID"),
#     secrets: dict = Body(..., description="Key-value pairs of secrets"),
#     db: AsyncIOMotorClient = Depends(get_database),
#     token: ServiceTokenInDB = Depends(require_scope(Scope.SECRETS_WRITE)),
# ):
#     """
#     Crea o actualiza secretos en un ambiente.
#
#     Scopes requeridos: `secrets:write`
#     """
#     environment = await get_environment_by_id(db, environment_id)
#     if not environment:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail=f"Environment '{environment_id}' not found"
#         )
#
#     if token.project_id and str(token.project_id) != str(environment.project_id):
#         raise HTTPException(
#             status_code=status.HTTP_403_FORBIDDEN,
#             detail="Token does not have access to this environment"
#         )
#
#     current_secrets = environment.secrets or {}
#     current_secrets.update(secrets)
#
#     from ....models.environment import EnvironmentUpdate
#     update_data = EnvironmentUpdate(secrets=current_secrets)
#     updated = await update_environment(db, environment_id, update_data)
#
#     if not updated:
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail="Failed to update secrets"
#         )
#
#     return {
#         "environment_id": updated.id,
#         "secrets_updated": list(secrets.keys()),
#         "total_secrets": len(updated.secrets or {})
#     }


# Deshabilitado temporalmente — borrado de secretos vía service token
# @router.delete("/secrets", )
# async def delete_secret(
#     environment_id: str = Query(..., alias="environment", description="Environment ID"),
#     secret_name: str = Query(..., description="Secret key to delete"),
#     db: AsyncIOMotorClient = Depends(get_database),
#     token: ServiceTokenInDB = Depends(require_scope(Scope.SECRETS_DELETE)),
# ):
#     """
#     Elimina un secret específico de un ambiente.
#
#     Scopes requeridos: `secrets:delete`
#     """
#     environment = await get_environment_by_id(db, environment_id)
#     if not environment:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail=f"Environment '{environment_id}' not found"
#         )
#
#     if token.project_id and str(token.project_id) != str(environment.project_id):
#         raise HTTPException(
#             status_code=status.HTTP_403_FORBIDDEN,
#             detail="Token does not have access to this environment"
#         )
#
#     current_secrets = environment.secrets or {}
#     if secret_name not in current_secrets:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail=f"Secret '{secret_name}' not found"
#         )
#
#     del current_secrets[secret_name]
#
#     from ....models.environment import EnvironmentUpdate
#     update_data = EnvironmentUpdate(secrets=current_secrets)
#     updated = await update_environment(db, environment_id, update_data)
#
#     if not updated:
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail="Failed to delete secret"
#         )
#
#     return {
#         "environment_id": updated.id,
#         "deleted_secret": secret_name,
#         "remaining_secrets": len(updated.secrets or {})
#     }


# ============================================================================
# AMBIENTES
# ============================================================================

@router.get("/environments/{id}", response_model=EnvironmentInDB, )
async def get_environment(
    id: str = Path(..., min_length=1),
    db: AsyncIOMotorClient = Depends(get_database),
    token: ServiceTokenInDB = Depends(require_scope(Scope.ENVIRONMENTS_READ)),
):
    """
    Obtiene detalles de un ambiente.

    Scopes requeridos: `environments:read`
    """
    environment = await get_environment_by_id(db, id)
    if not environment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Environment '{id}' not found"
        )

    # Verificar acceso al proyecto
    if token.project_id and str(token.project_id) != str(environment.project_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token does not have access to this environment"
        )

    # Verificar acceso al ambiente específico
    validate_environment_access(token, id)

    return environment


@router.get("/projects/{project_id}/environments", response_model=ManyEnvironmentsInResponse, )
async def get_environments_by_project(
    project_id: str = Path(..., min_length=1),
    limit: int = Query(20, gt=0),
    offset: int = Query(0, ge=0),
    db: AsyncIOMotorClient = Depends(get_database),
    token: ServiceTokenInDB = Depends(require_scope(Scope.ENVIRONMENTS_LIST)),
):
    """
    Lista ambientes de un proyecto.

    Scopes requeridos: `environments:list`
    """
    # Verificar acceso al proyecto
    if token.project_id and str(token.project_id) != project_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token does not have access to this project"
        )

    from ....core.config import database_name, environments_collection_name

    coll = db[database_name][environments_collection_name]
    query = {"project_id": project_id}

    # Si token restringido a un ambiente, filtrar solo ese
    if token.environment_id:
        query["_id"] = ObjectId(str(token.environment_id))

    total = await coll.count_documents(query)

    environments = await coll.find(query).skip(offset).limit(limit).to_list(None)
    environments_list = [EnvironmentInDB(**env) for env in environments]

    return ManyEnvironmentsInResponse(
        environments=environments_list,
        environments_count=total
    )


# ============================================================================
# PROYECTOS
# ============================================================================

@router.get("/projects/{id}", response_model=ProjectInDb, )
async def get_project(
    id: str = Path(..., min_length=1),
    db: AsyncIOMotorClient = Depends(get_database),
    token: ServiceTokenInDB = Depends(require_scope(Scope.PROJECTS_READ)),
):
    """
    Obtiene detalles de un proyecto.

    Scopes requeridos: `projects:read`
    """
    # Verificar acceso al proyecto
    if token.project_id and str(token.project_id) != id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token does not have access to this project"
        )

    project = await get_project_by_id(db, id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{id}' not found"
        )

    return create_aliased_response(project)


@router.get("/projects", response_model=ManyProjectsInResponse, )
async def list_projects(
    limit: int = Query(20, gt=0),
    offset: int = Query(0, ge=0),
    db: AsyncIOMotorClient = Depends(get_database),
    token: ServiceTokenInDB = Depends(require_scope(Scope.PROJECTS_LIST)),
):
    """
    Lista proyectos accesibles al token.

    Si el token está scoped a un proyecto, solo devuelve ese.
    Scopes requeridos: `projects:list`
    """
    from ....core.config import database_name, projects_collection_name

    coll = db[database_name][projects_collection_name]

    # Si token está scoped a proyecto, filtrar por ese
    query = {}
    if token.project_id:
        query = {"_id": ObjectId(token.project_id)}

    total = await coll.count_documents(query)
    projects = await coll.find(query).skip(offset).limit(limit).to_list(None)

    projects_list = [ProjectInDb(**p) for p in projects]

    return ManyProjectsInResponse(
        projects=projects_list,
        projects_count=total
    )


# ============================================================================
# ORGANIZACIÓN
# ============================================================================

@router.get("/organizations/{id}", response_model=OrganizationInDB, )
async def get_organization(
    id: str = Path(..., min_length=1),
    db: AsyncIOMotorClient = Depends(get_database),
    token: ServiceTokenInDB = Depends(require_scope(Scope.ORG_READ)),
):
    """
    Obtiene detalles de una organización.

    Scopes requeridos: `org:read`

    Nota: El token no valida acceso a la org, solo verifica scope.
    Considera agregar validación de membership si es crítico.
    """
    organization = await get_organization_by_id(db, id)
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organization '{id}' not found"
        )

    return organization
