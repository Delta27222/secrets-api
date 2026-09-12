"""
Consumidor SQS -> QuestDB.

Lambda disparada por la cola SQS de logs. Cada mensaje trae un log de servicio
(enviado por la API vía send_log_to_sqs) y se inserta en la tabla `Logs` de
QuestDB usando el protocolo Postgres-wire (puerto 8812) con pg8000.

⚠️ Particularidades de QuestDB por PG-wire (comprobadas empíricamente):
  - Ignora silenciosamente los INSERT PARAMETRIZADOS (protocolo extendido, `%s`):
    reporta éxito pero la fila NO persiste.
  - Ignora el `conn.commit()` explícito.
  - SOLO persiste con: autocommit=True + SQL LITERAL (simple query protocol).
Por eso se construye el INSERT como texto, escapando las comillas simples (`''`).
La API es la única fuente de estos valores (no entrada de usuario directa), pero
igual se escapa para no romper el SQL con comillas en `details`.

Schema de la tabla Logs (ver logs/README.md):
  date TIMESTAMP, "user" STRING, action STRING, "targetType" STRING,
  "idTarget" STRING, details STRING, execution_time DOUBLE,
  level SYMBOL, status_code INT, error_type STRING, error_message STRING,
  client_ip STRING, user_agent STRING, method SYMBOL, request_id STRING

Las cuatro últimas describen el RESULTADO: van null en los éxitos (level="INFO")
y se llenan cuando la operación falló, para que la auditoría no sea solo de
casos exitosos. Los mensajes ya vienen recortados desde la API.
"""
import json
import os

import pg8000


def _connect():
    conn = pg8000.connect(
        host=os.environ["DB_HOST"],
        database=os.environ.get("DB_NAME", "qdb"),
        user=os.environ.get("DB_USER", "admin"),
        password=os.environ.get("DB_PASSWORD", "quest"),
        port=int(os.environ.get("DB_PORT", 8812)),
        timeout=10,
    )
    # QuestDB solo persiste inserts con autocommit (ver docstring).
    conn.autocommit = True
    return conn


def _q(value):
    """Literal SQL string con comillas simples escapadas; NULL si es None."""
    if value is None:
        return "null"
    return "'" + str(value).replace("'", "''") + "'"


def _ts(raw):
    """Literal de timestamp: el ISO del log entre comillas, o now() si falta."""
    if not raw:
        return "now()"
    return _q(str(raw).replace("Z", ""))  # QuestDB parsea el ISO directo


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(value):
    """Literal de entero, o NULL si falta o no es convertible."""
    if value is None:
        return "null"
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return "null"


def _build_insert(log):
    """
    Enruta según log_type. Los dos tipos comparten cola SQS, así que el
    discriminador viaja en el propio mensaje.

    Los mensajes anteriores a este cambio no traen log_type: por defecto van a
    Logs, que es lo que eran.
    """
    if log.get("log_type") == "system":
        return _build_insert_system(log)
    return _build_insert_audit(log)


def _build_insert_system(log):
    """INSERT en system_logs: fallos internos que no producen respuesta HTTP."""
    return (
        "INSERT INTO system_logs (date, level, source, logger, message, error_type, "
        "operation, collection, duration_ms, request_id) "
        "VALUES ({date}, {level}, {source}, {logger}, {message}, {error_type}, "
        "{operation}, {collection}, {duration_ms}, {request_id})".format(
            date=_ts(log.get("date")),
            level=_q(log.get("level") or "ERROR"),
            source=_q(log.get("source") or "system"),
            logger=_q(log.get("logger")),
            message=_q(log.get("message")),
            error_type=_q(log.get("error_type")),
            operation=_q(log.get("operation")),
            collection=_q(log.get("collection")),
            duration_ms=_num(log.get("duration_ms")) if log.get("duration_ms") is not None else "null",
            request_id=_q(log.get("request_id")),
        )
    )


def _build_insert_audit(log):
    return (
        'INSERT INTO Logs (date, "user", action, "targetType", "idTarget", details, execution_time, '
        "level, status_code, error_type, error_message, "
        "client_ip, user_agent, method, request_id) "
        "VALUES ({date}, {user}, {action}, {target_type}, {id_target}, {details}, {exec_time}, "
        "{level}, {status_code}, {error_type}, {error_message}, "
        "{client_ip}, {user_agent}, {method}, {request_id})".format(
            date=_ts(log.get("date")),
            user=_q(log.get("user")),
            action=_q(log.get("action")),
            target_type=_q(log.get("targetType")),
            id_target=_q(log.get("idTarget")),
            details=_q(log.get("details", "")),
            exec_time=_num(log.get("execution_time", 0)),
            # Mensajes de error con comillas o saltos de línea pasan por _q(),
            # que escapa las comillas simples: es lo único que separa un stack
            # trace de romper el INSERT (el SQL es literal, no parametrizado).
            level=_q(log.get("level") or "INFO"),
            status_code=_int(log.get("status_code")),
            error_type=_q(log.get("error_type")),
            error_message=_q(log.get("error_message")),
            client_ip=_q(log.get("client_ip")),
            user_agent=_q(log.get("user_agent")),
            method=_q(log.get("method")),
            request_id=_q(log.get("request_id")),
        )
    )


def lambda_handler(event, context):
    records = event.get("Records", []) or []
    print(f"[START] {len(records)} mensaje(s) recibidos de SQS")

    failures = []
    conn = None
    try:
        conn = _connect()
        cursor = conn.cursor()
        print("[DB] Conectado a QuestDB (PG-wire, autocommit)")

        for record in records:
            message_id = record.get("messageId")
            try:
                log = json.loads(record.get("body") or "{}")
                cursor.execute(_build_insert(log))
                destino = "system_logs" if log.get("log_type") == "system" else "Logs"
                etiqueta = log.get("logger") if log.get("log_type") == "system" else log.get("action")
                print(f"[OK] {message_id}: {destino} <- {etiqueta}")
            except Exception as e:  # noqa: BLE001
                print(f"[ERROR] mensaje {message_id}: {e}")
                failures.append({"itemIdentifier": message_id})

        print(f"[DONE] insertados={len(records) - len(failures)} fallidos={len(failures)}")
    except Exception as e:  # noqa: BLE001 — fallo de conexión: reintentar todo el lote
        print(f"[FATAL] {e}")
        return {"batchItemFailures": [{"itemIdentifier": r.get("messageId")} for r in records]}
    finally:
        if conn:
            conn.close()

    # SQS borra los mensajes exitosos; reintenta solo los de batchItemFailures.
    return {"batchItemFailures": failures}
