from typing import Optional

from pydantic import BaseModel

from .dbmodel import DBModelMixin
from .rwmodel import RWModel


class OrganizationBase(RWModel):
    name: str
    slug: str


class OrganizationCreate(OrganizationBase):
    pass


class Organization(OrganizationBase):
    class Config:
        from_attributes = True


class OrganizationInDB(DBModelMixin, Organization):
    class Config:
        from_attributes = True
