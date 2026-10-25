"""
Agente de Procesamiento de Órdenes — registra ventas y actualiza estados.
"""
from __future__ import annotations

import logging
from datetime import datetime

from src.agents.base import AgentPayload, AgentResponse, BaseAgent, ToolHandler

logger = logging.getLogger(__name__)

_TOOL_DEFS = [
    {
        "name": "dal_read",
        "description": "Lee filas de órdenes o inventario.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sheet": {"type": "string"},
                "filters": {"type": "object"},
            },
            "required": ["sheet"],
        },
    },
    {
        "name": "dal_write",
        "description": "Actualiza el estado de una orden.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sheet": {"type": "string"},
                "row_id": {"type": "string"},
                "updates": {"type": "object"},
            },
            "required": ["sheet", "row_id", "updates"],
        },
    },
    {
        "name": "dal_append",
        "description": "Registra una nueva orden.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sheet": {"type": "string"},
                "row": {"type": "object"},
            },
            "required": ["sheet", "row"],
        },
    },
]

# FSM de estados válidos
_VALID_TRANSITIONS: dict[str, list[str]] = {
    "PENDIENTE":              ["CONFIRMADA", "CANCELADA"],
    "CONFIRMADA":             ["PREPARANDO", "CANCELADA"],
    "PREPARANDO":             ["DESPACHADA"],
    "DESPACHADA":             ["EN_CAMINO"],
    "EN_CAMINO":              ["ENTREGADA"],
    "ENTREGADA":              ["DEVOLUCION_SOLICITADA"],
    "DEVOLUCION_SOLICITADA":  ["DEVOLUCION_PROCESADA", "CANCELADA"],
    "DEVOLUCION_PROCESADA":   [],
    "CANCELADA":              [],
}


class OrdersAgent(BaseAgent):
    AGENT_ID = "orders"
    TOOLS = _TOOL_DEFS

    def _get_prompt_key(self) -> str:
        return "orders"

    def _tool_handlers(self) -> dict[str, ToolHandler]:
        return {
            "dal_read":   self._tool_dal_read,
            "dal_write":  self._tool_dal_write,
            "dal_append": self._tool_dal_append,
        }

    async def _tool_dal_read(self, sheet: str, filters: dict | None = None) -> dict:
        rows = self.dal.read(sheet, filters)
        return {"rows": rows, "count": len(rows)}

    async def _tool_dal_write(self, sheet: str, row_id: str, updates: dict) -> dict:
        # Validar transición de estado si corresponde
        if "Estado" in updates:
            new_state = updates["Estado"]
            existing = self.dal.read(sheet, {"ID": row_id})
            if existing:
                current = existing[0].get("Estado", "PENDIENTE")
                allowed = _VALID_TRANSITIONS.get(current, [])
                if new_state not in allowed:
                    return {
                        "success": False,
                        "error": f"Transición inválida: {current} → {new_state}",
                        "allowed": allowed,
                    }
            updates["Estado_Anterior"] = existing[0].get("Estado", "") if existing else ""
            updates["Timestamp_Cambio"] = datetime.utcnow().isoformat()

        ok = self.dal.write(sheet, row_id, updates)
        logger.info("Orders write %s[%s] ok=%s", sheet, row_id, ok)
        return {"success": ok}

    async def _tool_dal_append(self, sheet: str, row: dict) -> dict:
        row.setdefault("Estado", "PENDIENTE")
        row.setdefault("Timestamp_Creacion", datetime.utcnow().isoformat())
        new_id = self.dal.append(sheet, row)
        return {"id": new_id, "sheet": sheet}
