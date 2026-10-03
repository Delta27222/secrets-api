#!/bin/bash
# Invocado por Terraform (null_resource.docker_ami_builder, local-exec).
# Crea una AMI de Amazon Linux 2023 con Docker preinstalado, usada por las
# EC2 en subredes de datos (sin internet). Idempotente: si la AMI ya existe
# y está disponible, no hace nada.
#
# Uso: build_docker_ami.sh <region> <ami_name> <subnet_id>

set -euo pipefail

REGION="$1"
AMI_NAME="$2"
SUBNET_ID="$3"

info()    { echo "[INFO] $*"; }
success() { echo "[OK]   $*"; }
error()   { echo "[ERROR] $*" >&2; exit 1; }

existing_ami=$(aws ec2 describe-images \
  --region "$REGION" \
  --owners self \
  --filters "Name=name,Values=${AMI_NAME}" "Name=state,Values=available" \
  --query "Images[0].ImageId" \
  --output text 2>/dev/null || echo "")

if [ -n "$existing_ami" ] && [ "$existing_ami" != "None" ]; then
  success "AMI '$AMI_NAME' ya existe y está disponible: $existing_ami"
  exit 0
fi

info "Obteniendo AMI base de Amazon Linux 2023..."
base_ami=$(aws ec2 describe-images \
  --region "$REGION" \
  --owners 137112412989 \
  --filters \
    "Name=name,Values=al2023-ami-2023.*-x86_64" \
    "Name=architecture,Values=x86_64" \
    "Name=state,Values=available" \
    "Name=root-device-type,Values=ebs" \
  --query "sort_by(Images, &CreationDate)[-1].ImageId" \
  --output text)

[ -n "$base_ami" ] && [ "$base_ami" != "None" ] || error "No se encontró AMI base de AL2023."
info "AMI base: $base_ami"

USERDATA=$(cat <<'USERDATA_EOF'
#!/bin/bash
set -euo pipefail
dnf install -y docker
systemctl enable docker
systemctl start docker
docker --version
shutdown -h now
USERDATA_EOF
)

info "Lanzando instancia t3.micro temporal en $SUBNET_ID..."
instance_id=$(aws ec2 run-instances \
  --region "$REGION" \
  --image-id "$base_ami" \
  --instance-type "t3.micro" \
  --subnet-id "$SUBNET_ID" \
  --associate-public-ip-address \
  --user-data "$USERDATA" \
  --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":20,"VolumeType":"gp3","DeleteOnTermination":true}}]' \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${AMI_NAME}-builder},{Key=Purpose,Value=ami-build}]" \
  --query "Instances[0].InstanceId" \
  --output text)

[ -n "$instance_id" ] || error "No se pudo lanzar la instancia temporal."
success "Instancia lanzada: $instance_id"

info "Esperando a que Docker se instale y la instancia se apague (~3 min)..."
max_wait=600
waited=0
interval=15

while [ "$waited" -lt "$max_wait" ]; do
  state=$(aws ec2 describe-instances \
    --region "$REGION" \
    --instance-ids "$instance_id" \
    --query "Reservations[0].Instances[0].State.Name" \
    --output text 2>/dev/null || echo "")

  if [ "$state" = "stopped" ]; then
    success "Instancia detenida — Docker instalado correctamente."
    break
  fi

  info "Estado: $state. Esperando ${interval}s... (${waited}s/${max_wait}s)"
  sleep "$interval"
  waited=$((waited + interval))
done

info "Creando AMI '$AMI_NAME'..."
ami_id=$(aws ec2 create-image \
  --region "$REGION" \
  --instance-id "$instance_id" \
  --name "$AMI_NAME" \
  --description "Amazon Linux 2023 con Docker preinstalado" \
  --no-reboot \
  --query "ImageId" \
  --output text)

[ -n "$ami_id" ] && [ "$ami_id" != "None" ] || error "No se pudo crear la AMI."
success "AMI creada: $ami_id (registrando...)"

aws ec2 create-tags --region "$REGION" --resources "$ami_id" --tags "Key=Name,Value=${AMI_NAME}" >/dev/null

info "Esperando a que la AMI esté disponible (~2 min)..."
aws ec2 wait image-available --region "$REGION" --image-ids "$ami_id"
success "AMI disponible: $ami_id"

info "Terminando instancia temporal..."
aws ec2 terminate-instances --region "$REGION" --instance-ids "$instance_id" >/dev/null
success "Instancia $instance_id terminada."
