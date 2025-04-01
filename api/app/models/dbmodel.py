from datetime import datetime
from typing import Optional

from pydantic import BaseModel, BeforeValidator, Field, schema
from typing_extensions import Annotated

PyObjectId = Annotated[str, BeforeValidator(str)]


class DateTimeModelMixin(BaseModel):
    created_at: Optional[datetime] = Field(
        alias="createdAt", default=None)
    updated_at: Optional[datetime] = Field(
        alias="updatedAt", default=None)


class DBModelMixin(DateTimeModelMixin):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
