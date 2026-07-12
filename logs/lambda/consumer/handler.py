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
  "idTarget" STRING, details STRING, execution_time DOUBLE
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


def _build_insert(log):
    return (
        'INSERT INTO Logs (date, "user", action, "targetType", "idTarget", details, execution_time) '
        "VALUES ({date}, {user}, {action}, {target_type}, {id_target}, {details}, {exec_time})".format(
            date=_ts(log.get("date")),
            user=_q(log.get("user")),
            action=_q(log.get("action")),
            target_type=_q(log.get("targetType")),
            id_target=_q(log.get("idTarget")),
            details=_q(log.get("details", "")),
            exec_time=_num(log.get("execution_time", 0)),
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
                print(f"[OK] {message_id}: {log.get('action')} / {log.get('targetType')}")
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
