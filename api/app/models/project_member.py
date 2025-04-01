from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from .dbmodel import DBModelMixin
from .organization import OrganizationInDB
from .project import ProjectInDb
from .rwmodel import RWModel
from .user import UserInDB


class ProjectRole(str, Enum):
    viewer = "viewer"
    collab = "collab"
    admin = "admin"


class ProjectMemberBase(RWModel):
    project: str = Field(..., alias="project")
    user: str = Field(..., alias="user")
    role: ProjectRole = Field(..., alias="role")

    class Config:
        from_attributes = True
        allow_population_by_field_name = True


class ProjectMemberCreate(ProjectMemberBase):
    pass


class ProjectMember(ProjectMemberBase):
    class Config:
        from_attributes = True


class ProjectMemberInDB(DBModelMixin, ProjectMember):
    class Config:
        from_attributes = True


class ProjectMemberInResponse(DBModelMixin):
    user: Optional[UserInDB] = Field(..., alias="user")
    project: ProjectInDb = Field(..., alias="project")
    role: ProjectRole = Field(..., alias="role")

    class Config:
        from_attributes = True


class ProjectMemberUpdate(BaseModel):
    role: Optional[ProjectRole] = Field(None, alias="role")

    class Config:
        from_attributes = True
