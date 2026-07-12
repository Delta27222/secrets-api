# 🌱 Scripts de Seed - Tek Secrets API

Documentación completa para ejecutar los scripts de inicialización de la base de datos.

> 📖 **API en producción (Swagger docs):** https://secrets-api-gdl3.onrender.com/docs

---

## ▶️ Correr el API localmente

Si todavía no levantaste el backend, ejecuta estos pasos:

```bash
cd /Users/delta27222/Desktop/tesis/tek-secrets/api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
.venv/bin/fastapi dev app/main.py
```

## ▶️ Empezar desde cero (seed)

**Destructivo:** borra datos de prueba en MongoDB y crea org + **Proyecto Inicial** + llave v1 + 3 ambientes con secretos cifrados. Requiere usuario `angelgabriel.hernandez@gmail.com` en `users` (ver [Requisitos](#-requisitos-previos) más abajo).

```bash
cd /Users/delta27222/Desktop/tesis/tek-secrets/api && source .venv/bin/activate && python -m scripts.seed_full_project
```

## ▶️ Test de rotación de llaves

Simula rotación (v1 → v2), comprueba que los secretos viejos siguen desencriptándose y re-cifra todos los ambientes del **Proyecto Inicial**. Ejecutar **después** del seed (no requiere API levantada).

```bash
cd /Users/delta27222/Desktop/tesis/tek-secrets/api && source .venv/bin/activate && python -m scripts.test_key_rotation
```

## ▶️ Flujo completo (desde cero + rotación)

```bash
cd /Users/delta27222/Desktop/tesis/tek-secrets/api && source .venv/bin/activate && python -m scripts.seed_full_project && python -m scripts.test_key_rotation
```

## ▶️ Migración CSFLE (`key_material`)

Encripta en MongoDB el campo `key_material` de `encryption_keys` que aún esté en plaintext (requiere `MONGODB_CSFLE_MASTER_KEY` en `.env` y `pymongocrypt` instalado).

```bash
cd /Users/delta27222/Desktop/tesis/tek-secrets/api && source .venv/bin/activate && python -m scripts.migrate_csfle
```

---

## 📋 Requisitos Previos

Antes de correr cualquier seed, asegúrate de que:

1. **Virtual environment activado:**
   ```bash
   cd /Users/delta27222/Desktop/tesis/tek-secrets/api
   source .venv/bin/activate
   ```

2. **MongoDB corriendo:**
   - Local: `mongosh` disponible
   - O remoto: `MONGODB_URL` en `.env` correcto

3. **QuestDB corriendo (opcional pero recomendado):**
   - Para auditoría: EC2_INSTANCE_IP y EC2_INSTANCE_PORT en `.env`

4. **Variables de entorno configuradas:**
   - `.env` con `MONGODB_URL`, `MONGO_DB`, `EC2_INSTANCE_IP`, `EC2_INSTANCE_PORT`

---

## 🌱 Seeds Disponibles

### 1. `seed_full_project.py`

**¿Qué hace?**
- ✅ Verifica que el usuario `angelgabriel.hernandez@gmail.com` exista
- ✅ Limpia todas las tablas (encryption_keys, environments, organizations, projects, etc.)
- ✅ Crea organización con timestamp: `"Organización Inicial - {HH:MM am/pm, DD de Mes}"`
- ✅ Crea proyecto con timestamp: `"Proyecto Inicial - {HH:MM am/pm, DD de Mes}"`
- ✅ Inicializa llave de encriptación para el proyecto
- ✅ Crea 3 ambientes: Development, Staging, Production
- ✅ Agrega secretos de prueba ENCRIPTADOS a cada ambiente:
  - **dev:** DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, API_KEY, REDIS_URL
  - **stg:** (equivalentes staging)
  - **prd:** (equivalentes producción)

**Cuándo usar:**
- Para preparar un ambiente completo de prueba
- Verificar que encriptación funciona end-to-end
- Testing de rotación de llaves

**Cómo ejecutar:**
```bash
cd /Users/delta27222/Desktop/tesis/tek-secrets/api
source .venv/bin/activate
python -m scripts.seed_full_project
```

**Pasos antes de ejecutar:**

1. **Asegúrate de que el usuario existe en la BD:**
   ```bash
   mongosh
   use secrets-27222
   db.users.findOne({email: "angelgabriel.hernandez@gmail.com"})
   ```
   
   Si NO existe, créalo:
   ```bash
   db.users.insertOne({
     email: "angelgabriel.hernandez@gmail.com",
     username: "angelgabriel",
     displayName: "Ángel Gabriel Hernández",
     provider: "github",
     provider_id: "angelgabriel-xxx"
   })
   ```

2. **Ejecuta el seed:**
   ```bash
   python -m scripts.seed_full_project
   ```

**Output esperado:**
```
============================================================
🌱 SEED - PROYECTO INICIAL CON ENCRIPTACIÓN
============================================================

⏰ Timestamp: 10:45 pm, 19 de Abril

🔐 Verificando usuario requerido...
✅ Usuario encontrado: angelgabriel.hernandez@gmail.com

⚠️  Limpiando base de datos...
   ✅ encryption_key_versions: 2 documentos eliminados
   ✅ encryption_keys: 1 documentos eliminados
   ... (más colecciones)

🏢 Preparando organización...
✅ Organización creada: Organización Inicial - 10:45 pm, 19 de Abril

👥 Vinculando usuario con organización...
✅ Usuario vinculado: angelgabriel.hernandez@gmail.com (rol: owner)

🔑 Creando proyecto con encriptación automática...
✅ Proyecto creado: Proyecto Inicial - 10:45 pm, 19 de Abril
✅ Llave de encriptación creada: key_69e593faab4dc859d3834d53_20260420_001

📦 Ambientes creados automáticamente:
✅ Development (slug: dev)
✅ Staging (slug: stg)
✅ Production (slug: prd)

🔐 Agregando secretos de prueba...
✅ Development: 6 secretos encriptados
✅ Staging: 6 secretos encriptados
✅ Production: 6 secretos encriptados

============================================================
✅ SEED COMPLETADO CON ÉXITO
============================================================
```

**Verifica en MongoDB:**
```bash
mongosh
use secrets-27222

# Ver organización
db.organizations.findOne({name: /Organización Inicial/})

# Ver proyecto
db.projects.findOne({name: /Proyecto Inicial/})

# Ver llaves
db.encryption_keys.find({is_primary: true})

# Ver ambientes con secretos encriptados
db.environments.findOne({slug: "dev"})
```

---

### 2. `test_key_rotation.py`

**¿Qué hace?**
- ✅ Obtiene el proyecto "Proyecto Inicial" (creado por `seed_full_project.py`)
- ✅ Muestra llaves actuales
- ✅ Simula paso de 91 días (modificando timestamp)
- ✅ Dispara rotación manual (v1 → v2)
- ✅ Verifica que datos antiguos se desencriptan con v1
- ✅ Re-encripta todos los ambientes con v2
- ✅ Consulta auditoría en QuestDB
- ✅ Muestra resumen final con versiones reales

**Cuándo usar:**
- Para verificar que rotación de llaves funciona
- Probar que datos encriptados con v1 siguen siendo accesibles
- Validar re-encriptación batch

**Cómo ejecutar:**

1. **Primero ejecuta el seed completo:**
   ```bash
   python -m scripts.seed_full_project
   ```

2. **Luego corre el test:**
   ```bash
   python -m scripts.test_key_rotation
   ```

**Output esperado:**
```
════════════════════════════════════════════════════════════════════════════════════════════════════
🔐 TEST: ROTACIÓN DE LLAVES DE ENCRIPTACIÓN
════════════════════════════════════════════════════════════════════════════════════════════════════

1️⃣  Obtener proyecto
✅ Proyecto encontrado: Proyecto Inicial - 10:45 pm, 19 de Abril
   ID: 69e593faab4dc859d3834d53

2️⃣  Llaves actuales
📦 Llaves (1 total):
────────────────────────────────────────────────────────────────────────────────────────────────────
🟢	v1	active    	key_69e593faab4dc859d3834d53_20260420_001	PRIMARY
────────────────────────────────────────────────────────────────────────────────────────────────────

3️⃣  Ambientes
🌍 Ambientes (3 total):
────────────────────────────────────────────────────────────────────────────────────────────────────
  Development	v1	key_69e593faab4dc859d3834d53_20260420_001	6 secretos
  Staging	v1	key_69e593faab4dc859d3834d53_20260420_001	6 secretos
  Production	v1	key_69e593faab4dc859d3834d53_20260420_001	6 secretos
────────────────────────────────────────────────────────────────────────────────────────────────────

4️⃣  Simular paso de tiempo
⏳ Simulando paso de tiempo
────────────────────────────────────────────────────────────────────────────────────────────────────
  ✅ Llave actual: -91 días
────────────────────────────────────────────────────────────────────────────────────────────────────

5️⃣  Rotación de llave
🔄 Rotación de llave
────────────────────────────────────────────────────────────────────────────────────────────────────
  ✅ Generada: v2
  ✅ Activada: key_69e593faab4dc859d3834d53_20260420_002
────────────────────────────────────────────────────────────────────────────────────────────────────

6️⃣  Llaves después de rotación
📦 Llaves (2 total):
────────────────────────────────────────────────────────────────────────────────────────────────────
🟢	v2	active    	key_69e593faab4dc859d3834d53_20260420_002	PRIMARY
🔴	v1	deprecated	key_69e593faab4dc859d3834d53_20260420_001	
────────────────────────────────────────────────────────────────────────────────────────────────────

7️⃣  Desencriptación con llave antigua
🔐 Desencriptación (verificar compatibilidad)
────────────────────────────────────────────────────────────────────────────────────────────────────
  ✅ Development	v1	key_69e593faab4dc859d3834d53_20260420_001	6 secretos
────────────────────────────────────────────────────────────────────────────────────────────────────

8️⃣  Re-encriptación batch
♻️  Re-encriptando todos los ambientes...
────────────────────────────────────────────────────────────────────────────────────────────────────
  ✅ Development	v2	key_69e593faab4dc859d3834d53_20260420_002
  ✅ Staging	v2	key_69e593faab4dc859d3834d53_20260420_002
  ✅ Production	v2	key_69e593faab4dc859d3834d53_20260420_002
────────────────────────────────────────────────────────────────────────────────────────────────────
✅ Listo: 3/3 re-encriptados

9️⃣  Estado final
🌍 Ambientes (3 total):
────────────────────────────────────────────────────────────────────────────────────────────────────
  Development	v2	key_69e593faab4dc859d3834d53_20260420_002	6 secretos
  Staging	v2	key_69e593faab4dc859d3834d53_20260420_002	6 secretos
  Production	v2	key_69e593faab4dc859d3834d53_20260420_002	6 secretos
────────────────────────────────────────────────────────────────────────────────────────────────────

🔟 Auditoría
📊 Auditoría de eventos (QuestDB)
────────────────────────────────────────────────────────────────────────────────────────────────────
  ✅	KEY_GENERATED        	key_69e593faab4dc859d3834d53_20260420_002
  ✅	KEY_ROTATED          	key_69e593faab4dc859d3834d53_20260420_002
────────────────────────────────────────────────────────────────────────────────────────────────────

════════════════════════════════════════════════════════════════════════════════════════════════════
✅ TEST COMPLETADO
════════════════════════════════════════════════════════════════════════════════════════════════════

Resultado: ✅ Sistema funcionando correctamente
  ✓ Llaves rotadas (v1 → v2)
  ✓ Datos antiguos desencriptables
  ✓ Re-encriptación exitosa
  ✓ Auditoría registrada
```

**Verifica en MongoDB:**
```bash
mongosh
use secrets-27222

# Ver todas las llaves (incluyendo deprecated)
db.encryption_keys.find({})

# Ver ambientes actualizados con v2
db.environments.findOne({slug: "dev"})
```

---

## 🚀 Flujo Completo: De Cero a Testing

```bash
# 1. Activar virtual environment
cd /Users/delta27222/Desktop/tesis/tek-secrets/api
source .venv/bin/activate

# 2. Asegurarse de que usuario existe (ver paso 1 de seed_full_project.py)
mongosh
use secrets-27222
db.users.findOne({email: "angelgabriel.hernandez@gmail.com"})
# Si no existe, crear manualmente
exit

# 3. Correr seed completo (crea proyecto + ambientes + secretos encriptados + llave)
python -m scripts.seed_full_project

# 4. Verificar en MongoDB que proyecto + ambientes + secretos existen
mongosh
use secrets-27222
db.projects.findOne({name: /Proyecto Inicial/})
exit

# 5. Correr test de rotación (v1 → v2 + re-encriptación)
python -m scripts.test_key_rotation

# ✅ Listo! Sistema funcionando
```

---

## ✅ Checklist de Verificación

Después de correr los seeds:

- [ ] **Proyecto existe en MongoDB:**
  ```bash
  mongosh && db.projects.countDocuments() > 0
  ```

- [ ] **Llave activa creada:**
  ```bash
  db.encryption_keys.countDocuments({is_primary: true}) === 1
  ```

- [ ] **3 Ambientes creados:**
  ```bash
  db.environments.countDocuments() === 3
  ```

- [ ] **Secretos encriptados (no plaintext):**
  ```bash
  db.environments.findOne({slug: "dev"}).secrets.DB_HOST  # No debe ser "localhost"
  ```

- [ ] **Metadata de encriptación presente:**
  ```bash
  db.environments.findOne({}).secrets_encryption.encrypted_with_key_id  # Debe existir
  ```

- [ ] **Test de rotación completó:**
  ```bash
  # Último output debe mostrar: Llaves rotadas (v1 → v2)
  ```

---

## 🐛 Troubleshooting

| Error | Solución |
|-------|----------|
| `usuario no encontrado` | Crear usuario manualmente (ver seed_full_project.py) |
| `No active key for project` | Correr `seed_full_project.py` primero |
| `QuestDB retornó 400` | EC2_INSTANCE_IP/PORT incorrectos en `.env` |
| `DECRYPTION_ERROR` | Llave fue eliminada; re-encriptar batch |
| `Failed to fetch` | MongoDB no conecta; verificar MONGODB_URL en `.env` |

---

## 📝 Notas

- Los seeds son **idempotentes**: correr múltiples veces no genera duplicados (excepto timestamps únicos)
- La limpieza en `seed_full_project.py` es **destructiva**: borra todo de las colecciones
- Los secretos se almacenan **encriptados**: no verás valores plaintext en MongoDB
- Las llaves se versionan automáticamente: v1, v2, v3, etc.
- La auditoría se registra en QuestDB (opcional pero recomendado)
