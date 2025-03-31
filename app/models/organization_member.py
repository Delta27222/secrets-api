from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from .dbmodel import DBModelMixin
from .organization import OrganizationInDB
from .rwmodel import RWModel
from .user import UserInDB


# Enum for Organization Role
class OrganizationRole(str, Enum):
    owner = "owner"
    admin = "admin"
    collab = "collab"


# Enum for organization membership status
class MembershipStatus(str, Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"


class OrganizationMemberBase(RWModel):
    organization_id: str = Field(..., alias="organization_id")
    # Is the username in github
    email: str = Field(...)
    role: OrganizationRole = Field(..., alias="role")
    status: MembershipStatus = Field(MembershipStatus.pending, alias="status")

    class Config:
        from_attributes = True


class OrganizationMemberCreate(OrganizationMemberBase):
    pass


class OrganizationMember(OrganizationMemberBase):
    class Config:
        from_attributes = True


class OrganizationMemberInDB(DBModelMixin, OrganizationMember):
    class Config:
        from_attributes = True


class OrganizationMemberInResponse(OrganizationMemberInDB):
    user: Optional[UserInDB]
    organization: OrganizationInDB

    class Config:
        from_attributes = True


class OrganizationMemberUpdate(BaseModel):
    role: Optional[OrganizationRole] = Field(None, alias="role")
    status: Optional[MembershipStatus] = Field(None, alias="status")

    class Config:
        from_attributes = True
