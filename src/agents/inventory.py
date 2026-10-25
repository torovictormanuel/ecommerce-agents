"""
Agente de Gestión de Inventario — opera en el backend.
Lee y escribe en la fuente de datos, emite alertas de reposición.
"""
from __future__ import annotations

import logging
from datetime import datetime

from src.agents.base import AgentPayload, AgentResponse, BaseAgent, ToolHandler

logger = logging.getLogger(__name__)

_TOOL_DEFS = [
    {
        "name": "dal_read",
        "description": "Lee filas de una hoja con filtros opcionales.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sheet": {"type": "string", "description": "Nombre lógico de la hoja"},
                "filters": {"type": "object", "description": "Filtros {col: valor}"},
            },
            "required": ["sheet"],
        },
    },
    {
        "name": "dal_write",
        "description": "Actualiza campos de una fila por ID.",
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
        "description": "Inserta una fila nueva en la hoja indicada.",
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


class InventoryAgent(BaseAgent):
    AGENT_ID = "inventory"
    TOOLS = _TOOL_DEFS

    def _get_prompt_key(self) -> str:
        return "inventory"

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
        updates["Ultima_Actualizacion"] = datetime.utcnow().isoformat()
        ok = self.dal.write(sheet, row_id, updates)
        logger.info("Inventory write %s[%s] ok=%s", sheet, row_id, ok)
        return {"success": ok, "sheet": sheet, "row_id": row_id}

    async def _tool_dal_append(self, sheet: str, row: dict) -> dict:
        row["Timestamp_Creacion"] = datetime.utcnow().isoformat()
        new_id = self.dal.append(sheet, row)
        return {"id": new_id, "sheet": sheet}
