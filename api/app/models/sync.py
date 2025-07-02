from typing import Optional
from pydantic import BaseModel

class SyncResponse(BaseModel):
  code: str
  environmentId: Optional[str] = None

class MismatchSecrets(SyncResponse):
  secretsMismatched: list[str]