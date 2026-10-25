"""
FastAPI application — punto de entrada del sistema multi-agente.
Monta los routers y gestiona el ciclo de vida (startup/shutdown).
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import get_config
from src.core.dal import build_dal
from src.core.memory import MemoryManager
from src.channels.whatsapp import WhatsAppChannel
from src.channels.mercadolibre import MercadoLibreChannel

from src.api.routes import webhooks, chat, admin
from src.api.dependencies import AppState
from src.api.middleware import (
    ErrorSanitizingMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_config()
    memory = MemoryManager(os.getenv("REDIS_URL", "redis://localhost:6379"))
    await memory.connect()

    dal = build_dal(cfg)

    wpp_channel: WhatsAppChannel | None = None
    if cfg.channels.whatsapp.enabled:
        wpp_channel = WhatsAppChannel(cfg.channels.whatsapp)

    meli_channel: MercadoLibreChannel | None = None
    if cfg.channels.mercadolibre.enabled:
        meli_channel = MercadoLibreChannel(cfg.channels.mercadolibre)

    state = AppState(
        config=cfg,
        memory=memory,
        dal=dal,
        wpp_channel=wpp_channel,
        meli_channel=meli_channel,
    )
    app.state.app_state = state
    logger.info("Sistema iniciado — negocio: %s", cfg.business.name)

    yield

    await memory.close()
    if wpp_channel:
        await wpp_channel.close()
    if meli_channel:
        await meli_channel.close()
    logger.info("Sistema detenido")


def create_app() -> FastAPI:
    cfg = get_config()
    origins = cfg.channels.webchat.allowed_origins

    app = FastAPI(
        title=f"E-Commerce Agents — {cfg.business.name}",
        version="1.0.0",
        docs_url="/docs" if os.getenv("ENV", "production") != "production" else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    # Middlewares — orden inverso de ejecución (el último registrado se ejecuta primero)
    app.add_middleware(ErrorSanitizingMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,  # True sólo si se necesitan cookies cross-origin
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-API-Key", "X-Hub-Signature-256"],
    )

    app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
    app.include_router(chat.router, prefix="/chat", tags=["chat"])
    app.include_router(admin.router, prefix="/admin", tags=["admin"])

    @app.get("/health", tags=["system"])
    async def health():
        return {"status": "ok", "business": cfg.business.name, "env": os.getenv("ENV")}

    return app


app = create_app()
