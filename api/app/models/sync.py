from pydantic import BaseModel

class SyncResponse(BaseModel):
  code: str
  yam: bool
  status_code: int