# Estándares de Python

## Tipado

- **Type hints obligatorios** en todos los parámetros y retornos de funciones públicas.
- Sin `Any` de `typing` salvo cuando es estrictamente necesario y documentado.
- Usar `Optional[T]` o `T | None` (Python 3.10+) para valores nullable.

```python
# ✅ OBLIGATORIO
async def get_secret(secret_id: str, user_id: str) -> SecretResponse | None:
    ...

# ❌ PROHIBIDO
async def get_secret(secret_id, user_id):
    ...
```

## Manejo de errores

- Capturar excepciones específicas, nunca `except Exception` sin re-lanzar o loguear.
- En bloques `except`, siempre loguear con `logger.error(..., exc_info=True)` antes de manejar.

```python
# ✅
try:
    result = await db.secrets.find_one({"_id": ObjectId(secret_id)})
except Exception as e:
    logger.error("Error fetching secret", exc_info=True)
    raise HTTPException(status_code=500, detail="Error interno")
```

## Async/Await

- Toda función que toca I/O (BD, HTTP externo, S3) debe ser `async def`.
- Sin `asyncio.run()` dentro de funciones async — solo en el punto de entrada.
- Usar `asyncio.gather()` para operaciones paralelas independientes.

```python
# ✅ Operaciones independientes en paralelo
project, members = await asyncio.gather(
    projects_service.get(project_id),
    memberships_service.get_members(project_id),
)
```

## Pydantic

- Modelos de request/response siempre heredan de `BaseModel`.
- Usar `model_validator` o `field_validator` para validación cross-field.
- Sin campos con `Any` en los modelos expuestos al cliente.

## Configuración

- Variables de entorno solo se leen en `core/config.py` (objeto `settings`).
- Ningún endpoint ni servicio accede a `os.environ` directamente.
