from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from .dbmodel import DBModelMixin
from .rwmodel import RWModel


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


class ProjectMemberUpdate(BaseModel):
    role: Optional[ProjectRole] = Field(None, alias="role")

    class Config:
        from_attributes = True
