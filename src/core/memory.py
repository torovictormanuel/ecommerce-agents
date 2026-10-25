"""
Sistema de memoria en tres capas:
  L1 — Efímera     (Redis TTL 24h):  historial de conversación
  L2 — Persistente (Redis TTL 30d):  Contact Record por usuario
  L3 — Archivo     (Sheets/DB):      flush asíncrono de L2
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

CTX_TTL    = 86_400       # 24 h
PROFILE_TTL = 30 * 86_400  # 30 días
MAX_TURNS  = 10


class MemoryManager:
    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._client: aioredis.Redis | None = None

    async def connect(self) -> None:
        self._client = aioredis.from_url(
            self._redis_url, encoding="utf-8", decode_responses=True)
        await self._client.ping()
        logger.info("MemoryManager conectado a Redis")

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    @property
    def r(self) -> aioredis.Redis:
        if self._client is None:
            raise RuntimeError("MemoryManager no inicializado — llama connect() primero")
        return self._client

    # ── L1: Contexto de conversación ─────────────────────────────────────────

    async def get_context(self, user_id: str, session_id: str) -> list[dict]:
        raw = await self.r.get(f"ctx:{user_id}:{session_id}")
        return json.loads(raw) if raw else []

    async def save_turn(
        self, user_id: str, session_id: str,
        role: str, content: str
    ) -> None:
        key = f"ctx:{user_id}:{session_id}"
        history = await self.get_context(user_id, session_id)
        history.append({"role": role, "content": content})
        history = history[-MAX_TURNS:]
        await self.r.setex(key, CTX_TTL, json.dumps(history, ensure_ascii=False))

    async def clear_context(self, user_id: str, session_id: str) -> None:
        await self.r.delete(f"ctx:{user_id}:{session_id}")

    # ── L2: Contact Record ───────────────────────────────────────────────────

    async def get_profile(self, user_id: str) -> dict[str, Any]:
        raw = await self.r.get(f"profile:{user_id}")
        return json.loads(raw) if raw else {}

    async def update_profile(self, user_id: str, updates: dict) -> None:
        profile = await self.get_profile(user_id)
        profile.update(updates)
        profile["ultimo_contacto"] = datetime.utcnow().isoformat()
        await self.r.setex(
            f"profile:{user_id}", PROFILE_TTL,
            json.dumps(profile, ensure_ascii=False)
        )

    async def tag_contact(self, user_id: str, tag: str) -> None:
        profile = await self.get_profile(user_id)
        tags: set = set(profile.get("tags", []))
        tags.add(tag)
        await self.update_profile(user_id, {"tags": list(tags)})

    async def add_crm_note(self, user_id: str, note: str) -> None:
        profile = await self.get_profile(user_id)
        notes: list = profile.get("notas_crm", [])
        notes.append({"ts": datetime.utcnow().isoformat(), "note": note})
        notes = notes[-20:]  # mantener las últimas 20 notas
        await self.update_profile(user_id, {"notas_crm": notes})

    # ── Identity resolution (cross-channel) ─────────────────────────────────

    async def map_phone_to_user(self, phone: str, user_id: str) -> None:
        await self.r.setex(f"phone_map:{phone}", PROFILE_TTL, user_id)
        await self.update_profile(user_id, {"phone": phone})

    async def resolve_identity(self, phone: str) -> str | None:
        return await self.r.get(f"phone_map:{phone}")

    # ── Order locks (escritura concurrente) ──────────────────────────────────

    async def acquire_order_lock(self, order_id: str) -> bool:
        return bool(await self.r.set(
            f"lock:order:{order_id}", "1", nx=True, ex=30))

    async def release_order_lock(self, order_id: str) -> None:
        await self.r.delete(f"lock:order:{order_id}")

    # ── Rate limiting ────────────────────────────────────────────────────────

    async def check_rate_limit(self, user_id: str, max_rpm: int = 30) -> bool:
        """Retorna True si el usuario está dentro del límite (sliding window 1 min)."""
        key = f"ratelimit:{user_id}"
        pipe = self.r.pipeline()
        now_sec = int(datetime.utcnow().timestamp())
        pipe.zadd(key, {str(now_sec): now_sec})
        pipe.zremrangebyscore(key, 0, now_sec - 60)
        pipe.zcard(key)
        pipe.expire(key, 65)
        results = await pipe.execute()
        count = results[2]
        return count <= max_rpm

    # ── Product cache ────────────────────────────────────────────────────────

    async def get_cached_product(self, sku: str) -> dict | None:
        raw = await self.r.get(f"cache:product:{sku}")
        return json.loads(raw) if raw else None

    async def cache_product(self, sku: str, data: dict, ttl: int = 900) -> None:
        await self.r.setex(
            f"cache:product:{sku}", ttl,
            json.dumps(data, ensure_ascii=False)
        )
