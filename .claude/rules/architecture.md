# Arquitectura — FastAPI + Service Layer

## Estructura de módulo

```
app/
  api/v1/endpoints/   # Routers FastAPI — solo routing y validación de entrada
  models/             # Pydantic schemas (request/response) + modelos MongoDB
  services/           # Lógica de negocio — única capa que toca la BD
  core/               # Config, auth (JWT), logging, security
  db/                 # Conexión Motor/MongoDB, helpers de colección
  main.py             # Inicialización FastAPI + routers
```

## Capas y responsabilidades

### Endpoints (`api/v1/endpoints/`)
- Solo enrutan y validan la entrada con Pydantic.
- Sin lógica de negocio, sin acceso directo a MongoDB.
- Llaman al servicio correspondiente y devuelven la respuesta.

```python
# ✅ OBLIGATORIO
@router.post("/projects/{project_id}/secrets", response_model=SecretResponse)
async def create_secret(
    project_id: str,
    body: CreateSecretRequest,
    current_user: User = Depends(get_current_user),
):
    return await secrets_service.create(project_id, body, current_user)

# ❌ PROHIBIDO — lógica de negocio en el endpoint
@router.post("/projects/{project_id}/secrets")
async def create_secret(project_id: str, body: CreateSecretRequest):
    db = get_db()
    await db.secrets.insert_one({...})
    await db.audit_logs.insert_one({...})
    return {"ok": True}
```

### Services (`services/`)
- Contienen toda la lógica de negocio.
- Son los únicos que acceden a las colecciones de MongoDB.
- Async/await siempre (Motor).
- Cada servicio corresponde a un recurso: `secrets_service.py`, `projects_service.py`, etc.

### Models (`models/`)
- **Pydantic schemas** para request/response (validación automática).
- **MongoDB document models** con `_id` como `PyObjectId` cuando aplique.
- Sin lógica de negocio en los modelos.

## Fronteras

- Los endpoints no conocen Motor ni las colecciones de MongoDB.
- Los servicios no conocen FastAPI (`Request`, `Response`, headers HTTP).
- El core (`core/`) provee config, auth y logging — accesible desde ambas capas.

## Logging (QuestDB)

- El middleware en `main.py` registra automáticamente las requests en QuestDB (`http_logs`).
- Los servicios pueden escribir eventos de negocio a `service_logs` vía el logger estructurado de `core/logging.py`.
- Nunca usar `print()` en producción; siempre el logger del core.
