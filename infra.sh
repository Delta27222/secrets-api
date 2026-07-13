#!/usr/bin/env bash
# ============================================================================
# infra.sh — Orquestador de la infraestructura AWS de Tek Secrets.
#
# Crea o elimina TODO lo referente a los dos módulos independientes:
#   - logs/       QuestDB (EC2 + EBS + EIP + SG) + SQS + Lambda consumidora
#   - rotation/   Rotación de llaves (EventBridge + 2 Lambdas + SQS + IAM)
#
# Uso:
#   ./infra.sh create [logs|rotation|all]   # build + terraform apply
#   ./infra.sh delete [logs|rotation|all]   # terraform destroy (pide confirmación)
#
# Si no se indica módulo, aplica a 'all'. Añade -y para no pedir confirmación
# (aplica tanto a create como a delete; ej: ./infra.sh create all -y).
#
# ⚠️ Cada módulo necesita su terraform/terraform.tfvars (copiar del .example).
# ============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGS_DIR="$ROOT/logs"
ROTATION_DIR="$ROOT/rotation"

# ---- colores ----
b(){ printf "\033[1m%s\033[0m\n" "$1"; }
ok(){ printf "\033[32m✓ %s\033[0m\n" "$1"; }
warn(){ printf "\033[33m⚠ %s\033[0m\n" "$1"; }
err(){ printf "\033[31m✗ %s\033[0m\n" "$1" >&2; }
sep(){ printf "\033[36m──────────────────────────────────────────────\033[0m\n"; }

usage(){
  cat <<EOF
Uso: ./infra.sh <create|delete> [logs|rotation|all] [-y]

  create   empaqueta los Lambdas y hace 'terraform apply'
  delete   hace 'terraform destroy' (⚠️ destruye recursos y datos)

  módulo   logs | rotation | all   (default: all)
  -y       no pedir confirmación (aplica a create y delete)

Ejemplos:
  ./infra.sh create              # crea logs + rotation (pide confirmación)
  ./infra.sh create logs         # solo logs
  ./infra.sh create all -y       # crea todo sin preguntar
  ./infra.sh delete all -y       # destruye todo sin preguntar
EOF
}

# ---- verifica que exista terraform.tfvars ----
check_tfvars(){
  local dir="$1" name="$2"
  if [ ! -f "$dir/terraform/terraform.tfvars" ]; then
    err "Falta $dir/terraform/terraform.tfvars"
    warn "Créalo:  cp $dir/terraform/terraform.tfvars.example $dir/terraform/terraform.tfvars  (y edítalo)"
    exit 1
  fi
}

# ================= BUILD =================
build_logs(){
  b "[logs] Empaquetando Lambda consumidora..."
  ( cd "$LOGS_DIR" && ./scripts/build_consumer.sh )
  ok "[logs] zip listo"
}

require_docker(){
  if ! docker info >/dev/null 2>&1; then
    err "Docker no está corriendo (el Lambda Maestro se compila dentro de Docker)."
    warn "Abre Docker Desktop, espera a que arranque y reintenta:  ./infra.sh create rotation"
    exit 1
  fi
}

build_rotation(){
  require_docker
  b "[rotation] Empaquetando Lambdas (Maestro necesita Docker)..."
  ( cd "$ROTATION_DIR" && ./scripts/build_master.sh && ./scripts/build_worker.sh )
  ok "[rotation] zips listos"
}

# ================= APPLY =================
apply_module(){
  local dir="$1" name="$2"
  b "[$name] terraform init + apply..."
  ( cd "$dir/terraform" && terraform init -input=false && terraform apply -auto-approve )
  ok "[$name] desplegado"
}

# ================= DESTROY =================
destroy_module(){
  local dir="$1" name="$2"
  if [ ! -d "$dir/terraform/.terraform" ]; then
    warn "[$name] sin estado de terraform (¿ya destruido o nunca creado?). Saltando."
    return 0
  fi
  b "[$name] terraform destroy..."
  ( cd "$dir/terraform" && terraform destroy -auto-approve )
  ok "[$name] eliminado"
}

