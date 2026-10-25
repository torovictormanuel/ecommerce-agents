"""
Agente CopySEO — genera fichas optimizadas para MercadoLibre y web.
Sólo opera con datos del catálogo; nunca inventa especificaciones.
"""
from __future__ import annotations

from src.agents.base import BaseAgent, ToolHandler

_TOOL_DEFS = [
    {
        "name": "dal_read",
        "description": "Lee datos del catálogo o inventario para el producto.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sheet": {"type": "string"},
                "filters": {"type": "object"},
            },
            "required": ["sheet"],
        },
    },
]


class CopySEOAgent(BaseAgent):
    AGENT_ID = "copy"
    TOOLS = _TOOL_DEFS

    def _get_prompt_key(self) -> str:
        return "copy"

    def _tool_handlers(self) -> dict[str, ToolHandler]:
        return {
            "dal_read": self._tool_dal_read,
        }

    async def _tool_dal_read(self, sheet: str, filters: dict | None = None) -> dict:
        rows = self.dal.read(sheet, filters)
        return {"rows": rows, "count": len(rows)}
