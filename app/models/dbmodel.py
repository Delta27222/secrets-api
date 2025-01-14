from datetime import datetime
from typing import Optional

from pydantic import BaseModel, BeforeValidator, Field, Schema
from typing_extensions import Annotated

PyObjectId = Annotated[str, BeforeValidator(str)]


class DateTimeModelMixin(BaseModel):
    created_at: Optional[datetime] = Schema(..., alias="createdAt")
    updated_at: Optional[datetime] = Schema(..., alias="updatedAt")


class DBModelMixin(DateTimeModelMixin):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
