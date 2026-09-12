import json
import logging
import time
import asyncio
import inspect
import uuid
from datetime import datetime
from typing import Callable, Optional
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from ..models.sync import LoggingMiddlewareParameters, SqsParameters
from ..services.sqs import send_log_to_sqs

from .auth import get_current_user
from .context import request_context
from ..db.mongodb import get_database

# Configurar el logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('api.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Los mensajes de error pueden traer stack traces enteros. La columna es STRING
# y el INSERT de la Lambda es SQL literal, así que se recorta antes de encolar.
MAX_ERROR_MESSAGE = 1000


def _truncate(value: Optional[str], limit: int = MAX_ERROR_MESSAGE) -> Optional[str]:
    """
    Recorta conservando la parte informativa, que depende del tipo de mensaje.

    En un mensaje de una línea lo importante está al principio. En un traceback
    está al FINAL: las primeras líneas son el arranque de uvicorn y de starlette,
    siempre iguales, y la excepción real es la última. Recortar por el principio
    dejaba justamente fuera la línea que explica el fallo.
    """
    if value is None:
        return None
    value = str(value)
    if len(value) <= limit:
        return value
    if "\n" in value:
        return "…[truncado]\n" + value[-limit:]
    return value[:limit] + "…[truncado]"


def _dispatch_to_sqs(params: SqsParameters) -> None:
    """Encola el log sin bloquear el event loop (SQS es una llamada de red)."""
    asyncio.get_event_loop().run_in_executor(None, send_log_to_sqs, params)


# A partir de qué status se audita una respuesta HTTP. 400 incluye los 401/403,
# que en una plataforma de secretos son la señal que más interesa conservar.
AUDIT_HTTP_MIN_STATUS = 400

# Segundos a partir de los cuales una petición se considera lenta. Estaba en 1s,
# pero el tiempo de respuesta habitual de esta API ronda 1-4s, así que casi todas
# lo cruzaban: system_logs se llenaba de avisos rutinarios y los fallos reales
# (cifrado, rotación) quedaban sepultados y competían por el tope antiinundación.
SLOW_REQUEST_SECONDS = 3.0

# Marca en el scope ASGI: el decorador de servicio ya auditó este fallo, así que
# el middleware no debe registrarlo otra vez. El scope es un dict compartido por
# toda la petición, así que la marca sube del endpoint al middleware.
AUDITED_FLAG = "tek_audit_logged"

# Claves que el resto de la petición deja en el scope para que la auditoría las
# recoja: el id de usuario lo pone get_current_user tras validar el token.
USER_ID_KEY = "tek_user_id"
REQUEST_ID_KEY = "tek_request_id"

# Tope al leer el cuerpo de una respuesta de error para extraer el motivo.
MAX_ERROR_BODY = 8192


def _request_meta() -> dict:
    """
    Contexto de la petición en curso para adjuntar al log. Devuelve vacío si no
    hay request (llamadas internas, tareas de fondo).
    """
    try:
        request: Request = request_context.get()
    except LookupError:
        return {}
    return {
        "client_ip": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
        "method": request.method,
        "request_id": request.scope.get(REQUEST_ID_KEY),
    }


