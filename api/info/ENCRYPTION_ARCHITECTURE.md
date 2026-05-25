# 🔐 Arquitectura de Encriptación - Tek Secrets

**Documento técnico sobre el sistema de gestión de llaves de encriptación y flujos de datos.**

---

## 📋 Tabla de Contenidos

1. [Visión General](#visión-general)
2. [Bases de Datos](#bases-de-datos)
3. [Tablas/Colecciones](#tablascolecciones)
4. [Flujos Principales](#flujos-principales)
5. [Seguridad](#seguridad)
6. [Testing & Validación](#testing--validación)

---

## Visión General

Sistema de encriptación **con versionado automático** siguiendo NIST SP 800-57:

```
┌─────────────────────────────────────────────────────────────┐
│                    APLICACIÓN (FastAPI)                     │
│  POST /v1/projects/        POST /v1/environments/           │
│  POST /v1/keys/rotate      POST /v1/secrets/reencrypt       │
└──────────────────┬──────────────────────────────────────────┘
                   │
        ┌──────────┴──────────┐
        │                     │
        ▼                     ▼
    MongoDB              QuestDB
  (Datos)              (Auditoría)
```

**Roles:**
- **MongoDB** = almacena llaves + datos encriptados
- **QuestDB** = registra QUIÉN hizo QUÉ cuándo (inmutable)

---

## Bases de Datos

### MongoDB (`secrets-27222`)

**Propósito:** Almacenar datos operacionales (llaves, secretos, ambientes).

| Colección | Propósito | Acceso |
|-----------|-----------|--------|
| `encryption_keys` | Versiones actuales de llaves | Lectura/Escritura constante |
| `encryption_key_versions` | Historial de versiones | Auditoría |
| `environments` | Secretos (encriptados) | CRUD |
| `projects` | Proyectos | CRUD |

**Características:**
- Almacenamiento persistente
- Transacciones entre documentos
- Índices para búsqueda rápida

### QuestDB

**Propósito:** Time-series database para auditoría inmutable.

| Tabla | Propósito | Características |
|-------|-----------|-----------------|
| `encryption_key_audit` | Historial de eventos de llaves | Append-only, no actualizable |

**Características:**
- Append-only (no se puede borrar)
- Optimizado para queries por timestamp
- Perfecto para compliance/auditoría

---

## Tablas/Colecciones

### 1. `encryption_keys` (MongoDB)

**La bóveda de llaves activas.**

```javascript
{
  "_id": ObjectId("507f1f77bcf86cd799439011"),
  
  // Identificación
  "key_id": "key_proj_123_20260420_001",      // Único
  "project_id": "proj_123",                   // Null = global
  "version": 1,
  
  // Material sensible
  "key_material": "gAAAAABl8h7s_9XwK...",     // Fernet key en base64
  "algorithm": "Fernet",
  "key_size_bits": 256,
  
  // Ciclo de vida
  "status": "active",                         // pending|active|deprecated
  "is_primary": true,                         // Una sola activa por proyecto
  "created_at": ISODate("2026-04-20T00:55:00Z"),
  "activated_at": ISODate("2026-04-20T00:56:00Z"),
  "expires_at": ISODate("2027-04-20T00:55:00Z"),  // 1 año
  "rotated_at": null,
  "deactivated_at": null,
  
  // Trazabilidad
  "created_by": "user_456",
  "rotation_reason": "project_creation|scheduled|manual|compromised",
  "previous_key_id": null,
  
  // Metadata
  "metadata": {
    "environment": "production",
    "region": "us-east-1",
    "backup_location": null
  }
}
```

**Índices:**
```javascript
db.encryption_keys.createIndex({ key_id: 1 }, { unique: true })
db.encryption_keys.createIndex({ project_id: 1, is_primary: 1 })
db.encryption_keys.createIndex({ status: 1 })
db.encryption_keys.createIndex({ created_at: -1 })
```

**Ciclo de vida:**

```
Generación            Activación           Deprecación
    │                     │                     │
pending ───rotate()──→ active ───rotate()──→ deprecated
    │                     │                     │
  v1                    v1                    v1
  
En paralelo:
                      pending
                        │
                       v2 ───rotate()──→ active
```

---

### 2. `encryption_key_versions` (MongoDB)

**Historial de cada versión (para referencia).**

```javascript
{
  "_id": ObjectId("507f1f77bcf86cd799439012"),
  "key_id": "key_proj_123_20260420_001",
  "version_number": 1,
  "created_at": ISODate("2026-04-20T00:55:00Z"),
  "activated_at": ISODate("2026-04-20T00:56:00Z")
}
```

**Índices:**
```javascript
db.encryption_key_versions.createIndex({ key_id: 1 })
db.encryption_key_versions.createIndex({ version_number: 1 })
```

**Uso:** Auditoría interna, referencia histórica. NO se usa en encriptación.

---

### 3. `environments` (MongoDB)

**Secretos del usuario (encriptados).**

```javascript
{
  "_id": ObjectId("507f1f77bcf86cd799439013"),
  "project_id": "proj_123",
  "name": "Production",
  "slug": "prd",
  
  // SECRETOS ENCRIPTADOS
  "secrets": {
    "DB_PASSWORD": "gAAAAABl8h7t_K2pL...",    // Encriptado
    "API_KEY": "gAAAAABl8h7u_M3qM...",       // Encriptado
    "REDIS_URL": "gAAAAABl8h7v_N4rN..."      // Encriptado
  },
  
  // METADATA DE ENCRIPTACIÓN ← CRÍTICA
  "secrets_encryption": {
    "key_version": 1,
    "encrypted_with_key_id": "key_proj_123_20260420_001",
    "encrypted_at": ISODate("2026-04-20T01:00:00Z"),
    "requires_reencryption": false
  },
  
  // Credenciales integraciones (también encriptadas)
  "render_token": "gAAAAABl8h7w...",
  "render_server_id": "gAAAAABl8h7x...",
  "vercel_token": "gAAAAABl8h7y...",
  "vercel_project_id": "gAAAAABl8h7z...",
  "vercel_target": ["production"]
}
```

**Metadata crítica:**
- `encrypted_with_key_id` = **qué versión de llave usó**
- Permite desencriptar datos antiguos después de rotación

---

### 4. `encryption_key_audit` (QuestDB)

**Historial inmutable de eventos.**

```sql
CREATE TABLE IF NOT EXISTS encryption_key_audit (
  timestamp TIMESTAMP,           -- 2026-04-20T00:55:03Z
  action STRING,                 -- KEY_GENERATED, KEY_ROTATED, etc
  key_id STRING,                 -- key_proj_123_20260420_001
  project_id STRING,             -- proj_123
  actor_id STRING,               -- user_456
  ip_address STRING,             -- 'api'
  operation_result STRING,       -- success, failure
  details STRING                 -- JSON con metadatos
);
```

**Registro típico:**

```
timestamp                  | action          | key_id                              | project_id | actor_id  | ip_address | operation_result | details
2026-04-20T00:55:03.292Z   | KEY_GENERATED   | key_proj_123_20260420_001           | proj_123   | user_456  | api        | success          | {"version": 1, "reason": "project_creation"}
2026-04-20T00:56:00.755Z   | KEY_ROTATED     | key_proj_123_20260420_001           | proj_123   | user_456  | api        | success          | {"old_key_id": null, "new_key_id": "key_proj_123_20260420_001", "version": 1}
2026-04-20T10:30:15.123Z   | KEY_ROTATED     | key_proj_123_20261020_002           | proj_123   | scheduler | api        | success          | {"old_key_id": "key_proj_123_20260420_001", "new_key_id": "key_proj_123_20261010_002", "version": 2}
2026-04-20T11:45:22.456Z   | REENCRYPT_STARTED | (batch)                            | proj_123   | user_456  | api        | success          | {"total_environments": 3}
```

**Append-only:** Una vez escrito, NO se puede modificar (compliance).

---

## Flujos Principales

### Flujo 1: Crear Proyecto (con llave inicial)

```
Usuario
  │
  ▼
POST /v1/projects/
  │
  ├─ 1. Insertar proyecto en MongoDB
  │
  ├─ 2. Inicializar llave de encriptación
  │    ├─ EncryptionKeyManager.generate_key()
  │    │  └─ Crear documento en encryption_keys (status: pending)
  │    │  └─ Registrar en QuestDB: ACTION=KEY_GENERATED
  │    │
  │    └─ EncryptionKeyManager.rotate_key()
  │       ├─ Buscar llave pending
  │       ├─ Actualizar status: pending → active
  │       ├─ Registrar en QuestDB: ACTION=KEY_ROTATED
  │       └─ Resultado: Ya hay llave activa para encriptar
  │
  ├─ 3. Crear ambientes (dev, stg, prd)
  │    └─ create_environment() para cada uno
  │       ├─ Obtener llave activa de MongoDB
  │       ├─ Encriptar secretos con encrypt_secrets_new()
  │       ├─ Guardar en MongoDB con metadata
  │       └─ ✅ Exitoso
  │
  └─ 4. Retornar proyecto
```

**Datos después:**

MongoDB:
```
encryption_keys
└─ key_proj_123_20260420_001 (status: active, is_primary: true)

environments (3 documentos)
├─ Development
│  └─ secrets_encryption.encrypted_with_key_id = key_proj_123_20260420_001
├─ Staging
│  └─ secrets_encryption.encrypted_with_key_id = key_proj_123_20260420_001
└─ Production
   └─ secrets_encryption.encrypted_with_key_id = key_proj_123_20260420_001
```

QuestDB:
```
encryption_key_audit
├─ KEY_GENERATED (key_proj_123_20260420_001)
└─ KEY_ROTATED (key_proj_123_20260420_001)
```

---

### Flujo 2: Usuario Actualiza Secretos

```
Usuario en Frontend
  │
  ▼
PUT /v1/environments/{id}
Body: { "secrets": { "DB_PASS": "new-value" } }
  │
  ├─ 1. API recibe plaintext
  │    └─ DB_PASS = "new-value" (sin encriptar)
  │
  ├─ 2. encrypt_secrets_new()
  │    ├─ Obtener llave ACTIVA de MongoDB
  │    │  └─ Buscar: { project_id: "proj_123", is_primary: true }
  │    │  └─ Encuentra: key_proj_123_20260420_001
  │    │
  │    ├─ Fernet.encrypt("new-value") con esa llave
  │    │  └─ Resultado: "gAAAAABl8h7t_K2pL..."
  │    │
  │    └─ Crear metadata
  │       └─ encrypted_with_key_id: "key_proj_123_20260420_001"
  │
  ├─ 3. Guardar en MongoDB
  │    ├─ secrets: { DB_PASS: "gAAAAABl8h7t_K2pL..." }
  │    └─ secrets_encryption: {
  │         encrypted_with_key_id: "key_proj_123_20260420_001",
  │         encrypted_at: now
  │       }
  │
  └─ 4. Retornar al frontend (con secretos desencriptados)
```

**Antes/Después en MongoDB:**

```javascript
// ANTES
{
  "secrets": { "DB_PASS": "gAAAAABl8h7s..." },
  "secrets_encryption": {
    "encrypted_with_key_id": "key_proj_123_20260420_001"
  }
}

// DESPUÉS (usuario cambió a "new-value")
{
  "secrets": { "DB_PASS": "gAAAAABl8h7t_K2pL..." },  ← NUEVO
  "secrets_encryption": {
    "encrypted_with_key_id": "key_proj_123_20260420_001",
    "encrypted_at": ISODate("2026-04-20T10:30:00Z")
  }
}
```

---

### Flujo 3: Rotación Automática (90 días)

```
00:00 UTC cada día
  │
  ▼
APScheduler dispara rotate_encryption_keys_job()
  │
  ├─ 1. Para cada proyecto + global
  │
  ├─ 2. Obtener llave activa
  │    └─ Buscar: { project_id, is_primary: true }
  │
  ├─ 3. Verificar antigüedad
  │    └─ Si created_at > 90 días:
  │       ├─ ✅ Proceder a rotación
  │       └─ Si < 90 días:
  │          └─ ❌ Skip (no rotar aún)
  │
  ├─ 4. Generar nueva llave
  │    ├─ Fernet.generate_key()
  │    ├─ key_id: "key_proj_123_20261010_002"
  │    ├─ Insertar en encryption_keys (status: pending)
  │    └─ Registrar en QuestDB: ACTION=KEY_GENERATED
  │
  ├─ 5. Rotar
  │    ├─ Nueva: pending → active (is_primary: true)
  │    ├─ Antigua: active → deprecated (is_primary: false)
  │    └─ Registrar en QuestDB: ACTION=KEY_ROTATED
  │
  └─ ✅ Completado
```

**Resultado en MongoDB:**

```javascript
// ANTIGUA (ahora deprecated)
{
  "key_id": "key_proj_123_20260420_001",
  "status": "deprecated",      // ← CAMBIÓ
  "is_primary": false          // ← CAMBIÓ
}

// NUEVA (ahora activa)
{
  "key_id": "key_proj_123_20261010_002",
  "status": "active",          // ← NUEVA
  "is_primary": true           // ← NUEVA
}
```

**Consecuencia:**
- Ambientes antiguos → aún desencriptables con v1 (metadata lo guarda)
- Nuevos ambientes → encriptados con v2 automáticamente

---

### Flujo 4: Desencriptación (GET /v1/environments/{id})

```
Usuario solicita ver secretos
  │
  ▼
GET /v1/environments/{id}
  │
  ├─ 1. Obtener documento de MongoDB
  │    └─ Encuentra environment con secrets encriptados
  │
  ├─ 2. decrypt_secrets_new()
  │
  │    ├─ Leer metadata: encrypted_with_key_id = "key_proj_123_20260420_001"
  │    │
  │    ├─ Buscar esa llave en MongoDB
  │    │  └─ Encuentra key_material (aunque esté deprecated)
  │    │
  │    ├─ Fernet.decrypt() con key_material
  │    │  ├─ Input:  "gAAAAABl8h7t_K2pL..."
  │    │  └─ Output: "new-value"
  │    │
  │    └─ Si no hay metadata:
  │       └─ Fallback: usar llave ACTIVA (para datos muy antiguos)
  │
  └─ 3. Retornar plaintext al frontend
```

**Flujo visual:**

```
GET /v1/environments/prod-id
  │
  ▼
MongoDB busca documento
  ├─ secrets.DB_PASS = "gAAAAABl8h7t_K2pL..."  ← ENCRIPTADO
  └─ secrets_encryption.encrypted_with_key_id = "key_proj_123_20260420_001"
  
  ▼
Buscar llave por key_id
  ├─ MongoDB → encryption_keys
  └─ Encuentra: key_material = "gAAAAABl8h7s_9XwK..." (Fernet key)

  ▼
Desencriptar
  ├─ Fernet(key_material).decrypt("gAAAAABl8h7t_K2pL...")
  └─ Resultado: "new-value"

  ▼
Retornar
  └─ { secrets: { DB_PASS: "new-value" } }
```

---

### Flujo 5: Re-encriptación Batch

**POST /v1/secrets/reencrypt** - Re-encriptar TODOS los ambientes con nueva llave.

```
Usuario dispara manualmente (o después de migración KMS)
  │
  ▼
POST /v1/secrets/reencrypt
  │
  ├─ 1. Obtener todos los ambientes del proyecto
  │    └─ Query: { project_id: "proj_123" }
  │
  ├─ 2. Para CADA ambiente
  │    │
  │    ├─ a) Desencriptar con llave vieja
  │    │    └─ decrypt_secrets_new() usando metadata histórica
  │    │    └─ Resultado: plaintext
  │    │
  │    ├─ b) Encriptar con llave NUEVA (activa)
  │    │    └─ encrypt_secrets_new()
  │    │    └─ Resultado: ciphertext + metadata actualizada
  │    │
  │    └─ c) Actualizar MongoDB
  │       ├─ secrets: datos re-encriptados
  │       └─ secrets_encryption.encrypted_with_key_id: NUEVA
  │
  ├─ 3. Registrar en QuestDB
  │    └─ ACTION=REENCRYPT_COMPLETED
  │       details: { total: 3, success: 3, failed: 0 }
  │
  └─ ✅ Completado
```

**MongoDB antes:**

```javascript
{
  "_id": ObjectId("...prod..."),
  "secrets": { "DB_PASS": "gAAAAABl8h7t..." },  // Encriptado con v1
  "secrets_encryption": {
    "encrypted_with_key_id": "key_proj_123_20260420_001",  // v1
    "requires_reencryption": true  // Marcado para re-encriptar
  }
}
```

**MongoDB después:**

```javascript
{
  "_id": ObjectId("...prod..."),
  "secrets": { "DB_PASS": "gAAAAABl8h8u..." },  // Encriptado con v2 (NUEVO)
  "secrets_encryption": {
    "encrypted_with_key_id": "key_proj_123_20261010_002",  // v2 (CAMBIÓ)
    "encrypted_at": ISODate("2026-04-20T11:45:22Z"),
    "requires_reencryption": false  // Ya re-encriptado
  }
}
```

---

## Seguridad

### 🔐 Qué se encripta

```
✅ Encriptado
├─ secrets (DB_PASS, API_KEY, etc)
├─ render_token
├─ render_server_id
├─ vercel_token
└─ vercel_project_id

❌ NO encriptado (pública)
├─ key_id
├─ project_id
├─ version
├─ status
└─ created_at (timestamps)
```

### 🚫 Qué NUNCA se expone

```
NUNCA en API responses:
❌ key_material          (la llave real)
❌ plaintext secrets     (en lista de ambientes)

Retornar SIEMPRE:
✅ key_id               (para auditoría)
✅ status               (para estado)
✅ *** (asteriscos)     (en listados)
```

### ⚠️ Riesgos actuales

```
RIESGO ALTO:
├─ key_material en MongoDB plaintext
├─ Si BD se compromete → todas las llaves expostas
└─ Solución: Usar AWS KMS para guardar key_material encriptado

MITIGACIONES:
├─ QuestDB append-only (no se puede borrar auditoría)
├─ Metadata versionada (desencriptar datos antiguos siempre posible)
├─ Rotación automática (llaves antiguas se deprecan)
└─ Auditoría completa (QUIÉN accedió CUÁNDO)
```

---

## Testing & Validación

### ✅ Verificar Encriptación Funciona

```bash
# 1. Crear proyecto
curl -X POST http://localhost:8000/v1/projects/ \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"name": "Test Project"}'
# Retorna: project_id

# 2. Verificar llave creada en MongoDB
mongosh
> db.encryption_keys.findOne({ project_id: "<project_id>" })
{
  key_id: "key_<project_id>_...",
  status: "active",
  is_primary: true,
  key_material: "gAAAAAB..."  ← GUARDADO (⚠️ plaintext)
}

# 3. Verificar auditoría en QuestDB
curl 'http://52.91.246.92:9000/exec?query=SELECT%20*%20FROM%20encryption_key_audit'
[
  { action: "KEY_GENERATED", key_id: "key_<project_id>_..." },
  { action: "KEY_ROTATED", key_id: "key_<project_id>_..." }
]
```

### ✅ Verificar Desencriptación

```bash
# 1. Crear environment
curl -X POST http://localhost:8000/v1/environments/ \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"project_id": "<id>", "name": "Prod", "secrets": {"DB_PASS": "secret123"}}'

# 2. Verificar en MongoDB (encriptado)
mongosh
> db.environments.findOne({ name: "Prod" })
{
  secrets: {
    DB_PASS: "gAAAAABl8h7t..."  ← ENCRIPTADO
  },
  secrets_encryption: {
    encrypted_with_key_id: "key_proj_123_20260420_001"
  }
}

# 3. GET environment (desencripta automáticamente)
curl http://localhost:8000/v1/environments/<env_id>
{
  name: "Prod",
  secrets: {
    DB_PASS: "secret123"  ← PLAINTEXT ✅
  }
}
```

### ✅ Simular Rotación (sin esperar 90 días)

```bash
# 1. Modificar timestamp de llave en MongoDB
mongosh
> db.encryption_keys.updateOne(
    { key_id: "key_proj_123_20260420_001" },
    { $set: { created_at: new Date(Date.now() - 90*24*60*60*1000) } }
  )

# 2. Disparar rotación manual
curl -X POST http://localhost:8000/v1/keys/rotate \
  -H "Authorization: Bearer $TOKEN"

# 3. Verificar nueva llave
mongosh
> db.encryption_keys.find({ project_id: "<project_id>" })
[
  { key_id: "key_..._001", status: "deprecated", is_primary: false },
  { key_id: "key_..._002", status: "active", is_primary: true }
]

# 4. Ambiente antiguo aún funciona
curl http://localhost:8000/v1/environments/<env_id>
# Retorna secretos desencriptados ✅ (usa v1)
```

### ✅ Verificar Re-encriptación

```bash
# 1. Re-encriptar batch
curl -X POST http://localhost:8000/v1/secrets/reencrypt \
  -H "Authorization: Bearer $TOKEN"
# Retorna: { success: true, reencrypted: 3 }

# 2. Verificar que cambió metadata
mongosh
> db.environments.findOne({ name: "Prod" })
{
  secrets_encryption: {
    encrypted_with_key_id: "key_..._002"  ← CAMBIÓ A v2
  }
}

# 3. Ambiente sigue siendo accesible
curl http://localhost:8000/v1/environments/<env_id>
# Retorna secretos desencriptados ✅ (ahora usa v2)
```

### ✅ Auditoría en QuestDB

```bash
# Ver todos los eventos de llave
curl 'http://52.91.246.92:9000/exec' \
  --data-urlencode "query=SELECT timestamp, action, key_id, operation_result FROM encryption_key_audit ORDER BY timestamp DESC LIMIT 20"

# Resultado:
timestamp                  | action                | key_id                      | operation_result
2026-04-20T11:45:22.456Z   | REENCRYPT_COMPLETED   | (batch)                     | success
2026-04-20T10:30:15.123Z   | KEY_ROTATED           | key_proj_123_20261010_002   | success
2026-04-20T10:30:10.000Z   | KEY_GENERATED         | key_proj_123_20261010_002   | success
2026-04-20T01:00:00.000Z   | KEY_GENERATED         | key_proj_123_20260420_001   | success
```

---

## Resumen de Flujos

| Operación | Dónde | MongoDB | QuestDB | Resultado |
|-----------|-------|---------|---------|-----------|
| **Crear Proyecto** | API | Crea key v1 + 3 envs | KEY_GENERATED, KEY_ROTATED | Llave activa lista |
| **Usuario actualiza secretos** | API | Encripta + metadata | (nada) | Secretos guardados |
| **Usuario obtiene secretos** | API | Lee + desencripta | (nada) | Plaintext al frontend |
| **Rotación automática** | Scheduler | Genera v2, marca v1 deprecated | KEY_GENERATED, KEY_ROTATED | Nueva llave activa |
| **Re-encriptación batch** | API | Todos los envs con v2 | REENCRYPT_COMPLETED | Datos migrados a v2 |

---

## Próximos Pasos

1. ✅ Encriptación dinámica implementada
2. ✅ Versionado de llaves funcionando
3. ✅ Auditoría en QuestDB
4. 🔜 **AWS KMS** (guardar key_material encriptado)
5. 🔜 **Unit tests** (encrypt/decrypt)
6. 🔜 **Integration tests** (flujos completos)
7. 🔜 **Load testing** (rendimiento con rotaciones)

---

**Documento técnico v1.0**  
*Para más detalles: ver `IMPLEMENTATION_GUIDE.md`, `QUICK_START.md`*
