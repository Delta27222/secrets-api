from typing import Optional
from pydantic import BaseModel

class SyncResponse(BaseModel):
  code: str
  environmentId: Optional[str] = None

class MismatchSecrets(SyncResponse):
  secretsMismatched: list[str]

class SqsParameters(BaseModel):
  # Discrimina a qué tabla escribe la Lambda consumidora. Ambos tipos comparten
  # cola: separar colas obligaría a duplicar Lambda, IAM y event source mapping.
  log_type: str = "audit"
  user: str
  action: str
  targetType: str
  idTarget: str
  details: str
  execution_time: Optional[float] = None
  # Resultado de la operación. En los éxitos level="INFO" y el resto va null;
  # en los fallos se llenan y la Lambda consumidora los escribe en la tabla Logs.
  level: str = "INFO"
  status_code: Optional[int] = None
  error_type: Optional[str] = None
  error_message: Optional[str] = None
  # Contexto de la petición. user_agent distingue CLI de web app, que en la
  # auditoría de una rotación de llaves es información distinta.
  client_ip: Optional[str] = None
  user_agent: Optional[str] = None
  method: Optional[str] = None
  # Correlaciona las filas que produce una misma petición (un request puede
  # pasar por varios servicios decorados y generar varias entradas).
  request_id: Optional[str] = None

class LoggingMiddlewareParameters(BaseModel):
  service_name: str
  action: str
  target_type: str
  target_id: Optional[str]
  user_id: Optional[str]
  method: str
  path: str


class SystemLogParameters(BaseModel):
  """
  Fallo interno: los que NO se convierten en respuesta HTTP y por tanto no dejan
  rastro en la auditoría. El caso que motivó esto es services/environment.py, que
  loguea un fallo al descifrar y devuelve None sin lanzar.
  """
  log_type: str = "system"
  level: str
  source: str = "system"
  logger: str
  message: str
  error_type: Optional[str] = None
  # Específicos de los eventos de Mongo; null en source="system".
  operation: Optional[str] = None
  collection: Optional[str] = None
  duration_ms: Optional[float] = None
  # Cruza con la fila de Logs de la misma petición.
  request_id: Optional[str] = None
