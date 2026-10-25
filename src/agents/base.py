"""
Clase base para todos los agentes. Implementa el loop agéntico con tool use.
Cada sub-agente define AGENT_ID, TOOLS y _tool_handlers().
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Callable, Coroutine

import os

from pydantic import BaseModel, Field

from src.core.config import AppConfig, AgentModelConfig
from src.core.dal import DataAccessLayer
from src.core.memory import MemoryManager
from src.prompts.builder import build_system_prompt

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 6
_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")

_GROQ_MODEL_MAP: dict[str, str] = {
    "claude-haiku-5-5":  "llama-3.1-8b-instant",
    "claude-sonnet-4-6": "llama-3.3-70b-versatile",
    "claude-opus-5-5":   "llama-3.3-70b-versatile",
}
_GEMINI_MODEL_MAP: dict[str, str] = {
    "claude-haiku-5-5":  "gemini-1.5-flash",
    "claude-sonnet-4-6": "gemini-1.5-flash",
    "claude-opus-5-5":   "gemini-1.5-flash",
}


def _resolve_model(model: str) -> str:
    if _PROVIDER == "groq":
        if "/" in model or model.startswith("llama-") or model.startswith("gemma") or model.startswith("mixtral") or model.startswith("qwen") or model.startswith("openai/"):
            return model
        return _GROQ_MODEL_MAP.get(model, "openai/gpt-oss-120b")
    if _PROVIDER == "gemini":
        if model.startswith("gemini-"):
            return model
        return _GEMINI_MODEL_MAP.get(model, "gemini-1.5-flash")
    return model


def _to_openai_tools(tools: list[dict]) -> list[dict]:
    """Convierte tool defs de formato Anthropic a formato OpenAI."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        }
        for t in tools
    ]


# ── Modelos de entrada/salida ─────────────────────────────────────────────────

class SourceContext(BaseModel):
    channel: str = "web"
    raw_message: str = ""
    message_id: str = ""
    user_id: str = ""


