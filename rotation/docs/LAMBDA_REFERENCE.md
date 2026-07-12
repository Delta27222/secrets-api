# Lambda Functions Documentation

**Localización**: `/Users/delta27222/Desktop/tesis/tek-secrets/rotation/lambda/`

---

## Archivos

```
tek-secrets/rotation/lambda/
├── rotation_master.py      # 📍 Lambda Maestro
└── rotation_worker.py      # 📍 Lambda Worker
```

---

## 🗺️ Flujo general (visual)

```mermaid
sequenceDiagram
    autonumber
    participant EB as ⏰ EventBridge
    participant M as λ Maestro
    participant DB as 🍃 MongoDB
    participant SQS as 📨 SQS
    participant W as λ Worker
    participant API as ☁️ API (Render)

    EB->>M: trigger cron (00:00 UTC)
    M->>DB: obtener todos los proyectos
    DB-->>M: [project_ids]
    loop por cada proyecto
        M->>SQS: send_message(project_id)
    end
    M-->>EB: { projects_queued }

    SQS->>W: entrega mensaje (project_id)
    W->>API: POST /v1/internal/projects/{id}/rotate-encryption<br/>Authorization: Bearer tok_...
    Note over API,DB: La API hace TODO con CSFLE
    API->>DB: genera + rota llave, re-encripta secrets
    API-->>W: 200 { status: success }
    W-->>SQS: ✅ borra mensaje
```

---

## 1. rotation_master.py (Lambda Maestro)

**Archivo**: `/Users/delta27222/Desktop/tesis/tek-secrets/rotation/lambda/rotation_master.py`

```mermaid
flowchart LR
    EB([⏰ EventBridge<br/>00:00 UTC]) --> H[lambda_handler]
    H --> G[get_all_projects]
    G <-->|find projects| DB[(🍃 MongoDB)]
    G --> L{por cada<br/>project_id}
    L -->|send_to_sqs| SQS[📨 SQS Queue]
    L --> R[["{ projects_queued }"]]
```

### Configuración

```python
# Environment variables (inyectados por Terraform)
MONGODB_URL = os.getenv('MONGODB_URL')           # mongodb+srv://...
MONGO_DB = os.getenv('MONGO_DB', 'secrets-27222')
SQS_QUEUE_URL = os.getenv('SQS_QUEUE_URL')       # https://sqs.us-east-1.amazonaws.com/...
```

### Funciones

#### `async get_all_projects(mongo_client)`
- **Qué hace**: Obtiene todos los proyectos de MongoDB
- **Retorna**: Lista de project_ids `[str, str, ...]`
- **Error handling**: Registra y lanza excepción si falla

```python
project_ids = await get_all_projects(mongo_client)
# Resultado: ['507f1f77bcf86cd799439011', '507f191e810c19729de860ea', ...]
```

#### `send_to_sqs(project_id)`
- **Qué hace**: Envía proyecto a SQS Queue
- **Mensaje**: `{ project_id, action, timestamp }`
- **Retorna**: `bool` (True si OK, False si error)

```python
success = send_to_sqs('507f1f77bcf86cd799439011')
# SQS recibe: { "project_id": "...", "action": "rotate_and_reencrypt", "timestamp": "..." }
```

#### `async process_all_projects()`
- **Qué hace**: Orquesta todo (obtiene + envía)
- **Retorna**: 
```python
{
    'status': 'success',
    'projects_total': 50,
    'projects_queued': 50,
    'projects_failed': 0,
    'timestamp': '2026-07-11T00:00:00Z'
}
```

#### `lambda_handler(event, context)`
- **Qué es**: Entry point de Lambda
- **Disparado por**: EventBridge cron (00:00 UTC)
- **Retorna**:
```python
{
    'statusCode': 200,
    'body': '{"status": "success", "projects_queued": 50, ...}'
}
```

### Logs (CloudWatch)

Archivo: `/aws/lambda/tek-secrets-rotation-master`

```
🚀 Inicio - EventBridge Cron
Event: { "source": "eventbridge", "triggered": true, ... }
🔄 Iniciando rotación para todos proyectos
✅ Obtenidos 50 proyectos
📤 Proyecto 507f1f77bcf86cd799439011 enviado a SQS
📤 Proyecto 507f191e810c19729de860ea enviado a SQS
...
✅ Proceso completado: 50 en queue, 0 fallidos
```

### Tiempos

```
Conexión MongoDB:      ~500ms
SELECT * FROM projects: ~1-2s (depende proyectos)
Send 50 msgs SQS:     ~2-3s (paralelo)
───────────────────
Total:                ~4-5 segundos
```

---

## 2. rotation_worker.py (Lambda Worker)

**Archivo**: `/Users/delta27222/Desktop/tesis/tek-secrets/rotation/lambda/rotation_worker.py`

> ⚠️ **Arquitectura nueva**: el Worker ya NO hace encriptación. Solo hace un
> **HTTP POST a la API** en Render, que ejecuta la rotación + re-encriptación
> con su CSFLE nativo. El Worker usa **solo la stdlib** (`urllib`, `json`).
> Ver [SOLUTION_SUMMARY.md](./SOLUTION_SUMMARY.md).

