from typing import Literal

from ninja import Schema
from pydantic import Field

Provider = Literal["anthropic", "gemini", "ollama"]


class ApiKeyStateOut(Schema):
    configured: bool
    key_hint: str | None
    model: str


class OllamaStateOut(Schema):
    base_url: str
    model: str


class LLMSettingsOut(Schema):
    provider: Provider
    source: Literal["env", "saved"]
    anthropic: ApiKeyStateOut
    gemini: ApiKeyStateOut
    ollama: OllamaStateOut


class LLMSettingsIn(Schema):
    provider: Provider
    anthropic_api_key: str | None = Field(default=None, max_length=1000)
    gemini_api_key: str | None = Field(default=None, max_length=1000)
    ollama_base_url: str | None = Field(default=None, max_length=1000)
    ollama_model: str | None = Field(default=None, max_length=200)


class LLMTestOut(Schema):
    ok: bool
    seconds: float | None = None
    message: str | None = None
