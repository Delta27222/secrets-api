from typing import List, Optional

from pydantic import BaseModel

from .dbmodel import DBModelMixin, PyObjectId
from .organization import Organization
from .rwmodel import RWModel


class ProjectBase(RWModel):
    name: str
    slug: str
    tags: dict[str, str] = {}


class ProjectCreate(ProjectBase):
    organization_id: PyObjectId
    pass


class ProjectUpdate(ProjectBase):
    pass


class Project(ProjectBase):
    organization_id: PyObjectId

    class Config:
        from_attributes = True


class ProjectInDb(DBModelMixin, Project):
    class Config:
        from_attributes = True


class ManyProjectsInResponse(BaseModel):
    projects: List[ProjectInDb]
    projects_count: int
