"""
Carga y valida la configuración de business.yaml.
Los valores ${VAR} se expanden desde variables de entorno.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, model_validator


# ── Modelos de configuración ──────────────────────────────────────────────────

class ToneConfig(BaseModel):
    style: str = "friendly"
    use_tuteo: bool = True
    emoji_level: str = "moderate"


class PoliciesConfig(BaseModel):
    returns: str = "Sin política de devolución configurada."
    warranty: str = "Sin política de garantía configurada."
    shipping: str = "Sin política de envío configurada."


class DaySchedule(BaseModel):
    open: Optional[str] = None
    close: Optional[str] = None


class HoursConfig(BaseModel):
    timezone: str = "America/Buenos_Aires"
    schedule: dict[str, DaySchedule] = Field(default_factory=dict)
    out_of_hours_message: str = "Estamos fuera de horario. Te responderemos pronto."


class EscalationConfig(BaseModel):
    email: str = ""
    whatsapp_human: Optional[str] = None
    slack_webhook: Optional[str] = None
    max_retries_before_escalation: int = 2
    escalation_message: str = "Te conectamos con nuestro equipo en un momento."


class BusinessConfig(BaseModel):
    name: str
    description: str = ""
    industry: str = "general"
    language: str = "es-AR"
    currency: str = "ARS"
    currency_symbol: str = "$"
    tone: ToneConfig = Field(default_factory=ToneConfig)
    policies: PoliciesConfig = Field(default_factory=PoliciesConfig)
    hours: HoursConfig = Field(default_factory=HoursConfig)
    escalation: EscalationConfig = Field(default_factory=EscalationConfig)


class MercadoLibreChannelConfig(BaseModel):
    enabled: bool = False
    client_id: str = ""
    client_secret: str = ""
    access_token: str = ""
    refresh_token: str = ""
    seller_id: str = ""
    listen: list[str] = Field(default_factory=lambda: ["questions", "orders"])


class WhatsAppChannelConfig(BaseModel):
    enabled: bool = False
    phone_number_id: str = ""
    access_token: str = ""
    verify_token: str = ""
    app_secret: str = ""
    welcome_buttons: list[str] = Field(default_factory=list)


class WebChatChannelConfig(BaseModel):
    enabled: bool = True
    allowed_origins: list[str] = Field(default_factory=lambda: ["*"])


class ChannelsConfig(BaseModel):
    mercadolibre: MercadoLibreChannelConfig = Field(
        default_factory=MercadoLibreChannelConfig)
    whatsapp: WhatsAppChannelConfig = Field(
        default_factory=WhatsAppChannelConfig)
    webchat: WebChatChannelConfig = Field(
        default_factory=WebChatChannelConfig)


class SheetsDataConfig(BaseModel):
    credentials_path: str = ""
    spreadsheet_id: str = ""
    sheets_map: dict[str, str] = Field(default_factory=lambda: {
        "inventory": "Inventario",
        "orders": "Ordenes",
        "catalog": "Catalogo",
        "contacts": "Contactos",
        "unanswered_log": "PregunSinRespuesta",
    })


class ExcelDataConfig(BaseModel):
    file_path: str = ""
    sheets_map: dict[str, str] = Field(default_factory=lambda: {
        "inventory": "Inventario",
        "orders": "Ordenes",
        "catalog": "Catalogo",
        "contacts": "Contactos",
        "unanswered_log": "PregunSinRespuesta",
    })


class DataSourceConfig(BaseModel):
    type: str = "sheets"
    sheets: SheetsDataConfig = Field(default_factory=SheetsDataConfig)
    excel: ExcelDataConfig = Field(default_factory=ExcelDataConfig)


class AgentModelConfig(BaseModel):
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 1000
    temperature: float = 0.3


class AgentsConfig(BaseModel):
    orchestrator: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(
            model="claude-haiku-5-5", max_tokens=500, temperature=0.1))
    front: AgentModelConfig = Field(default_factory=AgentModelConfig)
    whatsapp: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(max_tokens=800, temperature=0.4))
    inventory: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(
            model="claude-haiku-5-5", max_tokens=600, temperature=0.0))
    orders: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(max_tokens=800, temperature=0.1))
    copy: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(max_tokens=2000, temperature=0.6))


class AppConfig(BaseModel):
    business: BusinessConfig
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    data_source: DataSourceConfig = Field(default_factory=DataSourceConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)

    @property
    def tone_description(self) -> str:
        t = self.business.tone
        parts = [f"Estilo: {t.style}"]
        if t.use_tuteo:
            parts.append("Tutear al usuario (vos/tú)")
        else:
            parts.append("Tratar de usted")
        parts.append(f"Emojis: {t.emoji_level}")
        return " · ".join(parts)

    @property
    def active_dal_config(self) -> SheetsDataConfig | ExcelDataConfig:
        if self.data_source.type == "sheets":
            return self.data_source.sheets
        return self.data_source.excel

    def sheet_name(self, logical: str) -> str:
        return self.active_dal_config.sheets_map.get(logical, logical)


# ── Carga de config ───────────────────────────────────────────────────────────

_ENV_VAR_RE = re.compile(r"\$\{(\w+)\}")


def _expand_env_vars(obj: object) -> object:
    """Reemplaza ${VAR} con el valor de la variable de entorno correspondiente."""
    if isinstance(obj, str):
        return _ENV_VAR_RE.sub(lambda m: os.getenv(m.group(1), m.group(0)), obj)
    if isinstance(obj, dict):
        return {k: _expand_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env_vars(i) for i in obj]
    return obj


def load_config(path: str | None = None) -> AppConfig:
    config_path = path or os.getenv("CONFIG_PATH", "config/business.yaml")
    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    raw = _expand_env_vars(raw)
    return AppConfig(**raw)


# Singleton cargado una sola vez al iniciar
_config: AppConfig | None = None


def get_config() -> AppConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config
