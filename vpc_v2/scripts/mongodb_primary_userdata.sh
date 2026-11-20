#!/bin/bash
# User data — EC2 MongoDB Primary
# Variables inyectadas por Terraform templatefile():
#   mongodb_version, mongodb_admin_user, mongodb_admin_pass, replica_set_name,
#   primary_ip, secondary_ip, arbiter_ip, ecr_registry, ecr_repo_mongodb, aws_region

set -euo pipefail

LOG_FILE="/var/log/mongodb_primary_setup.log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "==== [$(date)] Iniciando setup de MongoDB Primary ===="

ECR_IMAGE="${ecr_registry}/${ecr_repo_mongodb}:${mongodb_version}"
AWS_REGION="${aws_region}"
RS_NAME="${replica_set_name}"
PRIMARY_IP="${primary_ip}"
SECONDARY_IP="${secondary_ip}"
ARBITER_IP="${arbiter_ip}"
ADMIN_USER="${mongodb_admin_user}"
ADMIN_PASS="${mongodb_admin_pass}"

echo "[1/8] Habilitando Docker (preinstalado en Amazon Linux 2023)..."
systemctl enable docker
systemctl start docker
docker --version

echo "[2/8] Descargando imagen MongoDB desde ECR..."

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

echo "[3/8] Configurando volumen EBS..."
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

# keyFile para autenticacion interna del Replica Set — MongoDB lo exige
# junto con --auth en cualquier RS (no hay forma de usar solo --auth).
# Debe ser identico en los 3 nodos y con permisos restringidos (400).
echo "${mongodb_keyfile}" > "$MOUNT_POINT/keyfile"
chown 999:999 "$MOUNT_POINT/keyfile"
chmod 400 "$MOUNT_POINT/keyfile"

echo "[4/8] Arrancando MongoDB Primary (fase init, sin auth)..."
docker run \
  --detach \
  --name mongodb-primary \
  --restart unless-stopped \
  --publish 27017:27017 \
  --volume "$MOUNT_POINT/db:/data/db" \
  --volume "$MOUNT_POINT/logs:/var/log/mongodb" \
  --memory="3g" \
  --cpus="1.5" \
  --security-opt no-new-privileges:true \
  "$ECR_IMAGE" \
  mongod --replSet "$RS_NAME" --bind_ip_all --port 27017

sleep 15

if ! docker ps | grep -q mongodb-primary; then
  echo "ERROR: El contenedor mongodb-primary no arrancó."
  docker logs mongodb-primary || true
  exit 1
fi

echo "MongoDB Primary corriendo (sin auth)."

echo "[5/8] Esperando al Secondary ($SECONDARY_IP:27017) y Arbiter ($ARBITER_IP:27017)..."

wait_for_host() {
  local host="$1"
  local port="$2"
  local attempts=20
  for i in $(seq 1 $attempts); do
    if timeout 3 bash -c "echo > /dev/tcp/$host/$port" 2>/dev/null; then
      echo "  $host:$port accesible."
      return 0
    fi
    echo "  Esperando $host:$port... intento $i/$attempts"
    sleep 10
  done
  echo "  ADVERTENCIA: $host:$port no accesible después de $attempts intentos. Continuando de todas formas."
  return 0
}

wait_for_host "$SECONDARY_IP" "27017"
wait_for_host "$ARBITER_IP" "27017"

echo "[6/8] Inicializando Replica Set $RS_NAME..."

docker exec mongodb-primary mongosh --quiet --eval "
  rs.initiate({
    _id: '$RS_NAME',
    members: [
      { _id: 0, host: '$PRIMARY_IP:27017',   priority: 2 },
      { _id: 1, host: '$SECONDARY_IP:27017', priority: 1 },
      { _id: 2, host: '$ARBITER_IP:27017',   arbiterOnly: true }
    ]
  });
"

echo "Esperando a que el Primary sea elegido (puede tardar hasta 30 segundos)..."
sleep 30

docker exec mongodb-primary mongosh --quiet --eval "
  const status = rs.status();
  printjson(status.myState);
  if (status.myState !== 1) {
    print('ADVERTENCIA: El nodo no es Primary aún. Estado: ' + status.myState);
  } else {
    print('OK: Nodo elegido como Primary.');
  }
"

echo "[7/8] Creando usuario administrador y activando autenticación..."

docker exec mongodb-primary mongosh --quiet --eval "
  db = db.getSiblingDB('admin');
  db.createUser({
    user: '$ADMIN_USER',
    pwd: '$ADMIN_PASS',
    roles: [{ role: 'root', db: 'admin' }]
  });
  print('Usuario $ADMIN_USER creado correctamente.');
"

docker stop mongodb-primary
docker rm mongodb-primary

sleep 5

docker run \
  --detach \
  --name mongodb-primary \
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

docker exec mongodb-primary mongosh \
  --quiet \
  -u "$ADMIN_USER" \
  -p "$ADMIN_PASS" \
  --authenticationDatabase admin \
  --eval "print('RS Status: ' + rs.status().myState); print('Primary listo con auth.');"

echo ""
echo "============================================================"
echo " MongoDB Primary inicializado correctamente"
echo "  IP: $PRIMARY_IP"
echo "  RS: $RS_NAME"
echo "============================================================"
echo ""
echo "==== [$(date)] Setup de MongoDB Primary completado ===="
