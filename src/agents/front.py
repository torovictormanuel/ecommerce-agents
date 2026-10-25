"""
Agente de Atención al Cliente (canal MercadoLibre + Web).
Maneja consultas de stock, reclamos, soporte y asistencia en compra.
"""
from __future__ import annotations

from src.agents.base import AgentPayload, AgentResponse, BaseAgent, ToolHandler

_TOOL_DEFS = [
    {
        "name": "get_product_info",
        "description": "Obtiene stock, precio y descripción de un producto por SKU.",
        "input_schema": {
            "type": "object",
            "properties": {"sku": {"type": "string", "description": "SKU del producto"}},
            "required": ["sku"],
        },
    },
    {
        "name": "get_order_status",
        "description": "Obtiene el estado, tracking y ETA estimado de una orden.",
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string", "description": "ID de la orden"}},
            "required": ["order_id"],
        },
    },
    {
        "name": "update_order_note",
        "description": "Agrega una nota interna (no visible al cliente) a una orden.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "note": {"type": "string"},
            },
            "required": ["order_id", "note"],
        },
    },
    {
        "name": "escalate_to_human",
        "description": "Transfiere la conversación a un agente humano con contexto completo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Razón del escalamiento"},
                "context": {"type": "string", "description": "Resumen del intercambio"},
            },
            "required": ["reason"],
        },
    },
    {
        "name": "get_return_policy",
        "description": "Devuelve la política oficial de devoluciones del negocio.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_warranty_info",
        "description": "Devuelve la información de garantía de un producto.",
        "input_schema": {
            "type": "object",
            "properties": {"sku": {"type": "string"}},
            "required": ["sku"],
        },
    },
    {
        "name": "tag_contact",
        "description": "Etiqueta al contacto en el CRM.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "tag": {"type": "string"},
            },
            "required": ["user_id", "tag"],
        },
    },
    {
        "name": "log_unanswered_question",
        "description": "Registra una pregunta que el agente no pudo responder, para que el equipo mejore la base de conocimiento o el catálogo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "La pregunta que no se pudo responder"},
                "reason": {"type": "string", "description": "Por qué no se pudo responder: sin_datos | fuera_de_scope | datos_conflictivos"},
            },
            "required": ["question"],
        },
    },
]


class FrontAgent(BaseAgent):
    AGENT_ID = "front"
    TOOLS = _TOOL_DEFS

    def _get_prompt_key(self) -> str:
        return "front"

    def _tool_handlers(self) -> dict[str, ToolHandler]:
        return {
            "get_product_info":         self._tool_get_product_info,
            "get_order_status":         self._tool_get_order_status,
            "update_order_note":        self._tool_update_order_note,
            "escalate_to_human":        self._tool_escalate_to_human,
            "get_return_policy":        self._tool_get_return_policy,
            "get_warranty_info":        self._tool_get_warranty_info,
            "tag_contact":              self._tool_tag_contact,
            "log_unanswered_question":  self._tool_log_unanswered_question,
        }

    async def _tool_update_order_note(self, order_id: str, note: str) -> dict:
        ok = self.dal.write("orders", order_id, {"Nota_Interna": note})
        return {"updated": ok, "order_id": order_id}

    async def _tool_tag_contact(self, user_id: str, tag: str) -> dict:
        await self.memory.tag_contact(user_id, tag)
        return {"tagged": True, "user_id": user_id, "tag": tag}
