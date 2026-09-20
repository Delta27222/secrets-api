#!/bin/bash
# User data — EC2 MongoDB Arbiter
# Variables inyectadas por Terraform templatefile():
#   mongodb_version, replica_set_name, ecr_registry, ecr_repo_mongodb, aws_region
#
# El Arbiter vota en las elecciones del RS pero no almacena datos: sin
# volumen EBS adicional, arranca con arbiterOnly:true via rs.initiate().

set -euo pipefail

LOG_FILE="/var/log/mongodb_arbiter_setup.log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "==== [$(date)] Iniciando setup de MongoDB Arbiter ===="

ECR_IMAGE="${ecr_registry}/${ecr_repo_mongodb}:${mongodb_version}"
AWS_REGION="${aws_region}"
RS_NAME="${replica_set_name}"

echo "[1/5] Habilitando Docker (preinstalado en Amazon Linux 2023)..."
systemctl enable docker
systemctl start docker
docker --version

echo "[2/5] Descargando imagen MongoDB desde ECR..."

# El VPC Endpoint de ECR puede tardar unos segundos en quedar listo justo
# cuando la instancia arranca — reintenta en vez de abortar todo el setup
# por un timeout de red transitorio.
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

echo "[3/5] Arrancando MongoDB Arbiter (fase init, sin auth)..."

mkdir -p /data/mongodb/db /data/mongodb/logs
chown -R 999:999 /data/mongodb

# keyFile para autenticacion interna del RS — debe ser identico en los 3 nodos.
echo "${mongodb_keyfile}" > /data/mongodb/keyfile
chown 999:999 /data/mongodb/keyfile
chmod 400 /data/mongodb/keyfile

docker run \
  --detach \
  --name mongodb-arbiter \
  --restart unless-stopped \
  --publish 27017:27017 \
  --volume /data/mongodb/db:/data/db \
  --volume /data/mongodb/logs:/var/log/mongodb \
  --memory="512m" \
  --cpus="0.5" \
  --security-opt no-new-privileges:true \
  "$ECR_IMAGE" \
  mongod --replSet "$RS_NAME" --bind_ip_all --port 27017

sleep 10

if ! docker ps | grep -q mongodb-arbiter; then
  echo "ERROR: El contenedor mongodb-arbiter no arrancó."
  docker logs mongodb-arbiter || true
  exit 1
fi

echo "MongoDB Arbiter corriendo (sin auth). Esperando rs.initiate() del Primary..."

echo "[4/5] Esperando a que el Primary añada este nodo como Arbiter..."

MAX_WAIT=600
INTERVAL=15
ELAPSED=0

while [ $ELAPSED -lt $MAX_WAIT ]; do
  RS_STATE=$(docker exec mongodb-arbiter mongosh --quiet --eval \
    "try { rs.status().myState } catch(e) { print(0) }" 2>/dev/null || echo "0")

  if [ "$RS_STATE" = "7" ]; then
    echo "  Nodo reconocido como ARBITER (myState=7). Correcto."
    break
  fi

  echo "  Estado del RS: $RS_STATE — esperando... ($ELAPSED/$${MAX_WAIT}s)"
  sleep $INTERVAL
  ELAPSED=$((ELAPSED + INTERVAL))
done

if [ $ELAPSED -ge $MAX_WAIT ]; then
  echo "ADVERTENCIA: El Arbiter no fue añadido al RS en $MAX_WAIT segundos."
  echo "  El Primary deberá añadirlo manualmente: rs.addArb('<arbiter_ip>:27017')"
fi

echo "[5/5] Reiniciando MongoDB Arbiter con autenticación..."

sleep 30

docker stop mongodb-arbiter
docker rm mongodb-arbiter

sleep 5

docker run \
  --detach \
  --name mongodb-arbiter \
  --restart unless-stopped \
  --publish 27017:27017 \
  --volume /data/mongodb/db:/data/db \
  --volume /data/mongodb/logs:/var/log/mongodb \
  --volume /data/mongodb/keyfile:/etc/mongo-keyfile:ro \
  --memory="512m" \
  --cpus="0.5" \
  --security-opt no-new-privileges:true \
  "$ECR_IMAGE" \
  mongod --replSet "$RS_NAME" --auth --keyFile /etc/mongo-keyfile --bind_ip_all --port 27017

sleep 10

if docker ps | grep -q mongodb-arbiter; then
  echo "MongoDB Arbiter corriendo con autenticación activada."
else
  echo "ERROR: El contenedor mongodb-arbiter no arrancó con --auth."
  docker logs mongodb-arbiter || true
  exit 1
fi

echo ""
echo "============================================================"
echo " MongoDB Arbiter inicializado correctamente — RS: $RS_NAME"
echo "============================================================"
echo ""
echo "==== [$(date)] Setup de MongoDB Arbiter completado ===="
