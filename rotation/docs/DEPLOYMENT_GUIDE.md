# Guía Completa: Rotación + Reencriptación de Llaves con Lambda + EventBridge

**Última actualización**: 2026-07-12  
**Versión**: 1.0  
**Autor**: Tek Secrets Team

---

## 📋 Tabla de Contenidos

1. [Resumen Ejecutivo](#resumen-ejecutivo)
2. [Arquitectura](#arquitectura)
3. [Prerequisitos](#prerequisitos)
4. [Paso 1: Setup Inicial](#paso-1-setup-inicial)
5. [Paso 2: Preparar Código Lambda](#paso-2-preparar-código-lambda)
6. [Paso 3: Crear Infraestructura con Terraform](#paso-3-crear-infraestructura-con-terraform)
7. [Paso 4: Testing](#paso-4-testing)
8. [Paso 5: Monitoreo](#paso-5-monitoreo)
9. [Troubleshooting](#troubleshooting)
10. [Costos](#costos)
11. [Rollback](#rollback)
12. [Eliminar o Pausar Infraestructura](#eliminar-o-pausar-infraestructura) ← **PARA NO COBRAR**

---

## Resumen Ejecutivo

> ⚠️ **ARQUITECTURA ACTUAL (importante)**
> El Lambda Worker **NO** encripta. Solo hace un **HTTP POST a la API** en Render,
> que ejecuta la rotación + re-encriptación con su **CSFLE nativo**. La autenticación
> Lambda→API usa un **service token de sistema** (`tok_...`, scope `keys:rotate`)
> creado desde la UI (**Organización → tab Tokens**).
> Motivo: CSFLE (`pymongocrypt`) no corre bien en Lambda; la API en Render (Linux +
> Python 3.12) sí. Ver [SOLUTION_SUMMARY.md](./SOLUTION_SUMMARY.md).

### Qué hace

- **Rotación automática de llaves de encriptación**: Genera nueva llave por proyecto
- **Reencriptación de secretos**: La API desencripta con la llave vieja y re-encripta con la nueva
- **Ejecución programada**: Cron diario a las 00:00 UTC (configurable)
- **Escalable**: Procesa múltiples proyectos en paralelo sin timeout

### Flujo simplificado

```
EventBridge (00:00 UTC)
    ↓
Lambda Maestro
  ├─ Obtiene todos los proyectos (MongoDB)
  └─ Envía a SQS Queue
    ↓
SQS Queue (100+ mensajes)
    ↓
Lambda Worker (consume paralelo)
  └─ POST {API}/v1/internal/projects/{id}/rotate-encryption
       Authorization: Bearer tok_...
    ↓
API en Render (CSFLE nativo)
  ├─ Genera llave nueva (metadata completa)
  ├─ Rota a active (vieja → deprecated)
  ├─ Re-encripta todos los secretos
  ├─ Actualiza secrets_encryption
  └─ Audita en QuestDB
    ↓
CloudWatch (logs Lambda)
```

### Resultado

| Métrica | Valor |
|---------|-------|
| **Automatización** | ✅ 100% sin intervención |
| **Cobertura** | ✅ Todos los proyectos |
| **Tiempo** | 2-5 segundos por proyecto |
| **Reintentos** | ✅ Automático (3 intentos) |
| **Logging** | ✅ CloudWatch + QuestDB |
| **Costo** | ~$0.50-1.50 USD/mes |

---

## Arquitectura

### Diagrama general (visual)

```mermaid
flowchart TD
    EB([⏰ EventBridge<br/>cron 0 0 * * ?]) --> M[λ Maestro<br/>256MB · 60s]
    M -->|find projects| DB[(🍃 MongoDB<br/>Atlas)]
    M -->|send_message x N| SQS[[📨 SQS Queue]]
    SQS --> W[λ Worker<br/>solo HTTP · stdlib]
    SQS -.->|falla 3+ veces| DLQ[[💀 SQS DLQ]]
    W -->|POST · Bearer tok_| API[☁️ API en Render<br/>FastAPI + CSFLE]
    API -->|genera/rota/re-encripta| DB
    API -->|auditoría| Q[(📊 QuestDB)]
    M -.logs.-> CW[[📈 CloudWatch]]
    W -.logs.-> CW

    classDef aws fill:#ff9900,stroke:#333,color:#000;
    classDef ext fill:#4b8bbe,stroke:#333,color:#fff;
    class EB,M,SQS,DLQ,W,CW aws;
    class API,DB,Q ext;
```

> Naranja = recursos AWS · Azul = servicios externos (API Render, MongoDB, QuestDB)

### Componentes AWS

```
┌─────────────────────────────────────────────────────────────┐
│                     AWS Cloud                               │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  EventBridge Rule                                           │
│  └─ Schedule: cron(0 0 * * ? *)  [00:00 UTC diariamente]   │
│     └─ Trigger: Lambda Maestro                             │
│                                                             │
│  Lambda Maestro (256MB, 60s timeout)                        │
│  ├─ Conecta MongoDB                                         │
│  ├─ SELECT * FROM projects                                 │
│  └─ send_message para cada proyecto → SQS                  │
│                                                             │
│  SQS Queue (Main)                                           │
│  ├─ Visibility timeout: 900s (15min)                       │
│  ├─ Messages: ~50-500 (1 por proyecto)                     │
│  └─ Retry policy: max 3 intentos                           │
│                                                             │
│  SQS Queue (DLQ - Dead Letter)                             │
│  └─ Mensajes que fallaron >3 veces                         │
│                                                             │
│  Lambda Worker (512MB, 900s timeout)                        │
│  ├─ Consume 1 mensaje SQS                                  │
│  ├─ Ejecuta en paralelo (múltiples instancias)            │
│  ├─ Rota + Re-encripta proyecto                            │
│  └─ Delete message al terminar                             │
│                                                             │
│  CloudWatch Logs                                            │
│  ├─ /aws/lambda/rotation_master (detallado)               │
│  ├─ /aws/lambda/rotation_worker (detallado)               │
│  └─ Retention: 14 días                                     │
│                                                             │
│  CloudWatch Alarms (notificaciones)                         │
│  ├─ Lambda Maestro errors                                  │
│  ├─ Lambda Worker errors                                   │
│  └─ SQS DLQ no vacía (error manual)                        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
                           ↓
         ┌─────────────────────────────────┐
         │    MongoDB (tu infraestructura)  │
         ├─────────────────────────────────┤
         │ collections:                    │
         │  ├─ encryption_keys             │
         │  ├─ environments (secrets)       │
         │  └─ projects                    │
         └─────────────────────────────────┘
```

### Flujo de datos

```mermaid
sequenceDiagram
    autonumber
    participant EB as ⏰ EventBridge
    participant M as λ Maestro
    participant DB as 🍃 MongoDB
    participant SQS as 📨 SQS
    participant W as λ Worker
    participant API as ☁️ API (Render)
    participant Q as 📊 QuestDB

    EB->>M: trigger (00:00 UTC)
    M->>DB: db.projects.find({})
    DB-->>M: [50 proyectos]
    loop cada proyecto
        M->>SQS: send_message(project_id)
    end

    SQS->>W: entrega mensaje
    W->>API: POST rotate-encryption<br/>Bearer tok_...
    API->>DB: 1) genera llave (pending)
    API->>DB: 2) rota (active, vieja→deprecated)
    loop cada environment
        API->>DB: 3) desencripta (vieja) + re-encripta (nueva)
        API->>DB: 4) update secrets_encryption
    end
    API->>Q: 5) auditoría (KEY_ROTATED)
    API-->>W: 200 { status: success }
    W-->>SQS: ✅ borra mensaje
```

**Primera ejecución** (00:00 UTC):
```
1. EventBridge dispara Lambda Maestro
   Input: { source: "eventbridge", triggered: true }
   
2. Lambda Maestro:
   - Conecta MongoDB
   - Query: db.projects.find({}) → 50 proyectos
   - Para cada proyecto:
     {
       project_id: "507f1f77bcf86cd799439011",
       action: "rotate_and_reencrypt",
       timestamp: "2026-07-11T00:00:00Z"
     } → SQS
   - Retorna: { status: "success", projects_queued: 50 }
   
3. SQS recibe 50 mensajes
   
4. Lambda Worker (múltiples instancias en paralelo):
   - Instancia 1: procesa proyecto_1 (2-5s)
   - Instancia 2: procesa proyecto_2 (2-5s)
   - Instancia 3: procesa proyecto_3 (2-5s)
   - ...
   
5. Total: ~5-10 segundos (paralelo vs 250s secuencial)
   
6. CloudWatch + Logs
```

---

## Prerequisitos

### Local (tu máquina)

- [ ] AWS Account con acceso admin (o IAM user con permisos)
- [ ] AWS CLI v2 instalado: `aws --version`
- [ ] Terraform >= 1.0: `terraform version`
- [ ] Git: `git --version`
- [ ] Python 3.12+: `python3 --version`
- [ ] bash/zsh (incluido en Mac/Linux)

### API + Service Token (nuevo — obligatorio)

- [ ] **API desplegada en Render** con CSFLE funcionando
  - Python 3.12 pinneado (`api/.python-version` + env `PYTHON_VERSION=3.12.13`)
  - `requirements.txt` con `pymongo[encryption]`
  - Env vars: `MONGODB_URL`, `MONGO_DB`, `MONGODB_CSFLE_MASTER_KEY`
    (el MISMO valor que encriptó las llaves existentes), GitHub OAuth
  - MongoDB Atlas: whitelist `0.0.0.0/0`
- [ ] **Service token de sistema creado** (scope `keys:rotate`)
  - UI: **Organización → tab Tokens → Crear Token**
  - Guarda el `tok_...` (se muestra una sola vez)
- [ ] **Validador de `service_tokens` relajado** para `project_id` null
  - Correr `relax_service_token_validator.py` (una vez)

### AWS Permissions

Necesitas que tu IAM user tenga estos permisos:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "lambda:*",
        "sqs:*",
        "events:*",
        "iam:*",
        "logs:*",
        "cloudwatch:*"
      ],
      "Resource": "*"
    }
  ]
}
```

**O usa estas policies predefinidas:**
- AWSLambdaFullAccess
- AmazonSQSFullAccess
- CloudWatchEventsFullAccess
- IAMFullAccess
- CloudWatchLogsFullAccess

### Información necesaria

Recopila esto antes de empezar:

```bash
# MongoDB (para el Lambda Maestro que lista proyectos)
MONGODB_URL="mongodb+srv://user:pass@cluster.mongodb.net/?retryWrites=true&w=majority"
MONGO_DB="secrets-27222"

# API + Service Token (para el Lambda Worker)
API_BASE_URL="https://tu-app.onrender.com"
ROTATION_API_TOKEN="tok_..."   # scope keys:rotate (creado en la UI)

# AWS
AWS_REGION="us-east-1"
AWS_ACCOUNT_ID="123456789012"  # obtener con: aws sts get-caller-identity
```

> El Worker ya **no** necesita `MONGODB_CSFLE_MASTER_KEY` ni QuestDB — eso lo maneja
> la API. El Maestro solo necesita `MONGODB_URL` para listar proyectos.

---

## Paso 1: Setup Inicial

### 1.1 Clonar/Descargar código

```bash
# Si aún no tienes la carpeta deployment
cd /Users/delta27222/Desktop/tesis
ls -la deployment/

# Deberías ver:
# deployment/
# ├── lambda/
# │   ├── rotation_master.py
# │   └── rotation_worker.py
# ├── terraform/
# │   ├── main.tf
# │   ├── variables.tf
# │   ├── outputs.tf
# │   └── terraform.tfvars.example
# ├── scripts/
# │   └── scripts/build_master.sh
# └── docs/
#     └── DEPLOYMENT_GUIDE.md (este archivo)
```

### 1.2 Configurar AWS CLI

```bash
# Verificar configuración existente
aws sts get-caller-identity
# Resultado: { Account, UserId, Arn }

# Si necesitas config nueva:
aws configure
# Te pedirá: Access Key, Secret Key, Region (us-east-1), Output (json)
```

### 1.3 Crear terraform.tfvars

```bash
cd /Users/delta27222/Desktop/tesis/tek-secrets/rotation/terraform

# Copiar template
cp terraform.tfvars.example terraform.tfvars

# Editar con tus valores
nano terraform.tfvars
# O con tu editor favorito: vim, code, etc.
```

**Valores a completar** (`terraform.tfvars`):

```hcl
# Obligatorio: MongoDB (para el Lambda Maestro)
mongodb_url = "mongodb+srv://USER:PASSWORD@cluster.mongodb.net/?retryWrites=true&w=majority"
mongo_db    = "secrets-27222"

# Obligatorio: API + service token (para el Lambda Worker)
api_base_url       = "https://tu-app.onrender.com"   # URL de Render, sin slash final
rotation_api_token = "tok_..."                        # token de sistema (scope keys:rotate)

# Resto con defaults está bien
aws_region  = "us-east-1"
project_name = "tek-secrets"
environment  = "prod"
```

> Ya **no** se usa `mongodb_csfle_master_key` en Terraform — la API maneja CSFLE.
> El `rotation_api_token` lo creas en la UI (**Organización → tab Tokens**).

**⚠️ Importante**: `mongodb_url` con contraseña. Manejo:

```bash
# Opción 1: Sensitive string en tfvars
mongodb_url = "mongodb+srv://user:pass@..."  # git ignore esto

# Opción 2: Variable de entorno (más seguro)
export TF_VAR_mongodb_url="mongodb+srv://..."
# Terraform lo lee automático

# Opción 3: AWS Secrets Manager (producción)
# Crear secreto en AWS, terraform lo obtiene
```

**Agregar a .gitignore**:

```bash
# deployment/terraform/.gitignore
terraform.tfvars
*.tfvars
.terraform/
*.tfstate*
terraform_override.tf
```

---

## Paso 2: Preparar Código Lambda

### 2.1 Build Lambda Packages

Hay dos Lambdas con builds distintos:

#### Maestro (necesita `motor`/`pymongo` → Docker)

**⚠️ CRÍTICO**: el Maestro lleva `motor`/`pymongo` (binarios). Lambda corre Linux;
si compilas en macOS obtendrás `invalid ELF header`. Por eso se usa **Docker**.

```bash
cd /Users/delta27222/Desktop/tesis/tek-secrets/rotation
docker ps                     # verifica que Docker corre
./scripts/build_master.sh            # crea terraform/lambda_master.zip (binarios Linux)
```

#### Worker (solo stdlib → zip directo)

El Worker **no tiene dependencias** (solo `urllib`/`json`). No necesita Docker:

```bash
cd /Users/delta27222/Desktop/tesis/tek-secrets/rotation
./scripts/build_worker.sh     # crea terraform/lambda_worker.zip (~4.6 KB)
```

**Output esperado**:
```
✅ lambda_worker.zip creado (solo stdlib, sin dependencias)
     4670  ...  rotation_worker.py
```

> Ya no se usa `cryptography` ni `pyaes` en el Worker: la encriptación la hace la API.

### 2.2 Verificar ZIPs

```bash
cd /Users/delta27222/Desktop/tesis/tek-secrets/rotation/terraform

# Listar ZIPs
ls -lh lambda_*.zip

# Verificar contenido (debe incluir rotation_master.py + librerías)
unzip -l lambda_master.zip | head -20
```

---

## Paso 3: Crear Infraestructura con Terraform

### 3.1 Inicializar Terraform

```bash
cd /Users/delta27222/Desktop/tesis/tek-secrets/rotation/terraform

# Descargar plugins AWS
terraform init

# Output:
# - Downloading AWS provider v5.x
# - Initialized Terraform working directory
# - .terraform/ creado
```

### 3.2 Validar configuración

```bash
# Verificar sintaxis
terraform validate

# Debe retornar: Success! Configuration is valid.
```

### 3.3 Plan (visualizar cambios)

```bash
# Ver qué va a crear/modificar
terraform plan -out=tfplan

# Output mostrará:
# + aws_sqs_queue.rotation_queue
# + aws_lambda_function.rotation_master
# + aws_lambda_function.rotation_worker
# + aws_cloudwatch_event_rule.rotation_schedule
# + ... (más recursos)
#
# Plan: XX to add, 0 to change, 0 to destroy
```

**⚠️ Revisar plan antes de aplicar!**

### 3.4 Aplicar (crear infraestructura real)

```bash
# Crear recursos en AWS (irreversible, pero puedes destruir)
terraform apply tfplan

# O aplicar sin plan:
# terraform apply

# AWS Console muestra progreso:
# - Creando SQS queue
# - Creando Lambda functions
# - Creando EventBridge rule
# - Creando IAM roles
# - ...
#
# Esperar 2-5 minutos

# Output final:
# Apply complete! Resources: XX added, 0 changed, 0 destroyed.
# 
# Outputs:
# lambda_master_name = "tek-secrets-rotation-master"
# sqs_queue_url = "https://sqs.us-east-1.amazonaws.com/..."
# ...
```

### 3.5 Guardar outputs

```bash
# Mostrar outputs
terraform output

# Guardar en archivo (útil para documentación)
terraform output -json > deployment_outputs.json

# Mostrar específico
terraform output sqs_queue_url
terraform output eventbridge_rule_name
```

---

## Paso 4: Testing

### 4.1 Test Manual: Disparar Lambda Maestro

**¿Qué hace?**

Lambda Maestro (cuando se invoca):
1. Conecta a MongoDB
2. Obtiene TODOS los proyectos
3. Para cada proyecto: envía mensaje a SQS Queue
4. Retorna: resultado

**Ejecutar**:

```bash
# 1. Ir a carpeta deployment
cd /Users/delta27222/Desktop/tesis/tek-secrets/rotation

# 2. Obtener nombre Lambda Maestro
LAMBDA_NAME=$(cd terraform && terraform output -raw lambda_master_name)

# 3. Encodear payload a base64
PAYLOAD=$(echo '{"source":"manual-test","triggered":true}' | base64)

# 4. Invocar Lambda
aws lambda invoke \
  --function-name "$LAMBDA_NAME" \
  --region us-east-1 \
  --payload "$PAYLOAD" \
  response.json

# 5. Ver respuesta (formateada)
cat response.json | jq .
```

**Respuesta esperada**:

```json
{
  "statusCode": 200,
  "body": "{\"status\": \"success\", \"projects_total\": 50, \"projects_queued\": 50, \"projects_failed\": 0, \"timestamp\": \"2026-07-12T00:05:30Z\"}"
}
```

**Qué significa**:
- ✅ `statusCode: 200` = Ejecución exitosa
- ✅ `status: success` = Sin errores
- ✅ `projects_total: 50` = Encontró 50 proyectos en MongoDB
- ✅ `projects_queued: 50` = Envió 50 mensajes a SQS
- ✅ `projects_failed: 0` = Ninguno falló

---

**¿Qué se crea en AWS?**

Lambda Maestro **NO crea recursos**, solo **envía mensajes a SQS**:

```
Antes de invocar:
  SQS Queue: vacía

Después de invocar Lambda Maestro:
  SQS Queue: 50 mensajes
  ├─ Mensaje 1: { project_id: "507f1f77bcf86cd799439011", action: "rotate_and_reencrypt" }
  ├─ Mensaje 2: { project_id: "507f191e810c19729de860ea", action: "rotate_and_reencrypt" }
  ├─ Mensaje 3: { project_id: "507f1f77bcf86cd799439012", action: "rotate_and_reencrypt" }
  └─ ... (50 total)
```

---

**Qué sucede después**:

1. **Inmediato**: Los 50 mensajes están en SQS Queue
2. **Segundos después**: Lambda Worker consume los mensajes
   - Instancia 1 procesa proyecto_1 (2-5s)
   - Instancia 2 procesa proyecto_2 (2-5s) en paralelo
   - Instancia 3 procesa proyecto_3 (2-5s) en paralelo
   - ... (50 Lambdas pueden ejecutarse en paralelo)
3. **Total**: ~5-10 segundos (todo en paralelo)

---

**Verificar que funcionó**:

```bash
# Ver mensajes en SQS (debe haber mensajes)
QUEUE_URL=$(cd terraform && terraform output -raw sqs_queue_url)
aws sqs get-queue-attributes \
  --queue-url "$QUEUE_URL" \
  --attribute-names ApproximateNumberOfMessages \
  --region us-east-1

# Output esperado:
# {
#   "Attributes": {
#     "ApproximateNumberOfMessages": "50"
#   }
# }

# Esperar 10 segundos y verificar de nuevo
sleep 10
aws sqs get-queue-attributes \
  --queue-url "$QUEUE_URL" \
  --attribute-names ApproximateNumberOfMessages \
  --region us-east-1

# Output esperado después:
# {
#   "Attributes": {
#     "ApproximateNumberOfMessages": "0"  ← Todos consumidos
#   }
# }
```

---

**Alternativa (CLI v2+, sin base64 manual)**:

```bash
cd /Users/delta27222/Desktop/tesis/tek-secrets/rotation && \
LAMBDA_NAME=$(cd terraform && terraform output -raw lambda_master_name) && \
aws lambda invoke \
  --function-name "$LAMBDA_NAME" \
  --region us-east-1 \
  --cli-binary-format raw-in-base64-out \
  --payload '{"source":"manual-test","triggered":true}' \
  response.json && \
cat response.json | jq .
```

---

**Resumen del flujo**:

```
Tu máquina
  ↓
aws lambda invoke (test manual)
  ↓
Lambda Maestro (en AWS)
  ├─ Conecta MongoDB
  ├─ Obtiene 50 proyectos
  └─ Envía 50 mensajes a SQS ← ESTO CREA EN AWS
  ↓
Response: { statusCode: 200, body: "..." }
  ↓
SQS Queue ahora tiene 50 mensajes
  ↓
Lambda Worker (automático) consume en paralelo
  ├─ Procesa proyecto 1
  ├─ Procesa proyecto 2
  ├─ Procesa proyecto 3
  └─ ... (paralelo)
  ↓
MongoDB actualizado (secretos re-encriptados)
```

### 4.2 Verificar SQS Queue

**¿Qué hace?**

Verifica que los mensajes llegaron a SQS (que Lambda Maestro funcionó):
- Ver cantidad de mensajes en queue
- Ver contenido de un mensaje (sin eliminarlo)

**Ejecutar**:

```bash
# Estar en carpeta deployment
cd /Users/delta27222/Desktop/tesis/tek-secrets/rotation

# Obtener URL queue
QUEUE_URL=$(cd terraform && terraform output -raw sqs_queue_url)

# Ver cantidad de mensajes en queue
aws sqs get-queue-attributes \
  --queue-url "$QUEUE_URL" \
  --attribute-names ApproximateNumberOfMessages \
  --region us-east-1

# Ver un mensaje (sin eliminarlo)
aws sqs receive-message \
  --queue-url "$QUEUE_URL" \
  --region us-east-1 \
  --wait-time-seconds 1 | jq '.Messages[0]'
```

**Resultado esperado**:

**Cantidad de mensajes**:
```json
{
  "Attributes": {
    "ApproximateNumberOfMessages": "50"
  }
}
```
✅ Significa: 50 mensajes esperando en queue (uno por proyecto)

**Contenido de un mensaje**:
```json
{
  "MessageId": "abc123...",
  "ReceiptHandle": "xyz789...",
  "Body": "{\"project_id\": \"507f1f77bcf86cd799439011\", \"action\": \"rotate_and_reencrypt\", \"timestamp\": \"2026-07-12T00:05:30Z\"}"
}
```
✅ Significa: Cada mensaje contiene ID del proyecto + acción a ejecutar

**¿Qué se crea/modifica en AWS?**

- ✅ **SQS Queue**: Ahora tiene 50 mensajes (antes estaba vacía)
- ✅ **Cada mensaje**: Esperando a ser consumido por Lambda Worker
- ❌ **NO se crea nada más**: Solo mensajes en queue

**Timeline**:
```
00:05:00 - Lambda Maestro enviado (4.1)
00:05:05 - SQS tiene 50 mensajes ← ESTÁS AQUÍ (4.2)
00:05:06 - Lambda Worker comienza a consumir
00:05:15 - Mayoría de proyectos procesados
00:05:20 - SQS Queue vacía (todos consumidos)
```

### 4.3 Monitorear Lambda Worker

**¿Qué hace?**

Ver en TIEMPO REAL cómo Lambda Worker procesa los proyectos:
- Número de instancias ejecutándose (concurrency)
- Logs detallados de cada proyecto procesado

**Ejecutar**:

```bash
# Estar en carpeta deployment
cd /Users/delta27222/Desktop/tesis/tek-secrets/rotation

# Obtener nombre
WORKER_NAME=$(cd terraform && terraform output -raw lambda_worker_name)

# Opción 1: Ver concurrency (instancias activas)
watch -n 2 "aws lambda get-function-concurrency \
  --function-name '$WORKER_NAME' \
  --region us-east-1"

# Opción 2: Ver logs en vivo (RECOMENDADO)
aws logs tail /aws/lambda/$WORKER_NAME \
  --region us-east-1 \
  --follow
```

**Resultado esperado (logs en vivo)**:

```
2026-07-12T00:05:06.123Z    🚀 Inicio - SQS Event
2026-07-12T00:05:06.456Z    Records: 1
2026-07-12T00:05:06.789Z    📨 Procesando proyecto: 507f1f77bcf86cd799439011
2026-07-12T00:05:06.900Z    📡 POST https://tu-app.onrender.com/v1/internal/projects/507f.../rotate-encryption
2026-07-12T00:05:08.200Z    ✅ API respondió 200: {"status":"success","environments_processed":3,...}
2026-07-12T00:05:08.250Z    ✅ Proyecto 507f...: success (3 OK, 0 fallos)
2026-07-12T00:05:08.300Z    ✅ Mensaje confirmado en SQS
```

✅ Significa: el Worker llamó a la API y ésta rotó + re-encriptó exitosamente.

> El detalle de la rotación (generar llave, rotar, re-encriptar cada environment)
> aparece en los logs de la **API en Render**, no en CloudWatch.

**¿Qué se crea/modifica en AWS?**

**En MongoDB**:
- ✅ Nueva llave creada: `key_proj_20260712_002`
- ✅ Llave anterior deprecada: `key_proj_20260712_001` → status="deprecated"
- ✅ 5 ambientes re-encriptados:
  - `proj-dev` secrets re-encriptados con llave nueva
  - `proj-staging` secrets re-encriptados con llave nueva
  - `proj-prod` secrets re-encriptados con llave nueva
  - etc.

**En SQS**:
- ✅ Mensaje CONSUMIDO y ELIMINADO de queue
- ✅ Queue count disminuye (49 → 48 → ... → 0)

**En CloudWatch Logs**:
- ✅ Nuevos logs agregados (cada instancia Lambda crea logs)

**Timeline paralelo** (si 5 Lambda Worker activos):
```
00:05:06 - Lambda Worker 1 comienza proyecto_1
00:05:06 - Lambda Worker 2 comienza proyecto_2
00:05:06 - Lambda Worker 3 comienza proyecto_3
00:05:06 - Lambda Worker 4 comienza proyecto_4
00:05:06 - Lambda Worker 5 comienza proyecto_5
        ↓ (en paralelo, ~15 segundos después)
00:05:22 - Todos completados (no 5x15=75s)
```

### 4.4 Verificar MongoDB

**¿Qué hace?**

Verifica que los secretos fueron **re-encriptados** correctamente:
- Verifica metadata de encriptación
- Confirma que llave nueva está activa
- Comprueba que `requires_reencryption: false` (completado)

**Ejecutar**:

```bash
# Conectar a MongoDB con tu cliente favorito (MongoDB Compass, mongosh, etc)

use secrets-27222

# Ver metadata de encriptación de un ambiente
db.environments.findOne(
  { project_id: "tu-proyecto-id" },
  { secrets_encryption: 1 }
)

# Ver la llave activa del proyecto
db.encryption_keys.findOne(
  { project_id: "tu-proyecto-id", is_primary: true },
  { key_material: 0 }  # Excluye material criptográfico
)

# Ver historial de llaves (ver rotación)
db.encryption_keys.find(
  { project_id: "tu-proyecto-id" }
).sort({ version: -1 })
```

**Resultado esperado - Metadata ambiente**:

```json
{
  "_id": ObjectId("507f1f77bcf86cd799439012"),
  "name": "prod",
  "project_id": "507f1f77bcf86cd799439011",
  "secrets_encryption": {
    "key_version": 2,
    "encrypted_with_key_id": "key_proj_20260712_002",
    "encrypted_at": ISODate("2026-07-12T00:05:22Z"),
    "requires_reencryption": false
  }
}
```

✅ Significa:
- `key_version: 2` → Usando llave v2 (la más nueva)
- `encrypted_with_key_id: "key_proj_20260712_002"` → ID de la llave actual
- `encrypted_at: 2026-07-12T00:05:22Z` → Fue re-encriptado HOY a esta hora
- `requires_reencryption: false` → No necesita más re-encriptación

**Resultado esperado - Llave activa**:

```json
{
  "_id": ObjectId("507f1f77bcf86cd799439013"),
  "key_id": "key_proj_20260712_002",
  "project_id": "507f1f77bcf86cd799439011",
  "version": 2,
  "status": "active",
  "is_primary": true,
  "algorithm": "Fernet",
  "created_at": ISODate("2026-07-12T00:05:07Z"),
  "activated_at": ISODate("2026-07-12T00:05:07Z"),
  "expires_at": ISODate("2027-07-12T00:05:07Z")
}
```

✅ Significa:
- `status: "active"` → Esta es la llave usada ahora
- `is_primary: true` → Es la principal (usada para nuevos secretos)
- `version: 2` → Segunda versión (rotación completada)

**Resultado esperado - Historial llaves**:

```json
[
  // v2 (actual)
  {
    "version": 2,
    "status": "active",
    "is_primary": true,
    "key_id": "key_proj_20260712_002",
    "created_at": ISODate("2026-07-12T00:05:07Z")
  },
  // v1 (anterior)
  {
    "version": 1,
    "status": "deprecated",
    "is_primary": false,
    "key_id": "key_proj_20260712_001",
    "created_at": ISODate("2026-07-11T00:00:00Z")
  }
]
```

✅ Significa:
- v2: status="active" e is_primary=true → En uso
- v1: status="deprecated" e is_primary=false → Antigua (pero aún desencriptable)

**¿Qué se crea/modifica en AWS/MongoDB?**

**Colección: encryption_keys**
- ✅ Nueva llave: `key_proj_20260712_002` con status="active"
- ✅ Llave anterior: `key_proj_20260712_001` con status="deprecated"

**Colección: environments**
- ✅ Metadata actualizada: `secrets_encryption.encrypted_with_key_id = "key_proj_20260712_002"`
- ✅ Todos los secrets desencriptados y re-encriptados

**Verificación final** (la más importante):

```bash
# Desencriptar un secreto (prueba de que funcionó)
db.environments.findOne(
  { project_id: "tu-proyecto-id", name: "prod" },
  { secrets: { DB_PASSWORD: 1 } }
)

# Debe mostrar:
# {
#   secrets: {
#     DB_PASSWORD: "gAAAAABl8h7s..."  ← Encriptado con llave v2
#   }
# }

# Si intentas desencriptarlo manualmente (con Motor):
# fernet = Fernet(key_material_from_v2)
# plaintext = fernet.decrypt(encrypted_value)
# → Resultado: "super-secret-password" ✅
```

### 4.5 Verificar EventBridge Schedule

**¿Qué hace?**

Verifica que EventBridge está configurado para ejecutar Lambda Maestro automáticamente cada día:
- Valida que cron está habilitado
- Muestra próxima ejecución programada

**Ejecutar**:

```bash
# Estar en carpeta deployment
cd /Users/delta27222/Desktop/tesis/tek-secrets/rotation

# Obtener nombre regla
RULE_NAME=$(cd terraform && terraform output -raw eventbridge_rule_name)

# Ver configuración de la regla
aws events describe-rule \
  --name "$RULE_NAME" \
  --region us-east-1

# Ver targets (Lambda Maestro conectado)
aws events list-targets-by-rule \
  --rule "$RULE_NAME" \
  --region us-east-1
```

**Resultado esperado - Descripción regla**:

```json
{
  "Name": "tek-secrets-rotation-schedule",
  "Arn": "arn:aws:events:us-east-1:123456789012:rule/tek-secrets-rotation-schedule",
  "ScheduleExpression": "cron(0 0 * * ? *)",
  "State": "ENABLED",
  "ManagedBy": "terraform",
  "CreatedBy": "arn:aws:iam::123456789012:root",
  "Description": "Rotación diaria de llaves de encriptación a las 00:00 UTC"
}
```

✅ Significa:
- `ScheduleExpression: "cron(0 0 * * ? *)"` → Ejecuta diariamente a las 00:00 UTC
- `State: "ENABLED"` → Está activa (no pausada)
- `ManagedBy: "terraform"` → Creada por Terraform

**Resultado esperado - Targets**:

```json
{
  "Targets": [
    {
      "Id": "1",
      "Arn": "arn:aws:lambda:us-east-1:123456789012:function:tek-secrets-rotation-master",
      "RoleArn": "arn:aws:iam::123456789012:role/service-role/...",
      "Input": "{\"source\":\"eventbridge\",\"triggered\":true,\"timestamp\":\"...\"}"
    }
  ]
}
```

✅ Significa:
- Target conectado: Lambda Maestro
- Input: Evento que se envía a Lambda

**¿Qué se crea/modifica en AWS?**

- ✅ **EventBridge Rule**: Creada y HABILITADA
- ✅ **Trigger**: Lambda Maestro está conectado
- ✅ **Schedule**: 00:00 UTC diariamente
- ❌ **NO se ejecuta ahora**: Solo está programado (esperando 00:00 UTC)

**Timeline automático** (después que todo está deployado):

```
2026-07-13 00:00:00 UTC
  ↓
EventBridge dispara automáticamente
  ↓
Lambda Maestro se ejecuta (sin intervención manual)
  ↓
Obtiene 50 proyectos de MongoDB
  ↓
Envía 50 mensajes a SQS
  ↓
Lambda Worker consume en paralelo
  ↓
Rota + re-encripta secretos
  ↓
2026-07-13 00:05:30 UTC → COMPLETADO

...
2026-07-14 00:00:00 UTC → Se repite automáticamente
...
```

**Para simular ejecución manual** (sin esperar a 00:00 UTC):

```bash
# Opción 1: Usar test manual 4.1 (simula EventBridge)
# Opción 2: Disparar regla manualmente
aws events put-events \
  --entries '[
    {
      "Source": "manual-test",
      "DetailType": "EventBridge Rule Test",
      "Detail": "{\"triggered\": true}"
    }
  ]'
```

**Deshabilitar EventBridge** (si necesitas pausar):

```bash
RULE_NAME=$(cd terraform && terraform output -raw eventbridge_rule_name)

# Pausar
aws events disable-rule --name "$RULE_NAME" --region us-east-1

# Reanudar
aws events enable-rule --name "$RULE_NAME" --region us-east-1

# Verificar estado
aws events describe-rule --name "$RULE_NAME" --region us-east-1 | jq '.State'
# Output: "DISABLED" o "ENABLED"
```

---

### 4.6 Verificar que funciona (Validación Final)

**¿Cómo verificar que todo está funcionando correctamente?**

```bash
cd /Users/delta27222/Desktop/tesis/tek-secrets/rotation

# OPCIÓN 1: Ver logs en vivo (RECOMENDADO)
WORKER=$(cd terraform && terraform output -raw lambda_worker_name)
aws logs tail /aws/lambda/$WORKER --follow --region us-east-1

# Esperar a que aparezcan logs. Debe ver:
# ✅ [INFO] 🚀 Inicio - SQS Event
# ✅ [INFO] 📨 Procesando proyecto: ...
# ✅ [INFO] ✅ Llave generada
# ✅ [INFO] ✅ Rotación completada
# ✅ [INFO] ✅ Mensaje confirmado en SQS
# (NO debe ver: [ERROR], ImportError, etc)
```

**Comandos para validar cada componente**:

```bash
# 1. Ver si Lambda Maestro está procesando
MASTER=$(cd terraform && terraform output -raw lambda_master_name)
aws logs tail /aws/lambda/$MASTER --region us-east-1 | tail -20

# 2. Ver si hay mensajes en SQS (in flight = siendo procesados)
QUEUE_URL="https://sqs.us-east-1.amazonaws.com/087000170671/tek-secrets-rotation-queue"
aws sqs get-queue-attributes \
  --queue-url "$QUEUE_URL" \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
  --region us-east-1
# Resultado esperado:
# "ApproximateNumberOfMessages": 0 (ninguno esperando)
# "ApproximateNumberOfMessagesNotVisible": 0+ (siendo procesados)

# 3. Verificar que NO hay mensajes en DLQ (Dead Letter Queue)
DLQ_URL="https://sqs.us-east-1.amazonaws.com/087000170671/tek-secrets-rotation-dlq"
aws sqs get-queue-attributes \
  --queue-url "$DLQ_URL" \
  --attribute-names ApproximateNumberOfMessages \
  --region us-east-1
# Resultado esperado: "ApproximateNumberOfMessages": 0

# 4. Ver si EventBridge está activo
RULE_NAME=$(cd terraform && terraform output -raw eventbridge_rule_name)
aws events describe-rule --name "$RULE_NAME" --region us-east-1 | jq '.State'
# Resultado esperado: "ENABLED"
```

**Resumen de lo que sucede**:

```
EventBridge (00:00 UTC)
    ↓
Lambda Maestro
  ├─ Conecta MongoDB
  ├─ Obtiene proyectos
  └─ Envía a SQS (1-N mensajes)
    ↓
SQS Queue recibe mensajes
    ↓
Lambda Worker (múltiples instancias paralelo)
  ├─ Recibe 1 proyecto por mensaje
  ├─ Genera llave nueva
  ├─ Rota llave (pending → active)
  ├─ Re-encripta secretos de TODOS los ambientes
  ├─ Actualiza MongoDB
  └─ Confirma en SQS
    ↓
CloudWatch Logs (registra todo)
    ↓
✅ Sistema completo
```

---

## Paso 5: Monitoreo

### 5.1 CloudWatch Dashboard

```bash
# Crear dashboard (manual en AWS Console)
# https://console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards:

# O con CLI:
LAMBDA_MASTER=$(terraform output -raw lambda_master_name)
LAMBDA_WORKER=$(terraform output -raw lambda_worker_name)
QUEUE_URL=$(terraform output -raw sqs_queue_url)

# Ver métricas Lambda Maestro
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Invocations \
  --dimensions Name=FunctionName,Value=$LAMBDA_MASTER \
  --statistics Sum \
  --start-time 2026-07-10T00:00:00Z \
  --end-time 2026-07-11T23:59:59Z \
  --period 86400 \
  --region us-east-1
```

### 5.2 Monitoreo Logs

```bash
# CloudWatch Logs (última hora)
LOG_GROUP="/aws/lambda/$(terraform output -raw lambda_worker_name)"

aws logs tail "$LOG_GROUP" \
  --region us-east-1 \
  --follow \
  --since 1h

# Filtrar errores
aws logs filter-log-events \
  --log-group-name "$LOG_GROUP" \
  --filter-pattern "[ERROR]" \
  --region us-east-1 | jq '.events'

# Ver resumen
aws logs describe-log-streams \
  --log-group-name "$LOG_GROUP" \
  --region us-east-1 \
  --order-by LastEventTime \
  --descending \
  --max-items 10
```

### 5.3 Alertas (SNS)

```bash
# Crear SNS topic para alertas
aws sns create-topic \
  --name tek-secrets-rotation-alerts \
  --region us-east-1

# Suscribirse (recibir emails)
TOPIC_ARN="arn:aws:sns:us-east-1:ACCOUNT_ID:tek-secrets-rotation-alerts"

aws sns subscribe \
  --topic-arn "$TOPIC_ARN" \
  --protocol email \
  --notification-endpoint "tu@email.com" \
  --region us-east-1

# Confirmar suscripción (email que recibirás)

# Modificar Terraform para enviar alertas a SNS:
# En main.tf, agregar a CloudWatch Alarms:
# alarm_actions = ["${aws_sns_topic.alerts.arn}"]
```

### 5.4 Dashboard personalizado

```bash
# AWS Console → CloudWatch → Dashboards → Create Dashboard

# Agregar widgets:
# 1. Lambda Maestro - Invocations
# 2. Lambda Worker - Invocations + Errors + Duration
# 3. SQS Queue - Messages sent + Received + Deleted
# 4. SQS DLQ - Messages (debe ser 0)
# 5. CloudWatch Logs Insights - Error rate

# CloudWatch Logs Insights query:
fields @timestamp, @message, project_id, duration_seconds
| filter @message like /✅/
| stats count() as successful, avg(duration_seconds) as avg_duration by project_id
| sort avg_duration desc
```

---

## Troubleshooting

### Problema 1: Lambda Maestro timeout (>60s)

**Síntomas**: Lambda Maestro tarda mucho, timeout, pocos proyectos en queue

**Causas**:
- MongoDB conexión lenta
- Demasiados proyectos (>1000)
- Network latency

**Solución**:

```bash
# Aumentar timeout Maestro
terraform apply -var="lambda_master_timeout=120"

# O en terraform.tfvars:
# lambda_master_timeout = 120
```

### Problema 2: SQS DLQ con mensajes

**Síntomas**: Proyectos no se procesan, aparecen en DLQ

**Diagnóstico**:

```bash
DLQ_URL=$(terraform output -raw sqs_dlq_url)

# Ver mensajes en DLQ
aws sqs receive-message \
  --queue-url "$DLQ_URL" \
  --region us-east-1 \
  --max-number-of-messages 10 | jq '.Messages'

# Ver logs del worker
WORKER=$(terraform output -raw lambda_worker_name)
aws logs tail /aws/lambda/$WORKER --region us-east-1 --follow
```

**Causas comunes**:
- MongoDB conexión refused
- Llave encryption no encontrada
- Secretos corruptos

**Solución**: Verificar MongoDB, limpiar DLQ manual:

```bash
# Purgar DLQ (eliminar mensajes)
aws sqs purge-queue --queue-url "$DLQ_URL" --region us-east-1
```

### Problema 3: Lambda Worker timeout (>900s)

**Síntomas**: Algunos proyectos nunca terminan

**Causas**:
- Demasiados secretos por ambiente (>1000)
- MongoDB muy lenta
- Network issues

**Solución**:

```bash
# Aumentar timeout worker
# En terraform.tfvars:
lambda_worker_timeout = 1200  # 20 minutos (máx: 900s en Lambda actual)

# O aumentar memoria (mejor CPU)
lambda_worker_memory = 1024  # 1 GB en lugar de 512MB
```

### Problema 4: ConnectionError a MongoDB

**Síntomas**: Lambda logs muestran `pymongo.errors.ConnectionFailure`

**Causas**:
- MONGODB_URL inválida
- Whitelist IP MongoDB (si usas Atlas)
- Network VPC issues

**Solución**:

```bash
# Validar MONGODB_URL
echo $TF_VAR_mongodb_url
# Debe ser: mongodb+srv://user:pass@cluster.mongodb.net/

# Si usas MongoDB Atlas: añadir IP Lambda a whitelist
# AWS Lambda IPs: dinámicas, usar VPC endpoint o Atlas IP whitelist "0.0.0.0/0"

# Testing conexión (local):
python3 -c "
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def test():
    client = AsyncIOMotorClient('$TF_VAR_mongodb_url')
    db = client['secrets-27222']
    result = await db.command('ping')
    print('✅ MongoDB OK:', result)

asyncio.run(test())
"
```

### Problema 4.5: Lambda Worker no inicia - "cannot open shared object file" o "invalid ELF header"

**Síntomas**: CloudWatch logs muestran:
```
[ERROR] Runtime.ImportModuleError: Unable to import module 'rotation_worker': 
  /var/task/cryptography/hazmat/bindings/_rust.abi3.so: cannot open shared object file
```

> ✅ **Con la arquitectura actual este problema NO aplica al Worker**: el Worker ya
> no lleva `cryptography`/`pyaes`/`motor` (solo stdlib), así que no hay binarios que
> fallen. Esta sección queda como referencia histórica y para el **Maestro** (que sí
> lleva `motor`/`pymongo` y por eso se compila con Docker).

**Causa** (histórica):
- Compilaste en macOS/Windows, pero Lambda corre en Linux x86_64
- Las librerías con binarios (cryptography, pymongo) requieren compilarse para Linux
- Por eso el Maestro se empaqueta con Docker

**Solución (para el Maestro)**:

1. **Usa Docker para compilar** (incluido en scripts/build_worker.sh):
```bash
docker run --rm \
  --entrypoint bash \
  -v $(pwd)/lambda:/var/task \
  -v $(pwd)/terraform:/output \
  public.ecr.aws/lambda/python:3.12 \
  -c "
    pip install -t /tmp/worker motor pyaes
    cp /var/task/rotation_worker.py /tmp/worker/
    cd /tmp/worker
    python3 -c \"import zipfile; z=zipfile.ZipFile('/output/lambda_worker.zip','w'); [z.write(f'{r}/{f}') for r,_,fs in __import__('os').walk('.') for f in fs]\"
  "
```

2. **Destroy + Recreate Lambda Worker**:
```bash
cd terraform
terraform destroy -target=aws_lambda_function.rotation_worker -auto-approve
terraform apply -target=aws_lambda_function.rotation_worker -auto-approve
```

3. **Verificar ZIP contiene pyaes (NO cryptography)**:
```bash
unzip -l terraform/lambda_worker.zip | grep -E "(pyaes|cryptography)"
# Debe mostrar: pyaes-1.6.1.dist-info/
# NO debe mostrar: cryptography/
```

4. **Test**:
```bash
MASTER=$(terraform output -raw lambda_master_name)
aws lambda invoke --function-name $MASTER --region us-east-1 /tmp/test.json
# Verificar logs del worker: NO deben tener errores de import
```

### Problema 5: Encriptación/Desencriptación falla

**Síntomas**: Logs muestran `Invalid key length` o `fernet.InvalidToken`

**Causas**:
- Llave antigua no disponible
- Secretos corrupto o inválido
- Cambio de encryption algorithm

**Solución**:

```bash
# Verificar llave activa
mongo_client db.encryption_keys.findOne({ is_primary: true })

# Ver metadata ambiente problemático
db.environments.findOne(
  { name: "staging" },
  { secrets_encryption: 1 }
)

# Si llave antigua no existe: skip reencriptación manual
# O restaurar backup de encryption_keys
```

---

## Costos

### Desglose mensual (estimado)

| Servicio | Métrica | Precio | Costo mensual |
|----------|---------|--------|---------------|
| **Lambda Maestro** | 30 invocaciones × 1s × 256MB | $0.0000002083/GB-s | $0.06 |
| **Lambda Worker** | 1500 invocaciones × 3s × 512MB | $0.0000002083/GB-s | $0.47 |
| **SQS** | 1500 mensajes × $0.40/millón | $0.40/millón | $0.60 |
| **CloudWatch Logs** | ~500MB/mes × $0.50/GB ingested | $0.50/GB | $0.25 |
| **EventBridge** | 30 reglas × $0.35/millón eventos | $0.35/millón | $0.01 |
| **TOTAL estimado** | | | **~$1.40 USD/mes** |

**Notas**:
- Precios AWS 2026 (us-east-1)
- Varían según volumen proyectos
- Includes free tier: 1 millón invocaciones Lambda, 100 GB logs

### Optimizaciones de costo

```bash
# 1. Reducir memory → menos costo (pero más lento)
lambda_worker_memory = 256  # Mínimo: 128 MB

# 2. Reducir retention logs
aws logs modify-log-retention --log-group-name /aws/lambda/... --retention-in-days 7

# 3. Usar Lambda@Edge (distribución geográfica)
# No necesario para esta use case

# 4. Reserved Concurrency (si predecible)
# No necesario para cron job
```

---

## Rollback

### Caso 1: Destruir infraestructura completa

```bash
cd /Users/delta27222/Desktop/tesis/tek-secrets/rotation/terraform

# Ver qué va a destruir
terraform plan -destroy

# Destruir (irreversible)
terraform destroy

# Output:
# - Destruyendo SQS queues
# - Destruyendo Lambda functions
# - Destruyendo EventBridge rules
# - Destruyendo IAM roles
#
# Destroy complete! Resources: XX destroyed.
```

### Caso 2: Volver a versión anterior (con tfstate)

```bash
# Si guardaste tfstate anterior
terraform plan -destroy -out=rollback.tfplan
terraform apply rollback.tfplan
```

### Caso 3: Emergency: Deshabilitar rotación

```bash
# Sin destroyar infraestructura:
RULE_NAME=$(terraform output -raw eventbridge_rule_name)

aws events disable-rule \
  --name "$RULE_NAME" \
  --region us-east-1

# Verificar
aws events describe-rule --name "$RULE_NAME" --region us-east-1
# "State": "DISABLED"

# Re-habilitar después
aws events enable-rule \
  --name "$RULE_NAME" \
  --region us-east-1
```

---

## Operación Normal

### Verificación diaria (1 minuto)

```bash
#!/bin/bash

LAMBDA_WORKER=$(terraform output -raw lambda_worker_name 2>/dev/null)
DLQ_URL=$(terraform output -raw sqs_dlq_url 2>/dev/null)

# 1. Revisar DLQ vacío
DLQ_COUNT=$(aws sqs get-queue-attributes \
  --queue-url "$DLQ_URL" \
  --attribute-names ApproximateNumberOfMessages \
  --region us-east-1 \
  --query 'Attributes.ApproximateNumberOfMessages' \
  --output text)

if [[ $DLQ_COUNT -gt 0 ]]; then
  echo "⚠️  ALERT: $DLQ_COUNT mensajes en DLQ"
  # Investigar y purgar
else
  echo "✅ DLQ limpia"
fi

# 2. Ver últimos errores
ERRORS=$(aws logs filter-log-events \
  --log-group-name "/aws/lambda/$LAMBDA_WORKER" \
  --filter-pattern "[ERROR]" \
  --region us-east-1 \
  --start-time $(($(date +%s) - 86400)) \
  --query 'events | length(@)' \
  --output text)

if [[ $ERRORS -gt 0 ]]; then
  echo "⚠️  ALERT: $ERRORS errores en últimas 24h"
else
  echo "✅ Sin errores"
fi

# 3. Ver duración promedio
aws logs start-query \
  --log-group-name "/aws/lambda/$LAMBDA_WORKER" \
  --start-time $(($(date +%s) - 86400)) \
  --end-time $(date +%s) \
  --query-string 'fields duration_seconds | stats avg(duration_seconds)' \
  --region us-east-1
```

---

## Eliminar o Pausar Infraestructura

### Opción 1: Eliminar TODO (Sin Costos)

Si no necesitas más la rotación automática, destruye toda la infraestructura:

```bash
cd /Users/delta27222/Desktop/tesis/tek-secrets/rotation/terraform

# Paso 1: Ver qué se va a eliminar (IMPORTANTE)
terraform plan -destroy

# Output esperado:
# will be destroyed:
# ├─ aws_sqs_queue.rotation_queue
# ├─ aws_sqs_queue.rotation_dlq
# ├─ aws_lambda_function.rotation_master
# ├─ aws_lambda_function.rotation_worker
# ├─ aws_cloudwatch_event_rule.rotation_schedule
# ├─ aws_iam_role.lambda_master_role
# ├─ aws_iam_role.lambda_worker_role
# ├─ aws_cloudwatch_log_group.lambda_master_logs
# ├─ aws_cloudwatch_log_group.lambda_worker_logs
# └─ aws_cloudwatch_metric_alarm.*

# Paso 2: Si todo se ve correcto, destruir
terraform destroy

# Confirmación:
# Do you really want to destroy all resources?
# Type 'yes' to confirm

# Esperar 2-5 minutos
# ✅ Todo eliminado. Sin cobros.
```

**Qué se elimina**:
- ✅ SQS Queues (main + DLQ)
- ✅ Lambda Functions (maestro + worker)
- ✅ EventBridge Rule (cron)
- ✅ IAM Roles
- ✅ CloudWatch Logs
- ✅ CloudWatch Alarms

**Qué NO se elimina** (está afuera de Terraform):
- ❌ MongoDB (en tu infraestructura)
- ❌ Datos históricos (backups, snapshots)

**Costos después de destroy**:
```
Lambda:        $0 (was $0.53/mes)
SQS:           $0 (was $0.60/mes)
CloudWatch:    $0 (was $0.25/mes)
EventBridge:   $0 (was $0.01/mes)
───────────────────────────────
TOTAL:        $0 ✅
```

---

### Opción 2: Pausar (Sin Destruir)

Si quieres mantener la infraestructura pero pausar la ejecución automática:

```bash
# Deshabilitar EventBridge cron (Lambda no se ejecuta)
RULE_NAME=$(cd terraform && terraform output -raw eventbridge_rule_name)

aws events disable-rule \
  --name "$RULE_NAME" \
  --region us-east-1

# Verificar
aws events describe-rule \
  --name "$RULE_NAME" \
  --region us-east-1
# "State": "DISABLED" ✅

# Costos mientras está pausado:
# Lambda:        $0 (no se ejecuta)
# SQS:           ~$0.01/mes (queue vacía)
# CloudWatch:    ~$0.05/mes (logs retention)
# EventBridge:   $0 (regla deshabilitada)
# ───────────────────────────────
# TOTAL:        ~$0.06/mes (muy bajo)
```

**Para reanudar después**:

```bash
RULE_NAME=$(cd terraform && terraform output -raw eventbridge_rule_name)

aws events enable-rule \
  --name "$RULE_NAME" \
  --region us-east-1

# Verificar
aws events describe-rule \
  --name "$RULE_NAME" \
  --region us-east-1
# "State": "ENABLED" ✅

# Próxima ejecución: mañana a las 00:00 UTC
```

---

### Opción 3: Destruir Selectivamente

Si solo quieres eliminar ciertos recursos (ej: solo Lambdas, mantener SQS):

```bash
# Eliminar solo Lambda Worker
terraform destroy -target=aws_lambda_function.rotation_worker

# Eliminar solo SQS Queue
terraform destroy -target=aws_sqs_queue.rotation_queue

# Eliminar solo EventBridge
terraform destroy -target=aws_cloudwatch_event_rule.rotation_schedule
```

**⚠️ Cuidado**: Eliminar selectivamente puede dejar infraestructura inconsistente. Recomendado solo si sabes qué haces.

---

### Comparación: Eliminar vs Pausar

| Opción | Costo | Mantiene Infraestructura | Tiempo Reanudar | Caso |
|--------|-------|------------------------|-----------------|----|
| **Destroy** | $0 | ❌ No | 2-3 min (redeploy) | No necesitas más |
| **Pause** | ~$0.06/mes | ✅ Sí | Inmediato (enable) | Pausar temporalmente |
| **Selectivo** | Varía | Parcial | Varía | Ajuste fino |

---

### Checklist Antes de Destruir

- [ ] ✅ Guardar `terraform.tfstate` (por si necesitas recuperar info)
- [ ] ✅ Verificar `terraform plan -destroy` (leer qué se va)
- [ ] ✅ Backup de configuración (copiar terraform/terraform.tfvars)
- [ ] ✅ Confirmar con equipo (si es compartido)
- [ ] ✅ Ejecutar `terraform destroy`

---

### Recuperar Después de Destroy

Si accidentalmente ejecutaste `terraform destroy` y quieres recuperar:

```bash
# 1. El código sigue en Git
git log --oneline

# 2. Terraform state se guarda localmente
ls -la terraform/terraform.tfstate*

# 3. Para recrear:
cd terraform
terraform apply

# ⚠️ Nota: Crea todo de nuevo (puede tardar 2-3 min)
```

---

## Apéndice: AWS Console Links

```
EventBridge Rules:
https://console.aws.amazon.com/events/home?region=us-east-1#/rules

Lambda Functions:
https://console.aws.amazon.com/lambda/home?region=us-east-1#/functions

SQS Queues:
https://console.aws.amazon.com/sqs/v3/home?region=us-east-1#/queues

CloudWatch Logs:
https://console.aws.amazon.com/logs/home?region=us-east-1#logStream:

CloudWatch Alarms:
https://console.aws.amazon.com/cloudwatch/home?region=us-east-1#alarmsV2:

Terraform State (si usas S3):
https://s3.console.aws.amazon.com/s3/buckets/tek-secrets-terraform-state
```

---

## Support & Escalation

| Issue | Contact | Tiempo |
|-------|---------|--------|
| Lambda errors | CloudWatch Logs | Inmediato |
| MongoDB issues | DBA team | 1-4h |
| AWS account issues | AWS Support | Depende del plan |
| Terraform issues | Terraform community | async |

---

**Última actualización**: 2026-07-12  
**Versión estable**: 1.0  
**Mantenedor**: Tek Secrets Team
