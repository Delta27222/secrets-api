from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status

from app.core.logging import create_service_logger

from ....core.auth import get_current_user
from ....db.mongodb import AsyncIOMotorClient, get_database
from ....models.organization_member import (
    OrganizationMemberCreate,
    OrganizationMemberInResponse,
    OrganizationMemberUpdate,
)
from ....models.user import UserInDB
from ....services.organization_members import (
    accept_invitation,
    create_invitation,
    delete_organization_member,
    get_all_organization_memberships,
    get_all_organization_memberships_by_email,
    get_organization_member_by_email_and_org,
    get_organization_member_by_id,
    is_admin_for_organization,
    update_organization_member,
)

router = APIRouter(
    tags=['memberships']
)


@router.post("/organizations/{organization_id}/invite", response_model=OrganizationMemberInResponse)
async def invite_to_organization(
    organization_id: str,
    member: OrganizationMemberCreate,
    db: AsyncIOMotorClient = Depends(get_database),
    current_user: UserInDB = Depends(get_current_user)
):
    # Verify user has permissions to invite
    if not is_admin_for_organization(db, current_user.email, organization_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="No tienes permiso para invitar a esta organización")
    # Verify if user has already an membership
    current_membership = await get_organization_member_by_email_and_org(db, member.email, organization_id)
    if current_membership:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="El usuario ya tiene una invitación pendiente o ya es parte de la organización")
    return await _create_invitation(current_user.id, db, organization_id, member.email, member.role)

@create_service_logger("membership", "create_invitation", "organization") # 📦 DECORADOR QUE SE USA PARA LOGGEAR LAS ACCIONES DE LA API
async def _create_invitation(target_id: str, db: AsyncIOMotorClient, organization_id: str, email: str, role: str) -> OrganizationMemberInResponse:
    return await create_invitation(db, organization_id, email, role)


@router.post("/organizations/memberships/{member_id}/accept", response_model=OrganizationMemberInResponse)
async def accept_membership_invitation(
    member_id: str,
    db: AsyncIOMotorClient = Depends(get_database),
    current_user: UserInDB = Depends(get_current_user)
):
    # Verificar que el miembro que acepta la invitación es el usuario actual
    member = await get_organization_member_by_id(db, member_id)
    if not member or member.status != "pending":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Invitación no válida o ya aceptada")

    # Aceptar la invitación
    updated_member = await accept_invitation(db, member_id)
    return updated_member


@router.get("/organizations/memberships/me", response_model=List[OrganizationMemberInResponse])
async def get_user_memberships(
    db: AsyncIOMotorClient = Depends(get_database),
    current_user: UserInDB = Depends(get_current_user)
):
    # Get all membership of user
    memberships = await get_all_organization_memberships_by_email(db, current_user.email)
    return memberships


@router.put("/organizations/memberships/{member_id}")
async def update_membership(
    member_id: str,
    data: OrganizationMemberUpdate = Body(...),
    db: AsyncIOMotorClient = Depends(get_database),
    current_user: UserInDB = Depends(get_current_user)
):
    # Verificar que el usuario no es el dueño de la organización antes de eliminar la membresía
    member: Optional[OrganizationMemberInResponse] = await get_organization_member_by_id(db, member_id)
    if member == None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Membresía no encontrada")

    if not await is_admin_for_organization(db, current_user.email, member.organization_id):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="No tienes permiso para actualizar membresía")

    if member.role == "owner":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="No puedes actualizar la membresía del dueño")
    if data.role == "owner":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="No puedes actualizar la membresia a dueño")

    updated_member = await update_organization_member(db, member_id, data)

    if not updated_member:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="No se pudo actualizar la membresía")
    return updated_member


@router.delete("/organizations/memberships/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_membership(
    member_id: str,
    db: AsyncIOMotorClient = Depends(get_database),
    current_user: UserInDB = Depends(get_current_user)
):
    # Verificar que el usuario no es el dueño de la organización antes de eliminar la membresía
    member: Optional[OrganizationMemberInResponse] = await get_organization_member_by_id(db, member_id)
    if member == None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Membresía no encontrada")

    if not await is_admin_for_organization(db, current_user.email, member.organization_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="No tienes permiso para eliminar membresía")

    if member.role == "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="No puedes eliminar la membresía del dueño")

    # Eliminar la membresía
    deleted = await _delete_organization_member(current_user.id, db, member_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="No se pudo eliminar la membresía")
    return None

@create_service_logger("membership", "delete_organization_member", "organization")
async def _delete_organization_member(target_id: str, db: AsyncIOMotorClient, member_id: str) -> bool:
    return await delete_organization_member(db, member_id)

@router.get("/organizations/{organization_id}/memberships", response_model=List[OrganizationMemberInResponse])
async def get_memberships_by_organization(
    organization_id: str,
    db: AsyncIOMotorClient = Depends(get_database),
    current_user: UserInDB = Depends(get_current_user)
):

    # # Verify permissions
    # if not await is_admin_for_organization(db, current_user.email, organization_id):
    #     raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
    #                         detail="No tienes permiso para ver las membresías")

    # Get memberships for organization
    memberships = await get_all_organization_memberships(db, organization_id)

    return memberships
