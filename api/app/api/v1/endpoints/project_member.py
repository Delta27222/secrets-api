from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorClient

from ....core.auth import get_current_user
from ....db.mongodb import get_database
from ....models.project_member import (
    ProjectMemberCreate,
    ProjectMemberInDB,
    ProjectMemberUpdate,
)
from ....models.user import UserInDB
from ....services.project_members import (
    create_project_member,
    delete_project_member,
    get_project_member_by_id,
    get_project_member_by_user_id,
    get_project_members,
    is_admin_for_organization,
    is_project_admin,
    update_project_member,
)
from ....services.projects import get_project_by_id
from ....services.users import get_user_by_id

router = APIRouter(tags=['project_members'])


@router.post("/projects/{project_id}/members", response_model=ProjectMemberInDB)
async def create_project_member_route(
    project_id: str,
    project_member: ProjectMemberCreate,
    db: AsyncIOMotorClient = Depends(get_database),
    current_user: UserInDB = Depends(get_current_user)
):
    project = await get_project_by_id(db, project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Proyecto no encontrado")

    is_admin_project = await is_project_admin(db, project_id, current_user.id)
    is_admin = await is_admin_for_organization(db, current_user.email, project.organization_id)
    if not is_admin_project and not is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="No tienes permiso para añadir miembros a este proyecto")

    if project_member.project != project_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="El ID del proyecto no coincide con la ruta")

    user_to_add = await get_user_by_id(db, project_member.user)
    if user_to_add == None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Usuario no existe")

    existing_member = await get_project_member_by_user_id(db, project_id, user_to_add.id)
    if existing_member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Miembro de proyecto ya existente")

    new_member = await create_project_member(db, project_member)
    return new_member


@router.put("/projects/members/{member_id}", response_model=ProjectMemberInDB)
async def update_project_member_route(
    member_id: str,
    project_member: ProjectMemberUpdate,
    db: AsyncIOMotorClient = Depends(get_database),
    current_user: UserInDB = Depends(get_current_user)
):
    existing_member = await get_project_member_by_id(db, member_id)
    if not existing_member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Miembro de proyecto no encontrado")

    if not await is_project_admin(db, existing_member.project, current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="No tienes permiso para actualizar este miembro de proyecto")

    updated_member = await update_project_member(db, member_id, project_member)
    print(updated_member)
    if updated_member == None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="No se pudo actualizar el miembro de proyecto")
    return updated_member


@router.delete("/projects/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project_member_route(
    member_id: str,
    db: AsyncIOMotorClient = Depends(get_database),
    current_user: UserInDB = Depends(get_current_user)
):
    existing_member = await get_project_member_by_id(db, member_id)
    if not existing_member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Miembro de proyecto no encontrado")

    if not await is_project_admin(db, existing_member.project, current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="No tienes permiso para eliminar este miembro de proyecto")

    if not await delete_project_member(db, member_id):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="No se pudo eliminar el miembro de proyecto")
    return None
