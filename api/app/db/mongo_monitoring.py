"""
Listeners de PyMongo: llevan los fallos de MongoDB a la tabla system_logs.

Por qué esta vía y no los logs de Atlas: `system.profile`, el Query Profiler y la
descarga del log de mongod requieren cluster M10 o superior. El command monitoring
del driver funciona en cualquier tier, incluido M0.

⚠️ PRIVACIDAD — lo más importante de este módulo.
El evento incluye `event.command`, el documento COMPLETO del comando: valores de
secretos, filtros de búsqueda, tokens. Copiarlo al log convertiría la tabla de
logs en una segunda base de secretos sin cifrar. Aquí solo se extrae el NOMBRE de
la colección; el resto del documento nunca se toca.

Los eventos no se mandan a SQS directamente: se emiten por el logger normal y
viajan por el pipeline de system_logging, que ya resuelve el no bloquear (los
callbacks corren en el hilo del socket de Mongo) y el antiinundación (si Mongo
cae, cada comando falla y cada heartbeat también).
"""
import logging
from typing import Optional

from pymongo import monitoring

logger = logging.getLogger(__name__)

# Comandos internos del driver: se ejecutan solos, en volumen, y sus fallos son
# ruido — cuando fallan es porque la conexión ya está rota, cosa que informa el
# listener de heartbeat con mejor contexto.
IGNORED_COMMANDS = {"ismaster", "hello", "ping", "endSessions", "buildInfo", "getLastError"}


def _collection_name(event) -> Optional[str]:
    """
    Nombre de la colección, y NADA más del comando.

    En find/insert/update/delete/aggregate el primer valor del documento es el
    nombre de la colección. En otros comandos es un 1 u otro valor: por eso solo
    se acepta si es str. Nunca se lee otra clave del documento.
    """
    try:
        value = event.command.get(event.command_name)
        return value if isinstance(value, str) else None
    except Exception:
        return None


def _failure_text(event) -> str:
    """Mensaje del fallo. `failure` es un dict del servidor o una excepción."""
    failure = getattr(event, "failure", None)
    if isinstance(failure, dict):
        errmsg = failure.get("errmsg") or failure.get("$err") or str(failure)
        code = failure.get("code")
        return f"{errmsg} (code={code})" if code is not None else str(errmsg)
    return str(failure)


class MongoCommandLogger(monitoring.CommandListener):
    """Registra los comandos que el servidor rechaza o que expiran."""

    def started(self, event):      # obligatorio por la interfaz
        pass

    def succeeded(self, event):
        pass

    def failed(self, event):
        if event.command_name in IGNORED_COMMANDS:
            return
        try:
            logger.error(
                f"MongoDB: {event.command_name} falló — {_failure_text(event)}",
                extra={
                    "source": "mongo",
                    "operation": event.command_name,
                    "collection": _collection_name(event),
                    "duration_ms": round(event.duration_micros / 1000, 2),
                },
            )
        except Exception:
            pass  # un listener nunca puede tumbar una operación de base de datos


class MongoHeartbeatLogger(monitoring.ServerHeartbeatListener):
    """
    Registra cuando un nodo deja de responder.

    Cubre el hueco del listener de comandos: si Mongo está INALCANZABLE no hay
    CommandFailedEvent, porque la excepción salta durante la selección de servidor.
    Es exactamente el fallo que tumbó el arranque de la API (SSL handshake failed
    contra los tres nodos) y que no habría dejado rastro por la otra vía.

    Los heartbeats se repiten cada ~10s mientras dure la caída; el enfriamiento
    del pipeline de system_logging colapsa las repeticiones.
    """

    def started(self, event):
        pass

    def succeeded(self, event):
        pass

    def failed(self, event):
        try:
            logger.error(
                f"MongoDB: nodo {event.connection_id} no responde — {event.reply}",
                extra={
                    "source": "mongo",
                    "operation": "heartbeat",
                    "collection": None,
                    "duration_ms": round(event.duration * 1000, 2),
                },
            )
        except Exception:
            pass


def get_mongo_listeners() -> list:
    """Listeners para pasar como `event_listeners` al crear el cliente."""
    return [MongoCommandLogger(), MongoHeartbeatLogger()]
