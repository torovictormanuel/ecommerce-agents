"""
Dependencias compartidas por los routers de FastAPI.
AppState se almacena en app.state y se inyecta via get_app_state().
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from fastapi import Request

if TYPE_CHECKING:
    from src.channels.mercadolibre import MercadoLibreChannel
    from src.channels.whatsapp import WhatsAppChannel
    from src.core.config import AppConfig
    from src.core.dal import DataAccessLayer
    from src.core.memory import MemoryManager


@dataclass
class AppState:
    config: "AppConfig"
    memory: "MemoryManager"
    dal: "DataAccessLayer"
    wpp_channel: "WhatsAppChannel | None" = field(default=None)
    meli_channel: "MercadoLibreChannel | None" = field(default=None)


def get_app_state(request: Request) -> AppState:
    return request.app.state.app_state