# ================= FLUJOS =================
do_create(){
  local target="$1" assume_yes="$2"
  if [ "$assume_yes" != "yes" ]; then
    sep
    warn "Vas a CREAR la infraestructura de: $target"
    warn "Esto crea recursos en AWS que generan costos (EC2, EBS, Lambdas, SQS...)."
    read -r -p "Escribe 'create' para confirmar: " ans
    [ "$ans" = "create" ] || { err "Cancelado."; exit 1; }
  fi
  # Chequeos previos: no empezar si algo obligatorio falta (evita despliegues a medias).
  case "$target" in
    rotation|all)
      sep
      warn "PRERREQUISITO: Docker debe estar ENCENDIDO."
      warn "El Lambda Maestro de rotación se compila dentro de Docker; sin él no se puede crear."
      require_docker
      ok "Docker está corriendo. Continuando."
      ;;
  esac
  case "$target" in
    logs)     check_tfvars "$LOGS_DIR" logs;         build_logs;     apply_module "$LOGS_DIR" logs ;;
    rotation) check_tfvars "$ROTATION_DIR" rotation;  build_rotation; apply_module "$ROTATION_DIR" rotation ;;
    all)
      check_tfvars "$LOGS_DIR" logs
      check_tfvars "$ROTATION_DIR" rotation
      build_logs;     apply_module "$LOGS_DIR" logs
      build_rotation; apply_module "$ROTATION_DIR" rotation
      ;;
    *) err "módulo inválido: $target"; usage; exit 1 ;;
  esac
  summary_created "$target"
  final_note
}

do_delete(){
  local target="$1" assume_yes="$2"
  if [ "$assume_yes" != "yes" ]; then
    sep
    warn "Vas a DESTRUIR la infraestructura de: $target"
    warn "Esto elimina recursos de AWS. En 'logs' se borra el volumen EBS → SE PIERDEN LOS LOGS."
    read -r -p "Escribe 'destroy' para confirmar: " ans
    [ "$ans" = "destroy" ] || { err "Cancelado."; exit 1; }
  fi
  # Capturar los conteos ANTES de destruir (tras el destroy el estado queda vacío).
  local lc=0 rc=0
  lc=$(count_res "$LOGS_DIR")
  rc=$(count_res "$ROTATION_DIR")
  case "$target" in
    logs)     destroy_module "$LOGS_DIR" logs ;;
    rotation) destroy_module "$ROTATION_DIR" rotation ;;
    all)
      destroy_module "$ROTATION_DIR" rotation
      destroy_module "$LOGS_DIR" logs
      ;;
    *) err "módulo inválido: $target"; usage; exit 1 ;;
  esac
  summary_deleted "$target" "$lc" "$rc"
  final_note
}

# ================= RESÚMENES =================
# Lee un output de terraform sin romper si no existe.
tf_out(){ terraform -chdir="$1/terraform" output -raw "$2" 2>/dev/null || true; }

# Cuenta recursos reales en el estado (excluye data sources). 0 si no hay estado.
# El `|| true` evita que grep (código 1 si no hay coincidencias) aborte el script
# bajo `set -euo pipefail` cuando un módulo tiene 0 recursos o no está inicializado.
count_res(){
  local n
  n=$(terraform -chdir="$1/terraform" state list 2>/dev/null | grep -vc '^data\.' || true)
  echo "${n:-0}"
}

# Imprime la línea de totales según el módulo objetivo.
print_totals(){
  local target="$1" lc="$2" rc="$3"
  case "$target" in
    logs)     b "TOTAL:  logs = $lc recursos" ;;
    rotation) b "TOTAL:  rotation = $rc recursos" ;;
    all)      b "TOTAL:  logs = $lc  ·  rotation = $rc  ·  total = $((lc + rc)) recursos" ;;
  esac
}

summary_logs_created(){
  b "── LOGS ──"
  echo "  QuestDB (EC2)      : $(tf_out "$LOGS_DIR" questdb_instance_id)  →  $(tf_out "$LOGS_DIR" questdb_web_console)"
  echo "  IP pública (EIP)   : $(tf_out "$LOGS_DIR" questdb_public_ip)"
  echo "  SQS cola de logs   : $(tf_out "$LOGS_DIR" logs_sqs_queue_url)"
  echo "  SQS DLQ            : $(tf_out "$LOGS_DIR" logs_sqs_dlq_url)"
  echo "  Lambda consumidora : $(tf_out "$LOGS_DIR" consumer_lambda_name)"
  echo "  + Volumen EBS (datos) · Security Group"
}

