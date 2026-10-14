"""Raíz de composición: el único módulo que sabe que existen todas las capas.

Aquí se cablea todo y en ningún otro sitio, así que importar un router, un
servicio o un repositorio nunca arrastra el framework, y cada uno se puede
testear por separado. El servicio arranca con::

    uvicorn app.main:create_app --factory

Se usa la fábrica en vez de una instancia a nivel de módulo para que importar
este módulo no necesite entorno alguno: la configuración se resuelve cuando
arranca el proceso, que es donde un ``SERVICE_API_TOKEN`` ausente es fatal
(SPEC 2.5).
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.api.auth import BearerAuthMiddleware
from app.api.exception_handlers import register_exception_handlers
from app.api.middleware import (
    CORS_METHODS,
    AccessLogMiddleware,
    BodySizeLimitMiddleware,
    ContentTypeMiddleware,
    RequestIdMiddleware,
)
from app.api.routers import health, texts
from app.api.schemas import publish
from app.config import Settings, get_settings
from app.repositories.mongodb import MongoConnection
from app.repositories.mongodb_text_repository import MongoTextRepository
from app.services.text_service import TextService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Prepara MongoDB al subir y lo libera al bajar.

    Una base de datos que no contesta se registra, no se propaga: el servicio
    sigue en pie y ``/readyz`` reporta la caída, que es lo que el orquestador
    necesita para sacar la instancia de rotación sin un bucle de reinicio
    (SPEC 5.5).

    El apagado tampoco puede fallar. Uvicorn ya terminó las peticiones en vuelo
    antes de llegar aquí: lo que queda es soltar el pool, y un error al hacerlo
    se registra en vez de convertir una parada limpia en una salida con error.
    """
    connection: MongoConnection = app.state.mongo
    await connection.start()
    # La colección sólo existe una vez construido el cliente, así que el servicio
    # se cablea aquí: una conexión, un repositorio, un pool (SPEC 2.1).
    app.state.text_service = TextService(MongoTextRepository(connection.texts()))
    try:
        yield
    finally:
        logger.info("Shutting down: closing the MongoDB connection.")
        shutdown_started = perf_counter()
        try:
            await connection.close()
        except Exception:
            # El apagado nunca debe romper el proceso: se registra y se sigue.
            logger.exception("The MongoDB connection could not be closed cleanly.")
        else:
            logger.info(
                "Shutdown finished in %.1f ms.",
                (perf_counter() - shutdown_started) * 1000,
            )


def create_app(
    settings: Settings | None = None, connection: MongoConnection | None = None
) -> FastAPI:
    """Construye la aplicación.

    Args:
        settings: Configuración con la que correr. Se lee del entorno cuando se
            omite, que es el camino que sigue el proceso y la razón de que un
            token ausente detenga el arranque en vez de dejar un servicio sin
            protección.
        connection: La conexión a MongoDB a usar. Se construye a partir de
            ``settings`` cuando se omite; los tests pasan una cuyo cliente es un
            doble.

    Returns:
        La app con sus manejadores de error, sus sondas y su autenticación
        instalados. Los routers restantes los añaden las tareas que definen los
        endpoints.
    """
    resolved = settings if settings is not None else get_settings()
    mongo = connection if connection is not None else MongoConnection(resolved)

    app = FastAPI(title=resolved.app_name, lifespan=lifespan)
    app.state.settings = resolved
    app.state.mongo = mongo
    # Las sondas sólo preguntan a un callable, nunca a la base de datos, así que
    # las rutas de app/api no saben nada de pymongo (SPEC 2.1).
    app.state.readiness_check = mongo.is_available
    app.include_router(health.router)
    app.include_router(texts.router)
    register_exception_handlers(app)
    publish(app)
    # Starlette ejecuta el middleware añadido más recientemente como el más
    # externo, así que este bloque se lee al revés: añadir aquí significa
    # ejecutarse el último. El orden de ejecución resultante es el que pide
    # SPEC 3.3 -- 401 antes que 415, 415 antes que 413, y ambos antes que el 400
    # que produciría el parseo del body.
    app.add_middleware(BodySizeLimitMiddleware, settings=resolved)
    app.add_middleware(ContentTypeMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(BearerAuthMiddleware, settings=resolved)
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=CORS_METHODS,
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )
    return app
