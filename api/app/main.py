import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.logging import LoggingMiddleware
from .core.system_logging import setup_system_logging, shutdown_system_logging
from .core.csfle import init_csfle, close_csfle
from .api.v1.api import router as api_router
from .db.mongodb_utils import close_mongo_connection, connect_to_mongo, create_indexes

logger = logging.getLogger(__name__)

app = FastAPI(title='Tek Secrets')
origins = [
    "*"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(LoggingMiddleware)

@app.on_event("startup")
async def on_startup():
    """Ejecuta al iniciar la aplicación."""
    # Antes que nada: así los fallos del propio arranque (Mongo, CSFLE) quedan
    # registrados en lugar de perderse en el stdout del contenedor.
    setup_system_logging()
    await connect_to_mongo()
    await create_indexes()
    init_csfle()
    logger.info("Aplicación iniciada. CSFLE + índices de base de datos creados.")

@app.on_event("shutdown")
async def on_shutdown():
    """Ejecuta al cerrar la aplicación."""
    close_csfle()
    await close_mongo_connection()
    # Drena la cola pendiente antes de morir.
    shutdown_system_logging()
app.include_router(api_router, prefix='/v1')