summary_rotation_created(){
  b "── ROTATION ──"
  echo "  Lambda Maestro     : $(tf_out "$ROTATION_DIR" lambda_master_name)"
  echo "  Lambda Worker      : $(tf_out "$ROTATION_DIR" lambda_worker_name)"
  echo "  SQS cola rotación  : $(tf_out "$ROTATION_DIR" sqs_queue_url)"
  echo "  SQS DLQ            : $(tf_out "$ROTATION_DIR" sqs_dlq_url)"
  echo "  Regla EventBridge  : $(tf_out "$ROTATION_DIR" eventbridge_rule_name)"
  echo "  Costo estimado     : $(tf_out "$ROTATION_DIR" estimated_monthly_cost)"
  echo "  + Roles IAM · Grupos de CloudWatch Logs"
}

summary_created(){
  local target="$1" lc=0 rc=0
  sep; b "RESUMEN — recursos CREADOS"
  if [ "$target" = "logs" ] || [ "$target" = "all" ]; then
    summary_logs_created; lc=$(count_res "$LOGS_DIR")
    echo "  → $lc recursos en el módulo logs"
  fi
  if [ "$target" = "rotation" ] || [ "$target" = "all" ]; then
    summary_rotation_created; rc=$(count_res "$ROTATION_DIR")
    echo "  → $rc recursos en el módulo rotation"
  fi
  sep; print_totals "$target" "$lc" "$rc"
}

# Recibe los conteos capturados ANTES de destruir (tras el destroy el estado queda vacío).
summary_deleted(){
  local target="$1" lc="$2" rc="$3"
  sep; b "RESUMEN — recursos ELIMINADOS"
  if [ "$target" = "logs" ] || [ "$target" = "all" ]; then
    b "── LOGS ──"
    echo "  EC2 QuestDB · Volumen EBS (datos) · Elastic IP · Security Group"
    echo "  SQS (cola de logs + DLQ) · Lambda consumidora · Roles/políticas IAM"
    echo "  → $lc recursos eliminados del módulo logs"
  fi
  if [ "$target" = "rotation" ] || [ "$target" = "all" ]; then
    b "── ROTATION ──"
    echo "  Lambda Maestro · Lambda Worker · SQS (cola + DLQ)"
    echo "  Regla EventBridge · Roles IAM · Grupos de CloudWatch Logs · Alarmas CloudWatch"
    echo "  → $rc recursos eliminados del módulo rotation"
  fi
  sep; print_totals "$target" "$lc" "$rc"
}

# ================= NOTA FINAL =================
final_note(){
  sep
  b "RECUERDA: hay que hacer el build/deploy de la API en Render"
  cat <<EOF
La infraestructura cambió (IPs/colas/Lambdas). Para que la API tome los cambios:

  1. Ve a Render → servicio de la API.
  2. Manual Deploy → "Clear build cache & deploy" (o Restart si solo cambió infra).
  3. Verifica en los logs de arranque que autodescubra la QuestDB:
       "QuestDB autodescubierta en AWS: <ip> (tag Name=tek-secrets-questdb)"

Sin este redeploy, la API puede seguir apuntando a recursos viejos.
EOF
}

# ================= MAIN =================
[ $# -ge 1 ] || { usage; exit 1; }

ACTION="$1"; shift
TARGET="all"
ASSUME_YES="no"
for arg in "$@"; do
  case "$arg" in
    logs|rotation|all) TARGET="$arg" ;;
    -y|--yes) ASSUME_YES="yes" ;;
    *) err "argumento desconocido: $arg"; usage; exit 1 ;;
  esac
done

case "$ACTION" in
  create) do_create "$TARGET" "$ASSUME_YES" ;;
  delete) do_delete "$TARGET" "$ASSUME_YES" ;;
  -h|--help|help) usage ;;
  *) err "acción inválida: $ACTION"; usage; exit 1 ;;
esac
