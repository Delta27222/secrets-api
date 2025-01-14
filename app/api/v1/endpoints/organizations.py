from typing import List, Optional

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query

from ....db.mongodb import AsyncIOMotorClient, get_database
from ....models.organization import Organization, OrganizationCreate

router = APIRouter(
    tags=['Organization']
)


@router.post("/organizations/", response_model=Organization)
async def create_organization(organization: OrganizationCreate, db: AsyncIOMotorClient = Depends(get_database)):
    return await create_organization(db, organization)


@router.get("/organizations/{id}", response_model=Organization)
async def get_organization_by_id(id: str, db: AsyncIOMotorClient = Depends(get_database)):
    org = await get_organization_by_id(db, id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


@router.get("/organizations/", response_model=List[Organization])
async def get_all_organizations(limit: int = 100, offset: int = 0, db: AsyncIOMotorClient = Depends(get_database)):
    return await get_all_organizations(db, limit, offset)


@router.put("/organizations/{id}", response_model=Organization)
async def update_organization(id: str, organization: OrganizationCreate, db: AsyncIOMotorClient = Depends(get_database)):
    updated_org = await update_organization(db, id, organization)
    if updated_org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return updated_org


@router.delete("/organizations/{id}", status_code=204)
async def delete_organization(id: str, db: AsyncIOMotorClient = Depends(get_database)):
    if not await delete_organization(db, id):
        raise HTTPException(status_code=404, detail="Organization not found")
    return {"message": "Organization deleted successfully"}