async def _read_error_body(response: Response):
    """
    Consume el cuerpo de una respuesta de error para sacar el `detail` real y
    devuelve una respuesta equivalente (el iterador original queda agotado).

    Solo se llama con status >= 400 y content-type JSON: así las descargas y los
    streaming no se bufferean nunca en memoria.
    """
    body = b""
    async for chunk in response.body_iterator:
        body += chunk

    # Content-length se recalcula solo al reconstruir; arrastrar el viejo lo rompe.
    headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
    rebuilt = Response(
        content=body,
        status_code=response.status_code,
        headers=headers,
        media_type=response.media_type,
    )

    detail = None
    try:
        payload = json.loads(body[:MAX_ERROR_BODY] or b"{}")
        if isinstance(payload, dict):
            detail = payload.get("detail") or payload.get("message")
            if detail is not None and not isinstance(detail, str):
                detail = json.dumps(detail, ensure_ascii=False)
    except (ValueError, UnicodeDecodeError):
        detail = None

    return rebuilt, detail


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware para logging automático de todas las peticiones HTTP
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Guardar el request en el contexto
        token = request_context.set(request)

        # Identificador de correlación: todas las filas de auditoría que genere
        # esta petición lo comparten.
        request.scope[REQUEST_ID_KEY] = uuid.uuid4().hex[:16]

        # Tiempo de inicio
        start_time = time.time()

        # Información de la petición
        safe_headers = {k: v for k, v in dict(request.headers).items()
            if k.lower() not in ['authorization', 'x-github-token']}

        # request_info = {
        #     "timestamp": datetime.now().isoformat(),
        #     "method": request.method,
        #     "url": str(request.url),
        #     "path": request.url.path,
        #     "query_params": dict(request.query_params),
        #     "headers": safe_headers,
        #     "client_ip": request.client.host if request.client else None,
        #     "user_agent": request.headers.get("user-agent"),
        # }

        logger.info(f"Request started: {request.method} {request.url.path}")

        try:
            response = await call_next(request)

            # Calcular tiempo de respuesta
            process_time = time.time() - start_time

            # Información de respuesta
            # response_info = {
            #     "status_code": response.status_code,
            #     "process_time": round(process_time, 4),
            #     "response_headers": dict(response.headers)
            # }

            # Log de finalización exitosa
            logger.info(
                f"Request completed: {request.method} {request.url.path} - "
                f"Status: {response.status_code} - Time: {process_time:.4f}s"
            )

            # Log detallado si es necesario
            if process_time > SLOW_REQUEST_SECONDS:
                # La duración va en `extra` además de en el texto: en el stdout se
                # lee, y en system_logs.duration_ms se puede ordenar y promediar,
                # que dentro de una cadena no se puede.
                logger.warning(
                    f"Slow request detected: {request.method} {request.url.path} "
                    f"took {process_time:.4f}s",
                    extra={"duration_ms": round(process_time * 1000, 2)},
                )

            # Una HTTPException (401, 403, 404...) la convierte FastAPI en respuesta
            # antes de llegar al except de abajo, así que el fallo se detecta aquí.
            # Si un servicio decorado ya lo auditó, no se duplica.
            if (
                response.status_code >= AUDIT_HTTP_MIN_STATUS
                and not request.scope.get(AUDITED_FLAG)
            ):
                detail = None
                # Solo se toca el cuerpo si es JSON: las descargas y los streaming
                # se dejan intactos.
                if (response.headers.get("content-type") or "").startswith("application/json"):
                    try:
                        response, detail = await _read_error_body(response)
                    except Exception as read_err:
                        logger.error(f"❌ No se pudo leer el cuerpo del error: {read_err}")

                self._audit_http_failure(
                    request,
                    status_code=response.status_code,
                    error_type="HTTPStatus",
                    message=detail or f"Respuesta {response.status_code}",
                    process_time=process_time,
                )

            return response

        except Exception as e:
            # Log de errores
            process_time = time.time() - start_time
            logger.error(
                f"Request failed: {request.method} {request.url.path} - "
                f"Error: {str(e)} - Time: {process_time:.4f}s"
            )
            if not request.scope.get(AUDITED_FLAG):
                self._audit_http_failure(
                    request,
                    status_code=500,
                    error_type=type(e).__name__,
                    message=str(e),
                    process_time=process_time,
                )
            raise
        finally:
            # Limpiar el contexto después de cada petición
            request_context.reset(token)

    @staticmethod
    def _audit_http_failure(request: Request, status_code: int, error_type: str,
                            message: str, process_time: float) -> None:
        """
        Red de seguridad: audita los fallos que nunca llegan a un servicio
        decorado (rechazos de autenticación, rutas inexistentes, errores de
        dependencias).

        El usuario se toma del scope, donde lo dejó get_current_user si el token
        era válido. Queda vacío solo cuando la autenticación fue justamente lo
        que falló, que es el único caso en que no hay identidad que registrar.
        """
        try:
            _dispatch_to_sqs(
                SqsParameters(
                    user=request.scope.get(USER_ID_KEY) or "",
                    action=f"HTTP_{status_code}",
                    targetType="http",
                    idTarget="",
                    details=request.url.path,
                    execution_time=process_time,
                    level="ERROR",
                    status_code=status_code,
                    error_type=error_type,
                    error_message=_truncate(message),
                    client_ip=request.client.host if request.client else None,
                    user_agent=request.headers.get("user-agent"),
                    method=request.method,
                    request_id=request.scope.get(REQUEST_ID_KEY),
                )
            )
        except Exception as log_err:
            logger.error(f"❌ No se pudo auditar el fallo HTTP: {log_err}")

