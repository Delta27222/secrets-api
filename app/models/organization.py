from typing import Optional

from pydantic import BaseModel

from .rwmodel import RWModel


class OrganizationBase(RWModel):
    name: str
    slug: str


class OrganizationCreate(OrganizationBase):
    pass


class Organization(OrganizationBase):
    id: str

    class Config:
        orm_mode = True
