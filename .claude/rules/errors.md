# Errores — FastAPI

## Patrón de excepciones

- Usar `HTTPException` de FastAPI para errores esperados con código HTTP explícito.
- Nunca devolver `{"error": "..."}` con status 200 — el status HTTP es el contrato.
- Los mensajes de error van en español (panel interno).

```python
from fastapi import HTTPException, status

# ✅ OBLIGATORIO
raise HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail="Proyecto no encontrado",
)

raise HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="No tienes permisos para acceder a este recurso",
)

# ❌ PROHIBIDO
return {"error": "Not found"}  # status 200 con error embebido
```

## Errores de validación

- Pydantic valida automáticamente el body de las requests — los `ValidationError` los convierte FastAPI en 422.
- No capturar `ValidationError` manualmente en los endpoints; dejar que FastAPI los maneje.

## Errores de autenticación

- JWT inválido o expirado → 401 con mensaje claro.
- Sin permisos para el recurso → 403 (no 404 si el recurso existe pero el usuario no tiene acceso).

## Handler global

- Los errores no capturados (500) deben loguearse con el logger del core **antes** de que FastAPI los devuelva.
- Nunca filtrar el traceback al cliente — mensaje genérico en 500.

```python
# core/exception_handlers.py
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Error interno del servidor"},
    )
```

## Seguridad

- Ningún mensaje de error imprime tokens, contraseñas ni URLs firmadas.
- Los detalles técnicos (stack traces, nombres de colección) no llegan al cliente.