class ServiceLoggingMiddleware:
    """
    Middleware para logging específico de servicios
    """

    @staticmethod
    def log_service_call(service_name: str, method_name: str, request_info: dict, **kwargs):
        """
        Call of service logging
        """
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "service": service_name,
            "method": method_name,
            "parameters": kwargs,
            "type": "service_call"
        }

        logger.info(f"Service call: {service_name}.{method_name}")

        return log_data

    @staticmethod
    async def log_service_response(response_data, request_info: Optional[LoggingMiddlewareParameters], execution_time: Optional[float] = None):
        """
        Response of service logging. Runs SQS send in thread pool to avoid blocking.
        """
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "method": request_info.action if request_info else "unknown_action",
            "execution_time": execution_time,
            "type": "service_response"
        }

        # Enviar a SQS de forma no-bloqueante usando executor
        _dispatch_to_sqs(
            SqsParameters(
                user=(request_info.user_id if request_info and request_info.user_id else ""),
                action=(request_info.action if request_info else "unknown_action"),
                targetType=(request_info.target_type if request_info else "unknown_target"),
                idTarget=(request_info.target_id if request_info and request_info.target_id else ""),
                execution_time=execution_time,
                details=(request_info.path if request_info else "internal"),
                level="INFO",
                **_request_meta(),
            )
        )

        logger.info(
            f"Service response - Type: {type(response_data).__name__} - "
            + (f"Time: {execution_time:.4f}s" if execution_time else "Time: N/A")
        )
        return log_data

    @staticmethod
    async def log_service_error(error: BaseException, request_info: Optional[LoggingMiddlewareParameters], execution_time: Optional[float] = None):
        """
        Gemelo de log_service_response para el camino de fallo.

        Sin esto la tabla Logs solo contendría éxitos: un intento denegado de leer
        o rotar un secreto no dejaría rastro consultable, que es justo lo que una
        auditoría tiene que capturar.
        """
        # HTTPException trae el código; el resto de excepciones son un 500 de facto.
        status_code = getattr(error, "status_code", None) or 500
        # HTTPException guarda el motivo en .detail, no en str(e).
        message = getattr(error, "detail", None) or str(error)

        params = SqsParameters(
            user=(request_info.user_id if request_info and request_info.user_id else ""),
            action=(request_info.action if request_info else "unknown_action"),
            targetType=(request_info.target_type if request_info else "unknown_target"),
            idTarget=(request_info.target_id if request_info and request_info.target_id else ""),
            execution_time=execution_time,
            details=(request_info.path if request_info else "internal"),
            level="ERROR",
            status_code=status_code,
            error_type=type(error).__name__,
            error_message=_truncate(message),
            **_request_meta(),
        )
        _dispatch_to_sqs(params)
        return params

def create_service_logger(serviceName: str, action: str, targetType: str):
    """
    Factory para crear loggers específicos de servicios
    """

    def log_decorator(func):
        import functools

        # OPTIMIZACIÓN: cachear la firma UNA VEZ al decorar, no en cada invocación
        func_signature = inspect.signature(func)

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            request_info = None

            # Parámetros = argumentos de la FUNCIÓN DECORADA, no del request HTTP.
            # Ejemplo: @_create_invitation(target_id, db, organization_id, email, role)
            # al llamarse con (user.id, db, org_id, "a@b.com", "member") produce:
            #   params = {"target_id": "...", "db": <mongo>, "organization_id": "...",
            #             "email": "a@b.com", "role": "member"}
            # Abajo solo se usa params["target_id"] como idTarget del log de auditoría.
            bound_args = func_signature.bind(*args, **kwargs)  # empareja *args con nombres de la firma
            bound_args.apply_defaults()  # rellena los que no se pasaron con su default
            params = dict(bound_args.arguments)  # {nombre_param: valor}

            try:
                # Informatica de la request
                request: Request = request_context.get()
                headers = dict(request.headers)

                # Filtrar headers sensibles para logging
                github_token = headers.get("x-github-token")

                current_user = None
                # Try to get current user
                if github_token:
                    db = await get_database()
                    current_user = await get_current_user(github_token, db)

                # Build request info
                request_info = LoggingMiddlewareParameters(
                    service_name=serviceName,
                    action=action,
                    target_type=targetType,
                    target_id=(str(params.get("target_id")) if params.get("target_id") is not None else None),
                    user_id=getattr(current_user, "id", None),
                    method=request.method,
                    path=request.url.path
                )

            except LookupError:
                logger.warning("🚧 No hay request en el contexto. Usando valores por defecto para logging.")
            except Exception as e:
                logger.error(f"❌ Error al construir request_info: {str(e)}")

            try:
                # Make the function call of the service
                result = await func(*args, **kwargs)

                execution_time = time.time() - start_time

                # Log the service call (now async)
                await ServiceLoggingMiddleware.log_service_response(
                    result,
                    request_info,
                    execution_time,
                )

                return result

            except Exception as e:
                execution_time = time.time() - start_time
                logger.error(
                    f"Service error: {serviceName}.{action} - "
                    f"Error: {str(e)} - Time: {execution_time:.4f}s"
                )
                # Auditar el fallo antes de relanzar. Si el propio logging falla,
                # no puede tapar la excepción original: se traga y se relanza igual.
                try:
                    await ServiceLoggingMiddleware.log_service_error(
                        e, request_info, execution_time
                    )
                    # Evita que el middleware vuelva a registrar la misma respuesta.
                    request_context.get().scope[AUDITED_FLAG] = True
                except LookupError:
                    pass  # sin request en contexto: nada que marcar
                except Exception as log_err:
                    logger.error(f"❌ No se pudo auditar el fallo: {log_err}")
                raise

        return wrapper

    return log_decorator
