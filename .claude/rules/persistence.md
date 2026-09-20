# Persistencia — Motor + MongoDB

## Cliente

Usar el cliente Motor asíncrono inyectado desde `app/db/`. Nunca crear conexiones directas en endpoints o servicios.

```python
# db/database.py — punto único de conexión
from motor.motor_asyncio import AsyncIOMotorClient

client: AsyncIOMotorClient = None

def get_database():
    return client[settings.MONGO_DB]
```

```python
# services/secrets_service.py
from app.db.database import get_database

async def get_secrets(project_id: str, env_id: str):
    db = get_database()
    cursor = db.secrets.find({"project_id": project_id, "environment_id": env_id})
    return await cursor.to_list(length=None)
```

## Reglas

1. **Async siempre.** Toda operación a MongoDB usa `await`. Sin `find_one()` bloqueante — siempre `await collection.find_one()`.
2. **Solo los servicios acceden a la BD.** Los endpoints llaman al servicio; nunca `get_database()` en un endpoint.
3. **Sin N+1.** No ejecutar una query por cada elemento de una lista. Usar `$in` con una lista de IDs y agrupar en memoria.

```python
# ❌ PROHIBIDO — N+1
for secret in secrets:
    secret["created_by"] = await db.users.find_one({"_id": secret["user_id"]})

# ✅ OBLIGATORIO
user_ids = [s["user_id"] for s in secrets]
users = await db.users.find({"_id": {"$in": user_ids}}).to_list(None)
users_map = {u["_id"]: u for u in users}
for secret in secrets:
    secret["created_by"] = users_map.get(secret["user_id"])
```

4. **Proyecciones explícitas** cuando no se necesitan todos los campos.

```python
# ✅ Solo traer lo necesario
await db.secrets.find_one(
    {"_id": ObjectId(secret_id)},
    {"key": 1, "environment_id": 1, "project_id": 1}
)
```

5. **ObjectId** se convierte a string antes de devolver al cliente. Los modelos Pydantic manejan `PyObjectId` para la serialización.

6. **Escrituras múltiples consistentes:** si un caso de uso escribe en varias colecciones (ej: crear secreto + escribir audit log), ambas se ejecutan en el mismo bloque try/except. El rollback manual es responsabilidad del servicio si MongoDB no usa transacciones (replica set requerido para transacciones ACID).

## Cifrado de valores

- Los valores de secretos se cifran antes de guardar en MongoDB (ver `core/security.py`).
- Nunca guardar valores en plaintext en la BD.
- El cifrado/descifrado ocurre **solo en el servicio**, nunca en el endpoint ni en el modelo.
