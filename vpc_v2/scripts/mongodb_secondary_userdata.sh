#!/bin/bash
# User data — EC2 MongoDB Secondary
# Variables inyectadas por Terraform templatefile():
#   mongodb_version, replica_set_name, ecr_registry, ecr_repo_mongodb, aws_region
#
# El Secondary NO inicializa el Replica Set — arranca y espera a que el
# Primary lo incluya via rs.initiate().

set -euo pipefail

LOG_FILE="/var/log/mongodb_secondary_setup.log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "==== [$(date)] Iniciando setup de MongoDB Secondary ===="

ECR_IMAGE="${ecr_registry}/${ecr_repo_mongodb}:${mongodb_version}"
AWS_REGION="${aws_region}"
RS_NAME="${replica_set_name}"

echo "[1/6] Habilitando Docker (preinstalado en Amazon Linux 2023)..."
systemctl enable docker
systemctl start docker
docker --version

echo "[2/6] Descargando imagen MongoDB desde ECR..."

for attempt in $(seq 1 5); do
  if aws ecr get-login-password --region "$AWS_REGION" | \
      docker login --username AWS --password-stdin "${ecr_registry}" && \
      docker pull "$ECR_IMAGE"; then
    echo "Imagen $ECR_IMAGE descargada."
    break
  fi
  if [ "$attempt" = "5" ]; then
    echo "ERROR: no se pudo descargar $ECR_IMAGE tras 5 intentos."
    exit 1
  fi
  echo "Intento $attempt/5 fallo (probable timeout de red al arrancar). Reintentando en 15s..."
  sleep 15
done

echo "[3/6] Configurando volumen EBS..."
DEVICE="/dev/xvdf"
MOUNT_POINT="/data/mongodb"

for i in $(seq 1 12); do
  if [ -b "$DEVICE" ]; then break; fi
  echo "Esperando $DEVICE... intento $i/12"
  sleep 5
done

[ -b "$DEVICE" ] || { echo "ERROR: $DEVICE no encontrado."; exit 1; }

if ! blkid "$DEVICE" &>/dev/null; then
  mkfs -t xfs "$DEVICE"
fi

mkdir -p "$MOUNT_POINT"
mount "$DEVICE" "$MOUNT_POINT"

DEVICE_UUID=$(blkid -s UUID -o value "$DEVICE")
grep -q "$DEVICE_UUID" /etc/fstab || \
  echo "UUID=$DEVICE_UUID $MOUNT_POINT xfs defaults,nofail 0 2" >> /etc/fstab

mkdir -p "$MOUNT_POINT/db" "$MOUNT_POINT/logs"
chown -R 999:999 "$MOUNT_POINT"
echo "Volumen montado en $MOUNT_POINT."

# keyFile para autenticacion interna del RS — debe ser identico en los 3 nodos.
echo "${mongodb_keyfile}" > "$MOUNT_POINT/keyfile"
chown 999:999 "$MOUNT_POINT/keyfile"
chmod 400 "$MOUNT_POINT/keyfile"

echo "[4/6] Arrancando MongoDB Secondary (fase init, sin auth)..."
docker run \
  --detach \
  --name mongodb-secondary \
  --restart unless-stopped \
  --publish 27017:27017 \
  --volume "$MOUNT_POINT/db:/data/db" \
  --volume "$MOUNT_POINT/logs:/var/log/mongodb" \
  --memory="3g" \
  --cpus="1.5" \
  --security-opt no-new-privileges:true \
  "$ECR_IMAGE" \
  mongod --replSet "$RS_NAME" --bind_ip_all --port 27017

sleep 10

if ! docker ps | grep -q mongodb-secondary; then
  echo "ERROR: El contenedor mongodb-secondary no arrancó."
  docker logs mongodb-secondary || true
  exit 1
fi

echo "MongoDB Secondary corriendo (sin auth). Esperando rs.initiate() del Primary..."

echo "[5/6] Esperando a que el Replica Set se inicialice..."

MAX_WAIT=600
INTERVAL=15
ELAPSED=0

while [ $ELAPSED -lt $MAX_WAIT ]; do
  RS_STATE=$(docker exec mongodb-secondary mongosh --quiet --eval \
    "try { rs.status().myState } catch(e) { print(0) }" 2>/dev/null || echo "0")

  if [ "$RS_STATE" = "2" ] || [ "$RS_STATE" = "1" ]; then
    echo "  Nodo en estado $RS_STATE dentro del RS. Correcto."
    break
  fi

  echo "  Estado del RS: $RS_STATE — esperando... ($ELAPSED/$${MAX_WAIT}s)"
  sleep $INTERVAL
  ELAPSED=$((ELAPSED + INTERVAL))
done

if [ $ELAPSED -ge $MAX_WAIT ]; then
  echo "ADVERTENCIA: El RS no se inicializó en $MAX_WAIT segundos."
  echo "  El Primary deberá añadirlo manualmente: rs.add('<secondary_ip>:27017')"
fi

echo "[6/6] Reiniciando MongoDB Secondary con autenticación..."

sleep 30

docker stop mongodb-secondary
docker rm mongodb-secondary

sleep 5

docker run \
  --detach \
  --name mongodb-secondary \
  --restart unless-stopped \
  --publish 27017:27017 \
  --volume "$MOUNT_POINT/db:/data/db" \
  --volume "$MOUNT_POINT/logs:/var/log/mongodb" \
  --volume "$MOUNT_POINT/keyfile:/etc/mongo-keyfile:ro" \
  --memory="3g" \
  --cpus="1.5" \
  --security-opt no-new-privileges:true \
  "$ECR_IMAGE" \
  mongod --replSet "$RS_NAME" --auth --keyFile /etc/mongo-keyfile --bind_ip_all --port 27017

sleep 10

if docker ps | grep -q mongodb-secondary; then
  echo "MongoDB Secondary corriendo con autenticación activada."
else
  echo "ERROR: El contenedor mongodb-secondary no arrancó con --auth."
  docker logs mongodb-secondary || true
  exit 1
fi

echo ""
echo "============================================================"
echo " MongoDB Secondary inicializado correctamente — RS: $RS_NAME"
echo "============================================================"
echo ""
echo "==== [$(date)] Setup de MongoDB Secondary completado ===="
