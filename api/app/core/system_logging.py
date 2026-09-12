"""
Envío de los logs de SISTEMA a QuestDB (vía SQS → Lambda → tabla system_logs).

Qué captura: los fallos internos que NO se convierten en respuesta HTTP y que por
tanto no dejan rastro en la auditoría. El caso que motivó esto:

    # services/environment.py
    logger.error(f"Error decrypting field: {e}")
    return None          # ← se traga la excepción: no hay 500, no hay fila en Logs

Tres problemas que resuelve este módulo:

1. NO BLOQUEAR. send_log_to_sqs es I/O de red síncrona y un logger se llama desde
   cualquier hilo, con o sin event loop. Se usa QueueHandler + QueueListener: el
   emit solo encola en memoria y un hilo aparte hace la llamada a AWS.

2. NO ENTRAR EN BUCLE. Si el envío a SQS falla, services/sqs.py hace logger.error,
   que volvería a intentar enviarse a SQS. Esos loggers se excluyen por nombre.

3. NO INUNDAR. Si Mongo se cae, cada petición genera el mismo error. Se aplica un
   enfriamiento por mensaje repetido y un tope global por minuto.
"""
import logging
import logging.handlers
import queue
import sys
import threading
import time
from typing import Optional

from ..models.sync import SystemLogParameters
from ..services.sqs import send_log_to_sqs
from .context import request_context
from .logging import _truncate

logger = logging.getLogger(__name__)

# Umbral: los INFO son un "Request started/completed" por petición, redundante con
# la auditoría, que ya guarda cada acción con su tiempo.
MIN_LEVEL = logging.WARNING

# Tope del mensaje. El recorte lo hace _truncate, que en los multilínea conserva
# el final: en un traceback la excepción real es la última línea.
MAX_MESSAGE = 1000

# Loggers que NUNCA se envían: los dos primeros generarían un bucle, el resto es
# ruido de librerías de AWS que además se dispara justo cuando falla el envío.
EXCLUDED_LOGGERS = (
    "app.services.sqs",
    "app.core.system_logging",
    "botocore",
    "boto3",
    "urllib3",
    "s3transfer",
)

# Antiinundación.
DEDUPE_WINDOW_SECONDS = 60      # mismo mensaje repetido: se manda una vez por ventana
MAX_PER_MINUTE = 60             # tope global, pase lo que pase
QUEUE_MAX_SIZE = 1000           # si se llena, se descarta (mejor perder logs que RAM)


class _Throttle:
    """Enfriamiento por mensaje + tope global. Seguro entre hilos."""

    def __init__(self):
        self._seen: dict[tuple, float] = {}
        self._window_start = time.monotonic()
        self._window_count = 0
        self._lock = threading.Lock()

    def allow(self, key: tuple) -> bool:
        now = time.monotonic()
        with self._lock:
            # Tope global por minuto.
            if now - self._window_start >= 60:
                self._window_start = now
                self._window_count = 0
            if self._window_count >= MAX_PER_MINUTE:
                return False

            # Enfriamiento del mensaje concreto.
            last = self._seen.get(key)
            if last is not None and now - last < DEDUPE_WINDOW_SECONDS:
                return False

            # Limpieza perezosa: sin esto el dict crece sin límite.
            if len(self._seen) > 500:
                corte = now - DEDUPE_WINDOW_SECONDS
                self._seen = {k: v for k, v in self._seen.items() if v > corte}

            self._seen[key] = now
            self._window_count += 1
            return True


_throttle = _Throttle()


def _current_request_id() -> Optional[str]:
    """Id de correlación para cruzar con la fila de Logs de la misma petición."""
    try:
        return request_context.get().scope.get("tek_request_id")
    except (LookupError, AttributeError):
        return None