```mermaid
flowchart LR
    SQS([📨 SQS<br/>project_id]) --> H[lambda_handler]
    H --> RP[rotate_project_via_api]
    RP -->|POST Bearer tok_| API[☁️ API Render]
    API -->|200 success| OK[✅ borra mensaje SQS]
    API -.error / status!=success.-> ERR[❌ raise → SQS reintenta → DLQ]
```

### Configuración

```python
# Environment variables (inyectados por Terraform)
API_BASE_URL       = os.getenv('API_BASE_URL')        # https://tu-app.onrender.com
ROTATION_API_TOKEN = os.getenv('ROTATION_API_TOKEN')  # tok_... (scope keys:rotate)
HTTP_TIMEOUT       = int(os.getenv('HTTP_TIMEOUT', '300'))
```

### Funciones Principales

#### `rotate_project_via_api(project_id)`

**Qué hace**: Llama al endpoint de rotación de la API para un proyecto.

```python
POST {API_BASE_URL}/v1/internal/projects/{project_id}/rotate-encryption
Header: Authorization: Bearer {ROTATION_API_TOKEN}
```

La API (no el Lambda) hace todo:
1. genera llave nueva (metadata completa, `key_material` Binary CSFLE)
2. rota (pending → active, anterior → deprecated)
3. re-encripta los secrets de cada environment
4. actualiza `secrets_encryption` de cada environment
5. audita en QuestDB

**Salida** (la respuesta JSON de la API):
```python
{
    'status': 'success',                    # o 'partial' si hubo errores
    'project_id': '507f1f77bcf86cd799439011',
    'new_key_id': 'key_..._20260712_002',
    'old_key_id': 'key_..._20260712_001',
    'environments_processed': 3,
    'environments_failed': 0,
    'errors': [],
    'duration_seconds': 1.08,
    'timestamp': '2026-07-12T06:00:00Z'
}
```

Si la API responde error HTTP o `status != success`, el Worker **lanza excepción**
→ SQS reintenta → eventualmente DLQ.

#### `lambda_handler(event, context)`

**Disparado por**: SQS Queue (consumidor). Por cada record: parsea `project_id`
y llama `rotate_project_via_api`.

**Event estructura**:
```python
{
    'Records': [
        {
            'messageId': 'abc123...',
            'body': '{"project_id": "507f1f77bcf86cd799439011", ...}',
            'receiptHandle': 'xyz789...'
        }
    ]
}
```

### Logs (CloudWatch)

Archivo: `/aws/lambda/tek-secrets-rotation-worker`

```
🚀 Inicio - SQS Event
Records: 1
📨 Procesando proyecto: 507f1f77bcf86cd799439011
📡 POST https://tu-app.onrender.com/v1/internal/projects/507f.../rotate-encryption
✅ API respondió 200: {"status":"success","environments_processed":3,...}
✅ Proyecto 507f...: success (3 OK, 0 fallos)
✅ Mensaje confirmado en SQS
```

### Tiempos

```
HTTP POST a la API:   ~1-3s (si la API está despierta)
  + cold start Render: hasta 30-60s si estaba dormida (plan free)
───────────────────
Por proyecto:         ~1-5 segundos (API despierta)
```

> El Worker tiene `HTTP_TIMEOUT=300s` y el Lambda `timeout=900s`, suficiente
> aun con cold start de Render.

---

## Build & Deploy

### Build Lambda Packages

```bash
cd /Users/delta27222/Desktop/tesis/tek-secrets/rotation

# Maestro (necesita motor/pymongo → Docker para binarios Linux)
./scripts/build_master.sh            # o el script del maestro

# Worker (solo stdlib → zip directo, sin dependencias)
./scripts/build_worker.sh
```

**Qué incluye cada ZIP**:
```
lambda_master.zip/               (~15 MB)
├── rotation_master.py           # Código
├── motor/ + pymongo/            # MongoDB async (para listar proyectos)
└── (dependencias Linux...)

lambda_worker.zip/               (~4.6 KB)
└── rotation_worker.py           # Código — SOLO stdlib (urllib, json)
```

> El Worker ya no lleva `motor`/`pymongo`/`cryptography`: delega todo a la API.

### Deploy a AWS

```bash
cd /Users/delta27222/Desktop/tesis/tek-secrets/rotation/terraform

# Terraform lee los ZIPs y sube a AWS
terraform init
terraform plan
terraform apply

# Crea en AWS:
# - Lambda function: tek-secrets-rotation-master
# - Lambda function: tek-secrets-rotation-worker
# - Configura triggers
```

### Pausar (sin destruir — deja de correr, no borra nada)

```bash
# Desactiva el cron: el Maestro deja de dispararse (sin costos de ejecución)
aws events disable-rule --name tek-secrets-rotation-schedule --region us-east-1

# Reactivar cuando quieras
aws events enable-rule  --name tek-secrets-rotation-schedule --region us-east-1
```

### Eliminar TODO (sin costos)

