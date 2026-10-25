"""
Endpoints de webhooks — WhatsApp Business y MercadoLibre.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response

from src.agents.orchestrator import OrchestratorAgent
from src.agents.front import FrontAgent
from src.agents.whatsapp_agent import WhatsAppAgent
from src.agents.orders import OrdersAgent
from src.agents.base import AgentPayload, SourceContext, UserContext, ExtractedEntities
from src.api.dependencies import AppState, get_app_state

router = APIRouter()
logger = logging.getLogger(__name__)

_AGENT_MAP = {
    "atencion_cliente_front":   FrontAgent,
    "procesamiento_ordenes":    OrdersAgent,
}


# ── WhatsApp ──────────────────────────────────────────────────────────────────

@router.get("/whatsapp")
async def whatsapp_verify(
    hub_mode: str = Query(alias="hub.mode", default=""),
    hub_verify_token: str = Query(alias="hub.verify_token", default=""),
    hub_challenge: str = Query(alias="hub.challenge", default=""),
    state: AppState = Depends(get_app_state),
):
    if not state.wpp_channel:
        raise HTTPException(503, "Canal WhatsApp no configurado")
    challenge = state.wpp_channel.verify_webhook(
        hub_mode, hub_verify_token, hub_challenge)
    if challenge is None:
        raise HTTPException(403, "Token de verificación inválido")
    return Response(content=challenge, media_type="text/plain")


@router.post("/whatsapp")
async def whatsapp_incoming(
    request: Request,
    x_hub_signature_256: str = Header(default=""),
    state: AppState = Depends(get_app_state),
):
    if not state.wpp_channel:
        raise HTTPException(503, "Canal WhatsApp no configurado")

    body = await request.body()
    if not state.wpp_channel.validate_signature(body, x_hub_signature_256):
        raise HTTPException(401, "Firma inválida")

    payload = await request.json()
    messages = state.wpp_channel.parse_incoming(payload)

    for msg in messages:
        phone = msg["phone"]
        user_id = msg["user_id"]
        text = msg["text"]
        wa_id = msg["wa_message_id"]

        # Resolver identidad cross-channel
        resolved = await state.memory.resolve_identity(phone) or user_id
        await state.memory.map_phone_to_user(phone, resolved)

        # Rate limiting
        if not await state.memory.check_rate_limit(resolved):
            await state.wpp_channel.send_text(
                phone, "Por favor aguardá un momento antes de enviar otro mensaje.")
            continue

        # Guardar turno en memoria
        await state.memory.save_turn(resolved, f"wpp_{phone}", "user", text)

        # Clasificar intención
        orch = OrchestratorAgent(state.config, state.memory, state.dal)
        orch_payload = AgentPayload(
            source=SourceContext(channel="whatsapp", raw_message=text,
                                 message_id=wa_id, user_id=resolved),
            user_context=UserContext(
                conversation_history=await state.memory.get_context(
                    resolved, f"wpp_{phone}"),
            ),
        )
        orch_response = await orch.run(orch_payload)
        routing = orch_response.raw_output

        # Ejecutar agente WhatsApp especializado
        wpp_agent = WhatsAppAgent(
            state.config, state.memory, state.dal, state.wpp_channel)
        agent_payload = AgentPayload(
            intent=routing.get("intent", "SOPORTE"),
            confidence=routing.get("confidence", 0.5),
            priority=routing.get("priority", "MEDIUM"),
            source=SourceContext(channel="whatsapp", raw_message=text,
                                 message_id=wa_id, user_id=resolved),
            user_context=UserContext(
                conversation_history=await state.memory.get_context(
                    resolved, f"wpp_{phone}"),
            ),
            extracted_entities=ExtractedEntities(
                **{k: v for k, v in routing.get(
                    "extracted_entities", {}).items()
                   if k in ExtractedEntities.model_fields}
            ),
        )
        result = await wpp_agent.run(agent_payload)

        # Guardar respuesta en memoria
        await state.memory.save_turn(
            resolved, f"wpp_{phone}", "assistant", result.response_text)

        # Enviar respuesta
        if result.response_text:
            # Dividir en burbujas (máx 1600 chars por mensaje WPP)
            for chunk in _split_wpp_message(result.response_text):
                await state.wpp_channel.send_text(phone, chunk)

        # Marcar como leído
        if wa_id:
            await state.wpp_channel.mark_read(wa_id)

    return {"status": "ok"}


# ── MercadoLibre ──────────────────────────────────────────────────────────────

@router.post("/mercadolibre")
async def meli_incoming(
    request: Request,
    state: AppState = Depends(get_app_state),
):
    if not state.meli_channel:
        raise HTTPException(503, "Canal MercadoLibre no configurado")

    payload = await request.json()
    notification = state.meli_channel.parse_notification(payload)

    if not notification:
        return {"status": "ignored"}

    notif_type = notification["type"]
    resource_id = notification["resource_id"]

    if notif_type == "question":
        question = await state.meli_channel.get_question(resource_id)
        buyer_id = str(question.get("from", {}).get("id", resource_id))
        text = question.get("text", "")
        channel_msg_id = resource_id

    elif notif_type == "order":
        order = await state.meli_channel.get_order(resource_id)
        buyer_id = str(order.get("buyer", {}).get("id", resource_id))
        text = f"Nueva orden #{resource_id}: {order.get('status', '')}"
        channel_msg_id = resource_id

    else:
        return {"status": "ignored"}

    user_id = f"meli_{buyer_id}"
    session_id = f"meli_session_{buyer_id}"

    if not await state.memory.check_rate_limit(user_id):
        return {"status": "rate_limited"}

    await state.memory.save_turn(user_id, session_id, "user", text)

    orch = OrchestratorAgent(state.config, state.memory, state.dal)
    orch_payload = AgentPayload(
        source=SourceContext(channel="mercadolibre", raw_message=text,
                             message_id=channel_msg_id, user_id=user_id),
        user_context=UserContext(
            conversation_history=await state.memory.get_context(
                user_id, session_id),
        ),
    )
    orch_response = await orch.run(orch_payload)
    routing = orch_response.raw_output

    target = routing.get("target_agent", "atencion_cliente_front")
    AgentClass = _AGENT_MAP.get(target, FrontAgent)

    agent = AgentClass(state.config, state.memory, state.dal)
    agent_payload = AgentPayload(
        intent=routing.get("intent", "SOPORTE"),
        source=SourceContext(channel="mercadolibre", raw_message=text,
                             message_id=channel_msg_id, user_id=user_id),
        user_context=UserContext(
            conversation_history=await state.memory.get_context(
                user_id, session_id),
        ),
    )
    result = await agent.run(agent_payload)

    await state.memory.save_turn(
        user_id, session_id, "assistant", result.response_text)

    if notif_type == "question" and result.response_text:
        await state.meli_channel.answer_question(
            resource_id, result.response_text[:2000])

    return {"status": "ok"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _split_wpp_message(text: str, max_len: int = 1500) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    while text:
        chunk = text[:max_len]
        if len(text) > max_len:
            split_at = chunk.rfind("\n")
            if split_at < max_len // 2:
                split_at = chunk.rfind(" ")
            if split_at > 0:
                chunk = chunk[:split_at]
        chunks.append(chunk.strip())
        text = text[len(chunk):].strip()
    return chunks
