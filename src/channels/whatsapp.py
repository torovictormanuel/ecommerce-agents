"""
Canal WhatsApp Business — Meta Cloud API.
Valida webhooks (HMAC-SHA256), parsea mensajes entrantes y envía respuestas.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

import httpx

from src.core.config import WhatsAppChannelConfig

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.facebook.com/v21.0"


class WhatsAppChannel:
    def __init__(self, cfg: WhatsAppChannelConfig) -> None:
        self._cfg = cfg
        self._http = httpx.AsyncClient(timeout=10.0)

    async def close(self) -> None:
        await self._http.aclose()

    # ── Webhook verification (GET) ────────────────────────────────────────────

    def verify_webhook(self, mode: str, token: str, challenge: str) -> str | None:
        if mode == "subscribe" and token == self._cfg.verify_token:
            return challenge
        return None

    # ── Signature validation (POST) ──────────────────────────────────────────

    def validate_signature(self, body: bytes, signature: str) -> bool:
        if not signature.startswith("sha256="):
            return False
        expected = hmac.new(
            self._cfg.app_secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature[7:])

    # ── Message parsing ───────────────────────────────────────────────────────

    def parse_incoming(self, payload: dict) -> list[dict]:
        """
        Extrae mensajes normalizados de la estructura de webhook de Meta.
        Retorna lista de dicts: {phone, user_id, message_type, text, wa_message_id}.
        """
        messages: list[dict] = []
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                contacts = {
                    c["wa_id"]: c.get("profile", {}).get("name", "")
                    for c in value.get("contacts", [])
                }
                for msg in value.get("messages", []):
                    phone = msg.get("from", "")
                    msg_type = msg.get("type", "text")

                    if msg_type == "text":
                        text = msg.get("text", {}).get("body", "")
                    elif msg_type == "interactive":
                        inter = msg.get("interactive", {})
                        if inter.get("type") == "button_reply":
                            text = inter["button_reply"]["title"]
                        elif inter.get("type") == "list_reply":
                            text = inter["list_reply"]["title"]
                        else:
                            text = ""
                    elif msg_type == "image":
                        text = "[imagen recibida]"
                    elif msg_type == "audio":
                        text = "[audio recibido]"
                    elif msg_type == "document":
                        text = "[documento recibido]"
                    else:
                        text = f"[{msg_type}]"

                    messages.append({
                        "phone": phone,
                        "name": contacts.get(phone, ""),
                        "user_id": f"wpp_{phone}",
                        "message_type": msg_type,
                        "text": text,
                        "wa_message_id": msg.get("id", ""),
                        "timestamp": msg.get("timestamp", ""),
                    })
        return messages

    # ── Sending ───────────────────────────────────────────────────────────────

    async def send_text(self, to_phone: str, body: str) -> dict:
        return await self._post({
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_phone,
            "type": "text",
            "text": {"preview_url": False, "body": body},
        })

    async def send_interactive_buttons(
        self, to_phone: str, body: str, buttons: list[str]
    ) -> dict:
        btn_list = [
            {"type": "reply", "reply": {"id": f"btn_{i}", "title": b[:20]}}
            for i, b in enumerate(buttons[:3])  # Meta permite máx 3 botones
        ]
        return await self._post({
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_phone,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body},
                "action": {"buttons": btn_list},
            },
        })

    async def send_template(
        self, to_phone: str, template_name: str, lang: str = "es_AR",
        components: list[dict] | None = None
    ) -> dict:
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": to_phone,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": lang},
            },
        }
        if components:
            payload["template"]["components"] = components
        return await self._post(payload)

    async def mark_read(self, wa_message_id: str) -> dict:
        return await self._post({
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": wa_message_id,
        })

    async def _post(self, payload: dict) -> dict:
        url = f"{GRAPH_BASE}/{self._cfg.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self._cfg.access_token}",
            "Content-Type": "application/json",
        }
        try:
            resp = await self._http.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("WPP send error %s: %s", e.response.status_code,
                         e.response.text[:200])
            return {"error": str(e)}
        except Exception as e:
            logger.exception("WPP send unexpected error: %s", e)
            return {"error": str(e)}
