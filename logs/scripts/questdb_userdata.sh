#!/bin/bash
# ============================================================================
# user_data — arranca QuestDB en la EC2 con Docker y el volumen EBS montado.
# Amazon Linux 2023. Se ejecuta una sola vez al crear la instancia.
# ============================================================================
set -euxo pipefail

# 1. Instalar Docker
dnf update -y
dnf install -y docker
systemctl enable --now docker

# 2. Montar el volumen EBS de datos en /mnt/questdb
#    En instancias Nitro el disco puede aparecer como /dev/nvme1n1;
#    en otras como /dev/xvdf. Se detecta el primero que exista.
DEVICE=""
for d in /dev/nvme1n1 /dev/xvdf /dev/sdf; do
  if [ -e "$d" ]; then DEVICE="$d"; break; fi
done

if [ -n "$DEVICE" ]; then
  # Formatear solo si el volumen está vacío (preserva datos en re-creaciones)
  if ! blkid "$DEVICE"; then
    mkfs -t xfs "$DEVICE"
  fi
  mkdir -p /mnt/questdb
  mount "$DEVICE" /mnt/questdb
  grep -q "/mnt/questdb" /etc/fstab || echo "$DEVICE /mnt/questdb xfs defaults,nofail 0 2" >> /etc/fstab
else
  # Sin volumen adicional: usar disco local (datos NO persistentes ante recreación)
  mkdir -p /mnt/questdb
fi

# 3. Ejecutar QuestDB
#    Puertos: 9000 (REST/web), 9009 (ILP), 8812 (Postgres), 9003 (métricas)
docker run -d --name questdb --restart unless-stopped \
  -p 9000:9000 -p 9009:9009 -p 8812:8812 -p 9003:9003 \
  -v /mnt/questdb:/var/lib/questdb \
  questdb/questdb:${questdb_version}

# 4. Crear las tablas de la aplicación (idempotente: CREATE TABLE IF NOT EXISTS).
#    Espera a que QuestDB responda y luego ejecuta el DDL vía su API REST.
#
#    OJO: este archivo pasa por templatefile() de Terraform, que interpola las
#    secuencias con dolar-llave. Las variables de shell van SIN llaves ($col), o
#    Terraform intenta evaluarlas y el plan falla.
for i in $(seq 1 30); do
  if curl -sf -o /dev/null "http://localhost:9000"; then break; fi
  sleep 3
done

qdb() {
  curl -s -G "http://localhost:9000/exec" --data-urlencode "query=$1"
}

# Tabla Logs (auditoría). Registra la acción y SU RESULTADO: las cuatro últimas
# columnas quedan null en los éxitos y se llenan cuando la operación falla.
qdb "CREATE TABLE IF NOT EXISTS Logs (date TIMESTAMP, user STRING, action STRING, targetType STRING, idTarget STRING, details STRING, execution_time DOUBLE, level SYMBOL, status_code INT, error_type STRING, error_message STRING, client_ip STRING, user_agent STRING, method SYMBOL, request_id STRING) TIMESTAMP(date) PARTITION BY DAY;"

# Upgrade de tablas preexistentes: si el EBS ya traía una tabla Logs con el
# esquema viejo, el CREATE de arriba es un no-op y NO añade las columnas nuevas.
# Estos ALTER las agregan; si ya existen, QuestDB devuelve error y se ignora.
for col in "level SYMBOL" "status_code INT" "error_type STRING" "error_message STRING" \
           "client_ip STRING" "user_agent STRING" "method SYMBOL" "request_id STRING"; do
  qdb "ALTER TABLE Logs ADD COLUMN $col;" >/dev/null || true
done

# Tabla system_logs: fallos INTERNOS, los que no llegan a producir una respuesta
# HTTP. Separada de Logs a propósito: Logs responde "quién hizo qué" y esta
# responde "qué se rompió". Mezclarlas ensuciaría el timeline de auditoría.
#   source     = system | mongo
#   logger     = módulo de origen (app.services.environment, app.core.csfle...)
#   request_id = cruza con la fila de Logs de la misma petición
# Las tres de mongo van null en las filas de source=system.
qdb "CREATE TABLE IF NOT EXISTS system_logs (date TIMESTAMP, level SYMBOL, source SYMBOL, logger STRING, message STRING, error_type STRING, operation STRING, collection STRING, duration_ms DOUBLE, request_id STRING) TIMESTAMP(date) PARTITION BY DAY;"

for col in "operation STRING" "collection STRING" "duration_ms DOUBLE" "request_id STRING"; do
  qdb "ALTER TABLE system_logs ADD COLUMN $col;" >/dev/null || true
done

qdb "CREATE TABLE IF NOT EXISTS encryption_key_audit (timestamp TIMESTAMP, action STRING, key_id STRING, project_id STRING, actor_id STRING, ip_address STRING, operation_result STRING, details STRING) TIMESTAMP(timestamp) PARTITION BY DAY;"