```bash
cd /Users/delta27222/Desktop/tesis/tek-secrets/rotation/terraform

terraform destroy          # borra SQS, Lambdas, EventBridge, IAM, CloudWatch

# Eliminar solo un recurso (ej. el Worker):
terraform destroy -target=aws_lambda_function.rotation_worker
```

> `disable-rule` = pausa (recursos siguen creados, $0 de ejecución).
> `terraform destroy` = borra todo (para recrear, `terraform apply`).

---

## Environment Variables

### Lambda Maestro

| Variable | Origen | Ejemplo |
|----------|--------|---------|
| `MONGODB_URL` | Terraform (sensitive) | `mongodb+srv://user:pass@cluster.mongodb.net/...` |
| `MONGO_DB` | Terraform (default) | `secrets-27222` |
| `SQS_QUEUE_URL` | Terraform (auto) | `https://sqs.us-east-1.amazonaws.com/123456789012/tek-secrets-rotation-queue` |

### Lambda Worker

| Variable | Origen | Ejemplo |
|----------|--------|---------|
| `API_BASE_URL` | Terraform (`api_base_url`) | `https://tu-app.onrender.com` |
| `ROTATION_API_TOKEN` | Terraform (`rotation_api_token`, sensitive) | `tok_...` (scope `keys:rotate`) |
| `HTTP_TIMEOUT` | opcional | `300` |

> El `ROTATION_API_TOKEN` se crea desde la UI (**Organización → tab Tokens**) y se
> pega en `terraform.tfvars`. Terraform lo inyecta como env var del Worker.

---

## Dependencias Python

**Lambda Maestro** (via Docker, binarios Linux):
```
motor / pymongo   # MongoDB async driver (para listar proyectos)
```

**Lambda Worker**: NINGUNA dependencia externa — solo la stdlib de Python
(`urllib`, `json`). Por eso su ZIP es de ~4.6 KB.

---

## Testing Local

### Test rotation_master.py

```bash
cd /Users/delta27222/Desktop/tesis/tek-secrets/rotation/lambda

# Simular evento EventBridge
python3 -c "
import json
import asyncio
import os

# Set env vars
os.environ['MONGODB_URL'] = 'mongodb+srv://...'
os.environ['MONGO_DB'] = 'secrets-27222'
os.environ['SQS_QUEUE_URL'] = 'https://sqs.us-east-1.amazonaws.com/...'

# Import y ejecutar
from rotation_master import lambda_handler

event = {
    'source': 'eventbridge',
    'triggered': True,
    'time': '2026-07-11T00:00:00Z'
}

result = lambda_handler(event, None)
print(json.dumps(json.loads(result['body']), indent=2))
"
```

### Test rotation_worker.py

```bash
cd /Users/delta27222/Desktop/tesis/tek-secrets/rotation/lambda

# Simular evento SQS (llama a la API real)
python3 -c "
import json, os

os.environ['API_BASE_URL'] = 'https://tu-app.onrender.com'
os.environ['ROTATION_API_TOKEN'] = 'tok_...'

from rotation_worker import lambda_handler

event = {'Records': [{
    'messageId': 'abc123',
    'body': json.dumps({'project_id': '507f1f77bcf86cd799439011'}),
    'receiptHandle': 'xyz789'
}]}

print(json.dumps(json.loads(lambda_handler(event, None)['body']), indent=2))
"
```

---

## Troubleshooting

### Worker: `API error HTTP 401`

**Causa**: Token inválido/expirado o sin scope `keys:rotate`.

**Solución**: Crear un nuevo token de sistema (UI → Organización → Tokens) y
actualizar `rotation_api_token` en `terraform.tfvars` → `terraform apply`.

### Worker: `API error HTTP 500` con "CSFLE"

**Causa**: La API en Render no tiene `MONGODB_CSFLE_MASTER_KEY` correcta (o no
coincide con la que encriptó las llaves existentes).

**Solución**: En Render, `MONGODB_CSFLE_MASTER_KEY` = el MISMO valor del `.env` local.

### Worker: `No se pudo conectar a la API`

**Causa**: `API_BASE_URL` incorrecta, o la API dormida (Render free).

**Solución**: Verificar la URL; el primer request puede tardar por el cold start
(el `HTTP_TIMEOUT=300s` lo cubre).

### Maestro: `pymongo.errors.ConnectionFailure`

**Causa**: `MONGODB_URL` inválida o IP no permitida en Atlas.

**Solución**: Validar URL; en Atlas whitelist `0.0.0.0/0`.

### SQS messages en DLQ

**Causa**: El Worker falló 3 veces (API caída, token inválido, etc.).

**Solución**: Ver logs CloudWatch, corregir, purgar DLQ.

---

## Próximas Versiones

- [ ] Soporte para AWS Secrets Manager (en lugar de MongoDB)
- [ ] Parallel reencryption (procesar múltiples envs en paralelo)
- [ ] Notification SNS si hay errores
- [ ] Metrics custom en CloudWatch

---

**Versión**: 1.0  
**Última actualización**: 2026-07-12  
**Estado**: Production Ready ✅
