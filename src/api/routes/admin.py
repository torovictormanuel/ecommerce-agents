"""
Endpoints de administración — health check, sync de inventario, métricas básicas.
Solo accesibles con ADMIN_API_KEY en el header X-API-Key.
"""
from __future__ import annotations

import hmac
import os
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Header

from src.agents.base import AgentPayload, SourceContext
from src.agents.inventory import InventoryAgent
from src.api.dependencies import AppState, get_app_state

router = APIRouter()
logger = logging.getLogger(__name__)


def _require_admin_key(x_api_key: str = Header(default="")) -> None:
    expected = os.getenv("ADMIN_API_KEY", "")
    if not expected:
        raise HTTPException(500, "ADMIN_API_KEY no configurada")
    # Comparación en tiempo constante para evitar timing attacks
    if not hmac.compare_digest(x_api_key.encode(), expected.encode()):
        raise HTTPException(403, "API Key inválida")


@router.get("/health")
async def health(state: AppState = Depends(get_app_state)):
    """Endpoint público de salud para load balancers."""
    try:
        await state.memory.r.ping()
        redis_ok = True
    except Exception:
        redis_ok = False

    return {
        "status": "ok" if redis_ok else "degraded",
        "timestamp": datetime.utcnow().isoformat(),
        "business": state.config.business.name,
        "redis": redis_ok,
        "channels": {
            "whatsapp": state.wpp_channel is not None,
            "mercadolibre": state.meli_channel is not None,
        },
    }


@router.post("/sync/inventory", dependencies=[Depends(_require_admin_key)])
async def sync_inventory(state: AppState = Depends(get_app_state)):
    """Fuerza una sincronización y análisis de inventario."""
    agent = InventoryAgent(state.config, state.memory, state.dal)
    payload = AgentPayload(
        intent="GENERACION_CONTENIDO",
        source=SourceContext(channel="internal",
                             raw_message="Revisar stock completo y emitir alertas"),
    )
    result = await agent.run(payload)
    return {
        "status": "completed",
        "result": result.raw_output,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.delete("/cache/products", dependencies=[Depends(_require_admin_key)])
async def clear_product_cache(state: AppState = Depends(get_app_state)):
    """Invalida el cache de productos en Redis."""
    keys = await state.memory.r.keys("cache:product:*")
    if keys:
        await state.memory.r.delete(*keys)
    return {"deleted_keys": len(keys)}


@router.get("/metrics", dependencies=[Depends(_require_admin_key)])
async def metrics(state: AppState = Depends(get_app_state)):
    """Métricas básicas desde Redis."""
    profile_count = len(await state.memory.r.keys("profile:*"))
    ctx_count = len(await state.memory.r.keys("ctx:*"))
    cache_count = len(await state.memory.r.keys("cache:product:*"))
    return {
        "active_profiles": profile_count,
        "active_sessions": ctx_count,
        "cached_products": cache_count,
        "timestamp": datetime.utcnow().isoformat(),
    }
