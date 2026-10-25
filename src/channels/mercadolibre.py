"""
Canal MercadoLibre — API v2 + Webhooks.
Maneja preguntas, mensajes y notificaciones de órdenes.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from src.core.config import MercadoLibreChannelConfig

logger = logging.getLogger(__name__)

MELI_BASE = "https://api.mercadolibre.com"


class MercadoLibreChannel:
    def __init__(self, cfg: MercadoLibreChannelConfig) -> None:
        self._cfg = cfg
        self._http = httpx.AsyncClient(timeout=15.0)

    async def close(self) -> None:
        await self._http.aclose()

    # ── Webhook normalization ─────────────────────────────────────────────────

    def parse_notification(self, payload: dict) -> dict | None:
        """
        Normaliza un webhook de MeLi.
        Retorna None si no es un tipo de notificación que manejamos.
        """
        topic = payload.get("topic", "")
        resource = payload.get("resource", "")

        if topic == "questions":
            return {"type": "question", "resource_id": resource.split("/")[-1]}
        elif topic == "messages":
            return {"type": "message", "resource_id": resource.split("/")[-1]}
        elif topic == "orders_v2":
            return {"type": "order", "resource_id": resource.split("/")[-1]}
        elif topic == "items":
            return {"type": "item", "resource_id": resource.split("/")[-1]}
        return None

    # ── Questions ─────────────────────────────────────────────────────────────

    async def get_question(self, question_id: str) -> dict:
        return await self._get(f"/questions/{question_id}")

    async def answer_question(self, question_id: str, text: str) -> dict:
        return await self._post(f"/answers", {
            "question_id": int(question_id),
            "text": text,
        })

    # ── Orders ────────────────────────────────────────────────────────────────

    async def get_order(self, order_id: str) -> dict:
        return await self._get(f"/orders/{order_id}")

    async def get_order_items(self, order_id: str) -> list[dict]:
        data = await self._get(f"/orders/{order_id}/items")
        return data.get("order_items", [])

    # ── Messaging (post-venta) ────────────────────────────────────────────────

    async def get_message(self, message_id: str) -> dict:
        return await self._get(f"/messages/{message_id}")

    async def send_message(
        self, pack_id: str, to_user_id: str, text: str
    ) -> dict:
        return await self._post(f"/messages/packs/{pack_id}/sellers/{self._cfg.seller_id}", {
            "from": {"user_id": self._cfg.seller_id},
            "to": {"user_id": to_user_id},
            "text": text,
        })

    # ── Items ─────────────────────────────────────────────────────────────────

    async def get_item(self, item_id: str) -> dict:
        return await self._get(f"/items/{item_id}")

    async def update_item_stock(self, item_id: str, quantity: int) -> dict:
        return await self._put(f"/items/{item_id}", {
            "available_quantity": quantity
        })

    # ── Auth token refresh ────────────────────────────────────────────────────

    async def refresh_token(self) -> dict:
        data = await self._post("/oauth/token", {
            "grant_type": "refresh_token",
            "client_id": self._cfg.client_id,
            "client_secret": self._cfg.client_secret,
            "refresh_token": self._cfg.refresh_token,
        }, auth=False)
        if "access_token" in data:
            self._cfg.access_token = data["access_token"]
            self._cfg.refresh_token = data.get("refresh_token", self._cfg.refresh_token)
        return data

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._cfg.access_token}"}

    async def _get(self, path: str) -> dict:
        try:
            resp = await self._http.get(
                f"{MELI_BASE}{path}", headers=self._headers())
            if resp.status_code == 401:
                await self.refresh_token()
                resp = await self._http.get(
                    f"{MELI_BASE}{path}", headers=self._headers())
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("MeLi GET %s → %s", path, e.response.status_code)
            return {"error": str(e)}
        except Exception as e:
            logger.exception("MeLi GET unexpected: %s", e)
            return {"error": str(e)}

    async def _post(self, path: str, body: dict, auth: bool = True) -> dict:
        headers = self._headers() if auth else {}
        try:
            resp = await self._http.post(
                f"{MELI_BASE}{path}", json=body, headers=headers)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("MeLi POST %s → %s", path, e.response.status_code)
            return {"error": str(e)}
        except Exception as e:
            logger.exception("MeLi POST unexpected: %s", e)
            return {"error": str(e)}

    async def _put(self, path: str, body: dict) -> dict:
        try:
            resp = await self._http.put(
                f"{MELI_BASE}{path}", json=body, headers=self._headers())
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("MeLi PUT %s → %s", path, e.response.status_code)
            return {"error": str(e)}
        except Exception as e:
            logger.exception("MeLi PUT unexpected: %s", e)
            return {"error": str(e)}
