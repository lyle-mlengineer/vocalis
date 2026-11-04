from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote

import httpx

from app.config import Settings


class VoiceProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class GeneratedVoice:
    provider_voice_id: str
    preview_url: str | None


class VoiceProvider(Protocol):
    def create_voice(self, specification: dict) -> GeneratedVoice: ...

    def synthesize(self, provider_voice_id: str, text: str, settings: dict) -> bytes: ...


class HttpVoiceProvider:
    """Adapter for a voice service exposing Vocalis' small provider HTTP contract."""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def create_voice(self, specification: dict) -> GeneratedVoice:
        try:
            response = httpx.post(
                f"{self.base_url}/voices",
                json=specification,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=60,
            )
            response.raise_for_status()
            payload = response.json()
            provider_voice_id = payload.get("id")
            if not isinstance(provider_voice_id, str) or not provider_voice_id:
                raise VoiceProviderError("Voice provider response is missing an id.")
            preview_url = payload.get("preview_url")
            if preview_url is not None and not isinstance(preview_url, str):
                raise VoiceProviderError("Voice provider returned an invalid preview_url.")
            return GeneratedVoice(provider_voice_id, preview_url)
        except (httpx.HTTPError, ValueError) as exc:
            raise VoiceProviderError("Voice generation provider request failed.") from exc

    def synthesize(self, provider_voice_id: str, text: str, settings: dict) -> bytes:
        try:
            response = httpx.post(
                f"{self.base_url}/voices/{quote(provider_voice_id, safe='')}/speech",
                json={"text": text, **settings},
                headers={"Authorization": f"Bearer {self.api_key}", "Accept": "audio/mpeg"},
                timeout=90,
            )
            response.raise_for_status()
            if not response.content:
                raise VoiceProviderError("Voice provider returned empty audio.")
            return response.content
        except httpx.HTTPError as exc:
            raise VoiceProviderError("Speech synthesis provider request failed.") from exc


def provider_from_settings(settings: Settings) -> VoiceProvider | None:
    if not settings.voice_provider_base_url or not settings.voice_provider_api_key:
        return None
    return HttpVoiceProvider(
        settings.voice_provider_base_url,
        settings.voice_provider_api_key.get_secret_value(),
    )
