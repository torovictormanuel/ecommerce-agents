"""
Orquestador Central — clasifica la intención y enruta al agente correcto.
No responde al usuario; solo produce el JSON de enrutamiento.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from src.agents.base import AgentPayload, AgentResponse, BaseAgent
from src.core.config import AppConfig
from src.core.dal import DataAccessLayer
from src.core.memory import MemoryManager

logger = logging.getLogger(__name__)


class OrchestratorAgent(BaseAgent):
    AGENT_ID = "orchestrator"
    TOOLS: list[dict] = []  # El orquestador NO usa tool use — sólo clasifica

    def _get_prompt_key(self) -> str:
        return "orchestrator"

    def _build_messages(self, payload: AgentPayload) -> list[dict]:
        channel = payload.source.channel
        user_msg = payload.source.raw_message
        entities_hint = ""
        if payload.extracted_entities.order_id:
            entities_hint = f"\n[order_id detectado: {payload.extracted_entities.order_id}]"
        if payload.extracted_entities.product_sku:
            entities_hint += f"\n[sku detectado: {payload.extracted_entities.product_sku}]"

        return [{
            "role": "user",
            "content": (
                f"CHANNEL: {channel}\n"
                f"TIMESTAMP: {datetime.utcnow().isoformat()}\n"
                f"MESSAGE: {user_msg}{entities_hint}"
            ),
        }]

    def _build_response(self, payload: AgentPayload, response) -> AgentResponse:
        text = ""
        if response is not None:
            if self._provider in ("gemini", "groq"):
                text = (response.choices[0].message.content or "").strip()
            else:
                for block in response.content:
                    if hasattr(block, "text"):
                        text = block.text.strip()
                        break

        raw: dict = {}
        try:
            # El LLM a veces envuelve el JSON en ```json … ```
            if "```" in text:
                text = text.split("```")[1].lstrip("json").strip()
            raw = json.loads(text)
        except (json.JSONDecodeError, IndexError):
            logger.error("Orchestrator JSON parse error: %s", text[:200])
            raw = {
                "intent": "SOPORTE",
                "confidence": 0.5,
                "priority": "MEDIUM",
                "target_agent": "atencion_cliente_front",
                "requires_clarification": True,
            }

        return AgentResponse(
            payload_id=payload.payload_id,
            agent_id=self.AGENT_ID,
            response_text="",
            channel=payload.source.channel,
            raw_output=raw,
        )
