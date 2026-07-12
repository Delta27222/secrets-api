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
for i in $(seq 1 30); do
  if curl -sf -o /dev/null "http://localhost:9000"; then break; fi
  sleep 3
done

curl -s -G "http://localhost:9000/exec" --data-urlencode \
  "query=CREATE TABLE IF NOT EXISTS Logs (date TIMESTAMP, user STRING, action STRING, targetType STRING, idTarget STRING, details STRING, execution_time DOUBLE) TIMESTAMP(date) PARTITION BY DAY;"

curl -s -G "http://localhost:9000/exec" --data-urlencode \
  "query=CREATE TABLE IF NOT EXISTS encryption_key_audit (timestamp TIMESTAMP, action STRING, key_id STRING, project_id STRING, actor_id STRING, ip_address STRING, operation_result STRING, details STRING) TIMESTAMP(timestamp) PARTITION BY DAY;"
