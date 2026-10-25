"""
Endpoint de Web Chat — conversación sincrónica via HTTP.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.agents.base import AgentPayload, AgentResponse, SourceContext, UserContext, ExtractedEntities
from src.agents.front import FrontAgent
from src.agents.orchestrator import OrchestratorAgent
from src.agents.orders import OrdersAgent
from src.api.dependencies import AppState, get_app_state

router = APIRouter()
logger = logging.getLogger(__name__)

_AGENT_MAP = {
    "atencion_cliente_front":  FrontAgent,
    "procesamiento_ordenes":   OrdersAgent,
}


class ChatRequest(BaseModel):
    user_id: str
    session_id: str
    message: str
    channel: str = "web"


class ChatResponse(BaseModel):
    response: str
    intent: str = ""
    escalate: bool = False
    session_resolved: bool = False
    tools_used: list[str] = Field(default_factory=list)


@router.post("/message", response_model=ChatResponse)
async def chat_message(
    body: ChatRequest,
    state: AppState = Depends(get_app_state),
):
    if not state.config.channels.webchat.enabled:
        raise HTTPException(503, "Canal Web Chat no habilitado")

    if not await state.memory.check_rate_limit(body.user_id):
        raise HTTPException(429, "Demasiados mensajes. Aguardá un momento.")

    await state.memory.save_turn(
        body.user_id, body.session_id, "user", body.message)

    history = await state.memory.get_context(body.user_id, body.session_id)

    # Clasificar
    orch = OrchestratorAgent(state.config, state.memory, state.dal)
    orch_payload = AgentPayload(
        source=SourceContext(channel=body.channel, raw_message=body.message,
                             user_id=body.user_id),
        user_context=UserContext(conversation_history=history),
    )
    orch_resp = await orch.run(orch_payload)
    routing = orch_resp.raw_output

    target = routing.get("target_agent", "atencion_cliente_front")
    AgentClass = _AGENT_MAP.get(target, FrontAgent)

    agent = AgentClass(state.config, state.memory, state.dal)
    agent_payload = AgentPayload(
        intent=routing.get("intent", "SOPORTE"),
        confidence=routing.get("confidence", 0.5),
        priority=routing.get("priority", "MEDIUM"),
        source=SourceContext(channel=body.channel, raw_message=body.message,
                             user_id=body.user_id),
        user_context=UserContext(conversation_history=history),
        extracted_entities=ExtractedEntities(
            **{k: v for k, v in routing.get("extracted_entities", {}).items()
               if k in ExtractedEntities.model_fields}
        ),
    )
    result = await agent.run(agent_payload)

    await state.memory.save_turn(
        body.user_id, body.session_id, "assistant", result.response_text)

    return ChatResponse(
        response=result.response_text,
        intent=routing.get("intent", ""),
        escalate=result.escalate,
        session_resolved=result.session_resolved,
        tools_used=result.tools_used,
    )
