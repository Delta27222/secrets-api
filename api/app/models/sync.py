from typing import Optional
from pydantic import BaseModel

class SyncResponse(BaseModel):
  code: str
  environmentId: Optional[str] = None

class MismatchSecrets(SyncResponse):
  secretsMismatched: list[str]

class SqsParameters(BaseModel):
  user: str
  action: str
  targetType: str
  idTarget: str
  details: str
  execution_time: Optional[float] = None

class LoggingMiddlewareParameters(BaseModel):
  service_name: str
  action: str
  target_type: str
  target_id: Optional[str]
  user_id: Optional[str]
  method: str
  path: str
