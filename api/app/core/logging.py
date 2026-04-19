import logging
import time
import asyncio
import inspect
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


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware para logging automático de todas las peticiones HTTP
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Guardar el request en el contexto
        token = request_context.set(request)

        # Tiempo de inicio
        start_time = time.time()

        # Información de la petición
        safe_headers = {k: v for k, v in dict(request.headers).items()
                       if k.lower() not in ['authorization', 'x-github-token']}

        request_info = {
            "timestamp": datetime.now().isoformat(),
            "method": request.method,
            "url": str(request.url),
            "path": request.url.path,
            "query_params": dict(request.query_params),
            "headers": safe_headers,
            "client_ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent"),
        }

        logger.info(f"Request started: {request.method} {request.url.path}")

        try:
            response = await call_next(request)

            # Calcular tiempo de respuesta
            process_time = time.time() - start_time

            # Información de respuesta
            response_info = {
                "status_code": response.status_code,
                "process_time": round(process_time, 4),
                "response_headers": dict(response.headers)
            }

            # Log de finalización exitosa
            logger.info(
                f"Request completed: {request.method} {request.url.path} - "
                f"Status: {response.status_code} - Time: {process_time:.4f}s"
            )

            # Log detallado si es necesario
            if process_time > 1.0:  # Log detallado para peticiones lentas
                logger.warning(
                    f"Slow request detected: {request.method} {request.url.path} "
                    f"took {process_time:.4f}s"
                )

            return response

        except Exception as e:
            # Log de errores
            process_time = time.time() - start_time
            logger.error(
                f"Request failed: {request.method} {request.url.path} - "
                f"Error: {str(e)} - Time: {process_time:.4f}s"
            )
            raise
        finally:
            # Limpiar el contexto después de cada petición
            request_context.reset(token)

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
        loop = asyncio.get_event_loop()
        loop.run_in_executor(
            None,
            send_log_to_sqs,
            SqsParameters(
                user=(request_info.user_id if request_info and request_info.user_id else ""),
                action=(request_info.action if request_info else "unknown_action"),
                targetType=(request_info.target_type if request_info else "unknown_target"),
                idTarget=(request_info.target_id if request_info and request_info.target_id else ""),
                execution_time=execution_time,
                details=(request_info.path if request_info else "internal"),
            )
        )

        logger.info(
            f"Service response - Type: {type(response_data).__name__} - "
            + (f"Time: {execution_time:.4f}s" if execution_time else "Time: N/A")
        )
        return log_data

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

            # Obtener los parámetros con nombres (sig ya cacheada)
            bound_args = func_signature.bind(*args, **kwargs)
            bound_args.apply_defaults()
            params = dict(bound_args.arguments)

            try:
                request: Request = request_context.get()
                headers = dict(request.headers)

                # Filtrar headers sensibles para logging
                safe_headers = {k: v for k, v in headers.items()
                               if k.lower() not in ['authorization', 'x-github-token']}

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
                raise

        return wrapper

    return log_decorator
