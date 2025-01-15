from typing import List, Optional

from pydantic import BaseModel

from .dbmodel import DBModelMixin, PyObjectId
from .organization import Organization
from .rwmodel import RWModel


class ProjectBase(RWModel):
    organization_id: PyObjectId
    name: str
    slug: str


class ProjectCreate(ProjectBase):
    pass


class Project(ProjectBase):
    class Config:
        from_attributes = True


class ProjectInDb(DBModelMixin, Project):
    class Config:
        from_attributes = True


class ManyProjectsInResponse(BaseModel):
    projects: List[ProjectInDb]
    projects_count: int
