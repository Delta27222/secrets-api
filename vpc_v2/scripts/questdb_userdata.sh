#!/bin/bash
# User data — EC2 QuestDB (Primary y Standby)
# Variables inyectadas por Terraform templatefile():
#   questdb_version, questdb_pg_password, ecr_registry, ecr_repo_questdb, aws_region

set -euo pipefail

LOG_FILE="/var/log/questdb_setup.log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "==== [$(date)] Iniciando setup de QuestDB ===="

ECR_IMAGE="${ecr_registry}/${ecr_repo_questdb}:${questdb_version}"
AWS_REGION="${aws_region}"

echo "[1/6] Actualizando sistema operativo..."
dnf update -y
dnf install -y aws-cli jq

echo "[2/6] Instalando Docker..."
dnf install -y docker
systemctl enable docker
systemctl start docker
docker --version

echo "[3/6] Descargando imagen QuestDB desde ECR..."

for attempt in $(seq 1 5); do
  if aws ecr get-login-password --region "$AWS_REGION" | \
      docker login --username AWS --password-stdin "${ecr_registry}" && \
      docker pull "$ECR_IMAGE"; then
    echo "Imagen $ECR_IMAGE descargada correctamente."
    break
  fi
  if [ "$attempt" = "5" ]; then
    echo "ERROR: no se pudo descargar $ECR_IMAGE tras 5 intentos."
    exit 1
  fi
  echo "Intento $attempt/5 fallo (probable timeout de red al arrancar). Reintentando en 15s..."
  sleep 15
done

echo "[4/6] Configurando volumen EBS de datos..."
DEVICE="/dev/xvdf"
MOUNT_POINT="/data/questdb"

for i in $(seq 1 12); do
  if [ -b "$DEVICE" ]; then
    echo "Dispositivo $DEVICE disponible."
    break
  fi
  echo "Esperando dispositivo $DEVICE... intento $i/12"
  sleep 5
done

if [ ! -b "$DEVICE" ]; then
  echo "ERROR: Dispositivo $DEVICE no encontrado después de 60 segundos."
  exit 1
fi

if ! blkid "$DEVICE" &>/dev/null; then
  echo "Formateando $DEVICE con ext4..."
  mkfs -t ext4 "$DEVICE"
fi

mkdir -p "$MOUNT_POINT"
mount "$DEVICE" "$MOUNT_POINT"

DEVICE_UUID=$(blkid -s UUID -o value "$DEVICE")
if ! grep -q "$DEVICE_UUID" /etc/fstab; then
  echo "UUID=$DEVICE_UUID $MOUNT_POINT ext4 defaults,nofail 0 2" >> /etc/fstab
fi

mkdir -p "$MOUNT_POINT/db" "$MOUNT_POINT/conf" "$MOUNT_POINT/log"
chown -R 10001:10001 "$MOUNT_POINT"
echo "Volumen montado en $MOUNT_POINT."

echo "[5/6] Creando configuración de QuestDB..."
cat > "$MOUNT_POINT/conf/server.conf" << QUESTDB_CONF
http.bind.to=0.0.0.0:9000
http.min.enabled=false

pg.enabled=true
pg.net.bind.to=0.0.0.0:8812
pg.user=admin
pg.password=${questdb_pg_password}

line.tcp.enabled=true
line.tcp.net.bind.to=0.0.0.0:9009

cairo.sql.copy.buffer.size=2m
shared.worker.count=2
http.worker.count=1
pg.worker.count=1
QUESTDB_CONF

chown 10001:10001 "$MOUNT_POINT/conf/server.conf"
chmod 600 "$MOUNT_POINT/conf/server.conf"

echo "[6/6] Arrancando contenedor QuestDB ${questdb_version}..."
docker run \
  --detach \
  --name questdb \
  --restart unless-stopped \
  --publish 9000:9000 \
  --publish 8812:8812 \
  --publish 9009:9009 \
  --volume /data/questdb:/root/.questdb \
  --memory="1g" \
  --memory-swap="1g" \
  --cpus="1.5" \
  --security-opt no-new-privileges:true \
  "$ECR_IMAGE"

sleep 10
if docker ps | grep -q questdb; then
  echo "QuestDB corriendo correctamente."
else
  echo "ERROR: El contenedor questdb no está corriendo."
  docker logs questdb || true
  exit 1
fi

echo "Verificando que QuestDB responde..."
for i in $(seq 1 12); do
  if curl -sf "http://localhost:9000/exec?query=SELECT+1" > /dev/null; then
    echo "QuestDB responde en el puerto 9000."
    break
  fi
  echo "QuestDB no responde aún... intento $i/12"
  sleep 10
done

# ============================================================================
# Crear las tablas de la aplicación (idempotente: CREATE TABLE IF NOT EXISTS).
# QuestDB SOLO autocrea tablas por line protocol (ILP, :9009) — el INSERT por
# Postgres-wire (:8812, que es lo que usa la Lambda logs-consumer) exige que
# la tabla ya exista de antemano. Sin esto, todo INSERT falla con
# "table does not exist" aunque la Lambda y la cola SQS funcionen bien.
#
# OJO: este archivo pasa por templatefile() de Terraform, que interpola
# secuencias con dolar-llave. Las variables de shell van SIN llaves ($col),
# o Terraform intenta evaluarlas y el plan falla.
# ============================================================================
echo "Creando tablas de la aplicacion..."

qdb() {
  curl -s -G "http://localhost:9000/exec" --data-urlencode "query=$1"
}

# Logs (auditoria): quien hizo que, sobre que, y con que resultado. Las
# cuatro ultimas columnas quedan null en los exitos y se llenan si falla.
qdb "CREATE TABLE IF NOT EXISTS Logs (date TIMESTAMP, user STRING, action STRING, targetType STRING, idTarget STRING, details STRING, execution_time DOUBLE, level SYMBOL, status_code INT, error_type STRING, error_message STRING, client_ip STRING, user_agent STRING, method SYMBOL, request_id STRING) TIMESTAMP(date) PARTITION BY DAY;"

for col in "level SYMBOL" "status_code INT" "error_type STRING" "error_message STRING" \
           "client_ip STRING" "user_agent STRING" "method SYMBOL" "request_id STRING"; do
  qdb "ALTER TABLE Logs ADD COLUMN $col;" >/dev/null || true
done

# system_logs: fallos internos que no llegan a producir una respuesta HTTP
# (source=system) o errores de Mongo (source=mongo). Separada de Logs a
# proposito — Logs responde "quien hizo que", esta responde "que se rompio".
qdb "CREATE TABLE IF NOT EXISTS system_logs (date TIMESTAMP, level SYMBOL, source SYMBOL, logger STRING, message STRING, error_type STRING, operation STRING, collection STRING, duration_ms DOUBLE, request_id STRING) TIMESTAMP(date) PARTITION BY DAY;"

for col in "operation STRING" "collection STRING" "duration_ms DOUBLE" "request_id STRING"; do
  qdb "ALTER TABLE system_logs ADD COLUMN $col;" >/dev/null || true
done

qdb "CREATE TABLE IF NOT EXISTS encryption_key_audit (timestamp TIMESTAMP, action STRING, key_id STRING, project_id STRING, actor_id STRING, ip_address STRING, operation_result STRING, details STRING) TIMESTAMP(timestamp) PARTITION BY DAY;"

echo "==== [$(date)] Setup de QuestDB completado ===="
