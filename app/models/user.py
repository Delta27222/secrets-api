from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from .dbmodel import DBModelMixin
from .rwmodel import RWModel


class UserBase(RWModel):
    email: Optional[EmailStr] = Field(None, description="Email del usuario")
    # Github Username
    username: str
    # Opcional, puede ser diferente del username
    display_name: Optional[str] = Field(None, alias='displayName')


class UserCreate(UserBase):
    pass  # No necesitamos campos adicionales para la creación


class User(UserBase):
    class Config:
        from_attributes = True


class UserInDB(DBModelMixin, User):
    class Config:
        from_attributes = True
        # populate_by_name = True
