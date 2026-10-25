"""
Agente de Atención al Cliente para canal WhatsApp.
Respuesta tiered: INFO / RECLAMO / URGENTE.
"""
from __future__ import annotations

import logging

from src.agents.base import AgentPayload, AgentResponse, BaseAgent, ToolHandler
from src.channels.whatsapp import WhatsAppChannel

logger = logging.getLogger(__name__)

_TOOL_DEFS = [
    {
        "name": "get_product_info",
        "description": "Obtiene stock, precio y descripción de un producto por SKU.",
        "input_schema": {
            "type": "object",
            "properties": {"sku": {"type": "string"}},
            "required": ["sku"],
        },
    },
    {
        "name": "get_order_status",
        "description": "Obtiene el estado, tracking y ETA de una orden.",
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    },
    {
        "name": "update_contact_record",
        "description": "Actualiza campos del perfil del contacto en el CRM.",
        "input_schema": {
            "type": "object",
            "properties": {
                "phone": {"type": "string"},
                "updates": {"type": "object", "description": "Campos a actualizar"},
            },
            "required": ["phone", "updates"],
        },
    },
    {
        "name": "tag_contact",
        "description": "Etiqueta al contacto en el CRM.",
        "input_schema": {
            "type": "object",
            "properties": {
                "phone": {"type": "string"},
                "tag": {"type": "string"},
            },
            "required": ["phone", "tag"],
        },
    },
    {
        "name": "add_crm_note",
        "description": "Agrega una nota interna al registro del contacto.",
        "input_schema": {
            "type": "object",
            "properties": {
                "phone": {"type": "string"},
                "note": {"type": "string"},
            },
            "required": ["phone", "note"],
        },
    },
    {
        "name": "escalate_to_human",
        "description": "Transfiere al agente humano con contexto completo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string"},
                "context": {"type": "string"},
            },
            "required": ["reason"],
        },
    },
    {
        "name": "get_return_policy",
        "description": "Devuelve la política oficial de devoluciones.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "is_within_business_hours",
        "description": "Indica si actualmente estamos dentro del horario de atención.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "log_unanswered_question",
        "description": "Registra una pregunta que el agente no pudo responder, para que el equipo mejore la base de conocimiento o el catálogo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "reason": {"type": "string", "description": "sin_datos | fuera_de_scope | datos_conflictivos"},
            },
            "required": ["question"],
        },
    },
]


class WhatsAppAgent(BaseAgent):
    AGENT_ID = "whatsapp"
    TOOLS = _TOOL_DEFS

    def __init__(self, config, memory, dal, wpp_channel: WhatsAppChannel | None = None) -> None:
        super().__init__(config, memory, dal)
        self._wpp = wpp_channel

    def _get_prompt_key(self) -> str:
        return "whatsapp"

    def _tool_handlers(self) -> dict[str, ToolHandler]:
        return {
            "get_product_info":         self._tool_get_product_info,
            "get_order_status":         self._tool_get_order_status,
            "update_contact_record":    self._tool_update_contact_record,
            "tag_contact":              self._tool_tag_contact_phone,
            "add_crm_note":             self._tool_add_crm_note,
            "escalate_to_human":        self._tool_escalate_to_human,
            "get_return_policy":        self._tool_get_return_policy,
            "is_within_business_hours": self._tool_is_within_hours,
            "log_unanswered_question":  self._tool_log_unanswered_question,
        }

    async def _tool_update_contact_record(self, phone: str, updates: dict) -> dict:
        user_id = await self.memory.resolve_identity(phone) or phone
        await self.memory.update_profile(user_id, updates)
        return {"updated": True, "phone": phone}

    async def _tool_tag_contact_phone(self, phone: str, tag: str) -> dict:
        user_id = await self.memory.resolve_identity(phone) or phone
        await self.memory.tag_contact(user_id, tag)
        return {"tagged": True, "phone": phone, "tag": tag}

    async def _tool_add_crm_note(self, phone: str, note: str) -> dict:
        user_id = await self.memory.resolve_identity(phone) or phone
        await self.memory.add_crm_note(user_id, note)
        return {"saved": True, "phone": phone}

    async def _tool_is_within_hours(self) -> dict:
        from datetime import datetime
        import pytz
        tz = pytz.timezone(self.config.business.hours.timezone)
        now = datetime.now(tz)
        day_name = now.strftime("%A").lower()
        sched = self.config.business.hours.schedule.get(day_name)
        if not sched or not sched.open or not sched.close:
            return {"within_hours": False}
        fmt = "%H:%M"
        open_t = datetime.strptime(sched.open, fmt).time()
        close_t = datetime.strptime(sched.close, fmt).time()
        within = open_t <= now.time() <= close_t
        return {"within_hours": within, "current_time": now.strftime("%H:%M")}