class SqsSystemLogHandler(logging.Handler):
    """
    Convierte un LogRecord en SystemLogParameters y lo manda a SQS.

    Va SIEMPRE detrás de un QueueListener: aquí se hace la llamada de red, así que
    ejecutarlo en el hilo de la petición añadiría la latencia de AWS a cada error.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            # ── Filtro 1: nivel ──────────────────────────────────────────────
            # Descarta lo que esté por debajo del umbral (hoy, todo lo que no sea
            # WARNING o peor). Los INFO son un par de líneas por petición y son
            # redundantes con la auditoría, que ya guarda cada acción con su tiempo.
            #
            # Sí, el QueueHandler ya filtra por nivel al encolar. Se repite aquí
            # a propósito: si alguien engancha este handler directamente, sin la
            # cola delante, el umbral se sigue respetando.
            if record.levelno < MIN_LEVEL:
                return

            # ── Filtro 2: loggers excluidos (ANTI-BUCLE) ─────────────────────
            # Sin esto el sistema se muerde la cola. La secuencia sería:
            #
            #   1. send_log_to_sqs() falla (SQS caído, credenciales, red)
            #   2. services/sqs.py hace logger.error("Error al enviar log a SQS")
            #   3. ese registro llega hasta aquí
            #   4. se intenta enviar a SQS... y vuelve al paso 1, indefinidamente
            #
            # Se cortan por nombre ese logger y los de las librerías de AWS, que
            # además son las que hablan justo cuando el envío está fallando.
            #
            # startswith() acepta una tupla: basta con que el nombre empiece por
            # cualquiera de los prefijos, así "botocore.client" también entra.
            if record.name.startswith(EXCLUDED_LOGGERS):
                return

            # tek_message lo deja _TekQueueHandler.prepare(); getMessage() aquí
            # devolvería el texto ya formateado por el formatter del root logger.
            message = getattr(record, "tek_message", None) or record.getMessage()

            # La clave del enfriamiento usa solo el prefijo: los mensajes suelen
            # llevar un id o un timestamp al final que los haría todos distintos.
            if not _throttle.allow((record.name, record.levelno, message[:80])):
                return

            send_log_to_sqs(
                SystemLogParameters(
                    level=record.levelname,
                    # "mongo" lo ponen los listeners del driver; el resto es "system".
                    source=getattr(record, "tek_source", None) or "system",
                    logger=record.name,
                    message=_truncate(message, MAX_MESSAGE),
                    error_type=getattr(record, "tek_error_type", None),
                    operation=getattr(record, "tek_operation", None),
                    collection=getattr(record, "tek_collection", None),
                    duration_ms=getattr(record, "tek_duration_ms", None),
                    request_id=getattr(record, "tek_request_id", None),
                )
            )
        except Exception:
            # Un handler nunca puede tumbar a quien loguea.
            self.handleError(record)


def _resolve_error_type(record: logging.LogRecord) -> Optional[str]:
    """
    Tipo de la excepción asociada al log.

    Si el log no se hizo con exc_info=True, se mira sys.exc_info(). El patrón
    dominante en este código es:

        except Exception as e:
            logger.error(f"Error cifrando token: {e}")

    Ahí la excepción sigue viva en el hilo, así que se recupera el tipo sin
    tener que tocar las 30 y pico llamadas existentes. Fuera de un except,
    sys.exc_info() devuelve (None, None, None) y esto queda en null.
    """
    if record.exc_info and record.exc_info[0] is not None:
        return record.exc_info[0].__name__
    actual = sys.exc_info()[0]
    return actual.__name__ if actual is not None else None


class _TekQueueHandler(logging.handlers.QueueHandler):
    """
    QueueHandler con prepare() propio.

    El de la librería estándar formatea el mensaje y pone exc_info a None antes de
    encolar (para que el record sea serializable). Eso dejaría al handler de abajo
    sin el tipo de excepción y con el texto ya decorado por el formatter. Aquí se
    guardan ambos en atributos propios ANTES de delegar.

    También resuelve el request_id aquí y no en el otro extremo: el QueueListener
    corre en su propio hilo, donde el ContextVar de la petición ya no existe.
    """

    def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        record.tek_request_id = _current_request_id()
        record.tek_message = record.getMessage()
        record.tek_error_type = _resolve_error_type(record)
        # Campos estructurados por `extra`, para que sean columnas ordenables y
        # filtrables en vez de texto dentro del mensaje. Los rellenan el aviso de
        # petición lenta (duration_ms) y los listeners de Mongo (el resto).
        record.tek_duration_ms = getattr(record, "duration_ms", None)
        record.tek_source = getattr(record, "source", None)
        record.tek_operation = getattr(record, "operation", None)
        record.tek_collection = getattr(record, "collection", None)
        return super().prepare(record)


_listener: Optional[logging.handlers.QueueListener] = None


def setup_system_logging() -> None:
    """
    Engancha el envío al logger raíz. Idempotente: llamarlo dos veces no duplica.
    """
    global _listener
    if _listener is not None:
        return

    # ── 1. La cola EN MEMORIA ────────────────────────────────────────────────
    # Ojo: esta NO es la cola de AWS. Es el buzón interno del proceso, y es lo que
    # permite que quien loguea no espere a la red. Acotada a propósito: si se
    # llenara (SQS caído + errores en ráfaga) se descartan registros en vez de
    # crecer sin límite. Perder logs es preferible a agotar la memoria del
    # proceso que se está observando.
    log_queue: queue.Queue = queue.Queue(maxsize=QUEUE_MAX_SIZE)

    # ── 2. El extremo que ESCRIBE en la cola ─────────────────────────────────
    # Corre en el hilo de quien loguea. Lo único que hace es preparar el registro
    # y depositarlo: sin red, sin bloqueo. El setLevel descarta aquí lo que está
    # por debajo del umbral, para no encolar lo que luego se iba a tirar.
    queue_handler = _TekQueueHandler(log_queue)
    queue_handler.setLevel(MIN_LEVEL)

    # ── 3. El extremo que LEE de la cola ─────────────────────────────────────
    # Esta línea es la que une las dos mitades: el QueueListener saca registros de
    # `log_queue` y se los entrega a SqsSystemLogHandler, que es quien de verdad
    # llama a AWS. Todo eso ocurre en un hilo aparte, así que el filtrado, el
    # antiinundación y la llamada de red se pagan ahí y no en la petición.
    _listener = logging.handlers.QueueListener(
        log_queue, SqsSystemLogHandler(), respect_handler_level=True
    )

    # daemon: si el proceso muere de golpe (kill -9, caída del contenedor) este
    # hilo no lo mantiene vivo. El precio es perder lo que quedara en la cola;
    # un apagado limpio lo drena vía shutdown_system_logging().
    _listener.daemon = True
    _listener.start()

    # ── 4. Enganche al logger raíz ───────────────────────────────────────────
    # Se hace AL FINAL, con el consumidor ya corriendo: si se enganchara antes,
    # los primeros registros se quedarían en la cola sin nadie que los sacara.
    #
    # Va al raíz y no a un logger concreto porque en Python todo logger propaga
    # hacia arriba. Por eso alcanza también a los ajenos (uvicorn, pymongo,
    # starlette) sin tener que tocarlos: así se capturaron los tracebacks de
    # uvicorn.error cuando la app no arrancaba.
    logging.getLogger().addHandler(queue_handler)
    logger.info(
        "Logs de sistema hacia QuestDB activados (nivel >= %s)",
        logging.getLevelName(MIN_LEVEL),
    )


def shutdown_system_logging() -> None:
    """Drena la cola pendiente al apagar la API."""
    global _listener
    if _listener is not None:
        _listener.stop()
        _listener = None