class UserContext(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    conversation_history: list[dict] = Field(default_factory=list)
    user_profile: dict = Field(default_factory=dict)


class ExtractedEntities(BaseModel):
    order_id: str | None = None
    product_sku: str | None = None
    user_id: str | None = None
    keywords: list[str] = Field(default_factory=list)


class AgentPayload(BaseModel):
    payload_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    intent: str = "SOPORTE"
    confidence: float = 1.0
    priority: str = "MEDIUM"
    source: SourceContext = Field(default_factory=SourceContext)
    target_agent: str = ""
    user_context: UserContext = Field(default_factory=UserContext)
    extracted_entities: ExtractedEntities = Field(default_factory=ExtractedEntities)
    requires_clarification: bool = False
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class AgentResponse(BaseModel):
    payload_id: str
    agent_id: str
    response_text: str = ""
    channel: str = "web"
    escalate: bool = False
    escalation_reason: str | None = None
    tools_used: list[str] = Field(default_factory=list)
    contact_updates: dict = Field(default_factory=dict)
    session_resolved: bool = False
    raw_output: dict = Field(default_factory=dict)
    error: str | None = None
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ── Clase base ────────────────────────────────────────────────────────────────

ToolHandler = Callable[..., Coroutine[Any, Any, dict]]


class BaseAgent:
    AGENT_ID: str = "base_agent"
    TOOLS: list[dict] = []

    def __init__(
        self,
        config: AppConfig,
        memory: MemoryManager,
        dal: DataAccessLayer,
    ) -> None:
        self.config = config
        self.memory = memory
        self.dal = dal
        self._provider = _PROVIDER
        if self._provider == "groq":
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                api_key=os.getenv("GROQ_API_KEY"),
                base_url="https://api.groq.com/openai/v1",
            )
        elif self._provider == "gemini":
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                api_key=os.getenv("GEMINI_API_KEY"),
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            )
        else:
            import anthropic
            self._client = anthropic.AsyncAnthropic()
        self._model_cfg: AgentModelConfig = getattr(
            config.agents, self.AGENT_ID.split("_")[0],
            config.agents.front,
        )
        self._system_prompt = build_system_prompt(
            self._get_prompt_key(), config)
        self._tools_used: list[str] = []

    def _get_prompt_key(self) -> str:
        return self.AGENT_ID.replace("_agent", "").replace("atencion_cliente_", "")

    def _tool_handlers(self) -> dict[str, ToolHandler]:
        """Subclases sobreescriben esto para registrar sus herramientas."""
        return {}

    # ── Loop agéntico ─────────────────────────────────────────────────────────

    async def run(self, payload: AgentPayload) -> AgentResponse:
        self._tools_used = []
        response = None
        try:
            if self._provider in ("gemini", "groq"):
                response = await self._run_openai(payload)
            else:
                response = await self._run_anthropic(payload)
        except Exception as e:
            logger.exception("Agent %s error: %s", self.AGENT_ID, e)
            return AgentResponse(
                payload_id=payload.payload_id,
                agent_id=self.AGENT_ID,
                error=str(e),
                channel=payload.source.channel,
            )
        return self._build_response(payload, response)

    async def _run_anthropic(self, payload: AgentPayload) -> Any:
        import anthropic as _anthropic
        messages = self._build_messages(payload)
        response = None
        for _ in range(MAX_TOOL_ROUNDS):
            response = await self._client.messages.create(
                model=self._model_cfg.model,
                max_tokens=self._model_cfg.max_tokens,
                system=self._system_prompt,
                tools=self.TOOLS or _anthropic.NOT_GIVEN,
                messages=messages,
            )
            if response.stop_reason != "tool_use":
                break
            tool_results = await self._execute_tools_anthropic(response.content)
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
        return response

    async def _run_openai(self, payload: AgentPayload) -> Any:
        messages: list[dict] = [{"role": "system", "content": self._system_prompt}]
        messages += self._build_messages(payload)
        openai_tools = _to_openai_tools(self.TOOLS) if self.TOOLS else None
        model = _resolve_model(self._model_cfg.model)
        response = None
        for _ in range(MAX_TOOL_ROUNDS):
            kwargs: dict = {
                "model": model,
                "max_tokens": self._model_cfg.max_tokens,
                "messages": messages,
            }
            if openai_tools:
                kwargs["tools"] = openai_tools
            response = await self._client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            if choice.finish_reason != "tool_calls" or not choice.message.tool_calls:
                break
            tool_results = await self._execute_tools_openai(choice.message.tool_calls)
            messages.append(choice.message)
            messages += tool_results
        return response

    def _build_messages(self, payload: AgentPayload) -> list[dict]:
        messages: list[dict] = []
        # Inyectar historial de conversación
        for turn in payload.user_context.conversation_history:
            messages.append({"role": turn["role"], "content": turn["content"]})
        # Mensaje actual del usuario
        messages.append({
            "role": "user",
            "content": payload.source.raw_message,
        })
        return messages

    async def _execute_tools_anthropic(self, content: list) -> list[dict]:
        handlers = self._tool_handlers()
        results = []
        for block in content:
            if not hasattr(block, "type") or block.type != "tool_use":
                continue
            self._tools_used.append(block.name)
            handler = handlers.get(block.name)
            result = await self._call_handler(handler, block.name, block.input)
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result, ensure_ascii=False),
            })
        return results

    async def _execute_tools_openai(self, tool_calls: list) -> list[dict]:
        handlers = self._tool_handlers()
        results = []
        for call in tool_calls:
            name = call.function.name
            self._tools_used.append(name)
            try:
                args = json.loads(call.function.arguments)
            except Exception:
                args = {}
            handler = handlers.get(name)
            result = await self._call_handler(handler, name, args)
            results.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result, ensure_ascii=False),
            })
        return results

    async def _call_handler(
        self, handler: Any, name: str, args: dict
    ) -> dict:
        if handler:
            try:
                return await handler(**args)
            except Exception as e:
                return {"error": str(e)}
        logger.warning("Tool '%s' not registered in %s", name, self.AGENT_ID)
        return {"error": f"Herramienta '{name}' no encontrada"}

    def _build_response(
        self, payload: AgentPayload, response: Any
    ) -> AgentResponse:
        text = ""
        if response is not None:
            if self._provider in ("gemini", "groq"):
                text = response.choices[0].message.content or ""
            else:
                for block in response.content:
                    if hasattr(block, "text"):
                        text = block.text
                        break

        # Intentar parsear JSON del agente
        raw_output: dict = {}
        try:
            raw_output = json.loads(text)
            response_text = (
                raw_output.get("response_text")
                or raw_output.get("customer_message")
                or "\n".join(
                    m.get("body", "") for m in raw_output.get("messages", []))
                or text
            )
        except (json.JSONDecodeError, TypeError):
            response_text = text

        return AgentResponse(
            payload_id=payload.payload_id,
            agent_id=self.AGENT_ID,
            response_text=response_text,
            channel=payload.source.channel,
            escalate=raw_output.get("escalate", False),
            escalation_reason=raw_output.get("escalation_reason"),
            tools_used=self._tools_used,
            contact_updates=raw_output.get("contact_updates", {}),
            session_resolved=raw_output.get("session_resolved", False),
            raw_output=raw_output,
        )

    # ── Helpers comunes a todos los agentes ───────────────────────────────────

    async def _tool_get_product_info(self, sku: str) -> dict:
        cached = await self.memory.get_cached_product(sku)
        if cached:
            return cached
        product = self.dal.get_product(sku)
        if not product:
            return {"error": f"Producto {sku} no encontrado"}
        await self.memory.cache_product(sku, product)
        return product

    async def _tool_get_order_status(self, order_id: str) -> dict:
        order = self.dal.get_order(order_id)
        if not order:
            return {"error": f"Orden {order_id} no encontrada"}
        return order

    async def _tool_get_return_policy(self) -> dict:
        return {"policy": self.config.business.policies.returns}

    async def _tool_get_warranty_info(self, sku: str) -> dict:
        product = self.dal.get_catalog_item(sku)
        if not product:
            return {"error": f"Producto {sku} no encontrado en catálogo"}
        return {"sku": sku, "warranty": product.get("Garantia", self.config.business.policies.warranty)}

    async def _tool_escalate_to_human(self, reason: str, context: str = "") -> dict:
        logger.warning("ESCALADO: agent=%s reason=%s", self.AGENT_ID, reason)
        return {
            "escalated": True,
            "reason": reason,
            "message_to_user": self.config.business.escalation.escalation_message,
        }

    async def _tool_log_unanswered_question(
        self, question: str, reason: str = "sin_datos"
    ) -> dict:
        """
        Registra preguntas que el agente no pudo responder.
        El negocio las revisa para mejorar su base de conocimiento / catálogo.
        Patrón MazeFunnels: "Log unanswered questions so the team can update the knowledge base."
        """
        logger.warning(
            "UNANSWERED: agent=%s reason=%s question=%.120s",
            self.AGENT_ID, reason, question,
        )
        log_row = {
            "Agente": self.AGENT_ID,
            "Pregunta": question,
            "Razon": reason,
            "Timestamp": datetime.utcnow().isoformat(),
        }
        try:
            self.dal.append("unanswered_log", log_row)
        except Exception:
            pass  # El log no debe interrumpir la conversación
        return {"logged": True, "question": question}
