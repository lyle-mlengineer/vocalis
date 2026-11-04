import base64
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote
from pathlib import Path
from fishaudio import TTSConfig
import requests
import os
from uuid import uuid4


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

    def delete_voice(self, provider_voice_id: str) -> None: ...


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

    def delete_voice(self, provider_voice_id: str) -> None:
        try:
            response = httpx.delete(
                f"{self.base_url}/voices/{quote(provider_voice_id, safe='')}",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=30,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise VoiceProviderError("Voice deletion provider request failed.") from exc


class BreezeVoiceProvider:
    """Adapter for Breeze Blue TTS API."""

    def __init__(self, api_key: str):
        try:
            from breeze_blue import BreezeBlue
            self.client = BreezeBlue(api_key=api_key)
        except ImportError as exc:
            raise VoiceProviderError("breeze_blue library is not installed. Please install it to use Breeze TTS.") from exc

    def create_voice(self, specification: dict) -> GeneratedVoice:
        """Create a voice using Breeze's design preview and save workflow."""
        try:
            # Build voice description from specification
            description_parts = []
            if specification.get("gender"):
                description_parts.append(f"{specification['gender']}")
            if specification.get("age_range"):
                description_parts.append(f"{specification['age_range']}")
            if specification.get("ethnicity"):
                description_parts.append(f"{specification['ethnicity']}")
            if specification.get("description"): 
                description_parts.append(specification["description"])
            
            voice_description = ". ".join(description_parts)
            voice_name = specification.get("title", "Untitled Voice")

            print(f"Breeze: Creating voice with description: {voice_description}")


            # Step 1: Create design preview - try without language first (as per original example)
            try:
                design = self.client.voices.create_design_preview(
                    voice_description=specification.get("description")
                )
                print(f"Breeze: Design preview created successfully")
            except Exception as e:
                print(f"Breeze: Error creating design preview: {e}")
                # Try with language parameter
                try:
                    design = self.client.voices.create_design_preview(
                        voice_description=specification.get("description"),
                        language="en"
                    )
                    print(f"Breeze: Design preview created with language parameter")
                except Exception as e2:
                    print(f"Breeze: Error with language parameter: {e2}")
                    raise VoiceProviderError(f"Breeze API error: {str(e2)}") from e2
            
            # print(f"Breeze: Design response: {design}")
            print("Breeze: Design response keys:", list(design.keys()))
            
            if not design.get("previews") or len(design["previews"]) == 0:
                raise VoiceProviderError("Breeze API returned no preview in design response.")
            
            generated_voice_id = design["previews"][0]["generated_voice_id"]
            print(f"Breeze: Generated voice ID: {generated_voice_id}")

            # Step 2: Get the generated voice
            preview_audio = self.client.voices.stream_preview(generated_voice_id)
            print(f"Breeze: Downloaded generated voice: {generated_voice_id}")

            # Step 3: Save the generated voice locally
            parent_dir = Path(__file__).parent.parent
            reference_dir = parent_dir / "data" / "references"
            save_path: Path = reference_dir / f"{generated_voice_id}.mp3"
            print(f"Breeze: Saving to: {save_path}")
            preview_audio.save(str(save_path))
            print(f"Breeze: Saved successfully")

            # Step 4: Save the preview as a persistent custom voice
            print(f"Breeze: Saving voice preview with name: {voice_name}")
            preview = self.client.voices.create_clone_preview(
                name=voice_name,
                file=Path(save_path),
            )
            generated_voice_id = preview["generated_voice_id"]
            print(f"Breeze: Saved preview: {voice_name}")

            # Step 5: Save the preview as a voice
            print(f"Breeze: Saving voice with name: {voice_name}")
            voice = self.client.voices.save_preview(
                generated_voice_id=generated_voice_id,
                voice_name=voice_name,
                language_code="en",
            )
            voice_id = voice["voice_id"]
            print(f"Breeze: Saved voice with voice name: {voice_name} and voice id: {voice_id}")

            # Step 6: Rename the voice
            new_save_path: Path = reference_dir / f"{voice_id}.mp3"
            print(f"Renaming: {save_path} to: {new_save_path}")
            save_path.rename(new_save_path)
            print("Renamed successfully!")
            
            # Return None for preview_url since we're using local files
            return GeneratedVoice(provider_voice_id=voice_id, preview_url=None)
            
        except Exception as exc:
            if isinstance(exc, VoiceProviderError):
                raise
            raise VoiceProviderError(f"Breeze voice creation failed: {str(exc)}") from exc

    def synthesize(self, provider_voice_id: str, text: str, settings: dict) -> bytes:
        """Synthesize speech using Breeze TTS."""
        try:
            # Extract settings with defaults
            output_format = settings.get("output_format", "mp3")
            
            # Generate audio
            audio = self.client.text_to_speech.convert(
                voice_id=provider_voice_id,
                text=text,
                output_format=output_format
            )
            
            return audio.content
                    
        except Exception as exc:
            if isinstance(exc, VoiceProviderError):
                raise
            raise VoiceProviderError(f"Breeze speech synthesis failed: {str(exc)}") from exc

    def delete_voice(self, provider_voice_id: str) -> None:
        """Delete a voice using Breeze TTS."""
        try:
            result = self.client.voices.delete(voice_id=provider_voice_id)
            print(f"Breeze: Deleted voice with ID: {provider_voice_id}, result: {result}")
        except Exception as exc:
            if isinstance(exc, VoiceProviderError):
                raise
            raise VoiceProviderError(f"Breeze voice deletion failed: {str(exc)}") from exc


class FishVoiceProvider:
    """Adapter for Fish TTS API."""

    def __init__(self, api_key: str):
        from fishaudio import FishAudio

        self.client = FishAudio(api_key=api_key)
        self.api_key = api_key

    def create_voice(self, specification: dict) -> GeneratedVoice:
        """Create a voice using Fish TTS."""
        try:
            # Build voice description from specification
            description_parts = []
            if specification.get("gender"):
                description_parts.append(f"{specification['gender']}")
            if specification.get("age_range"):
                description_parts.append(f"{specification['age_range']}")
            if specification.get("ethnicity"):
                description_parts.append(f"{specification['ethnicity']}")
            if specification.get("description"): 
                description_parts.append(specification["description"])
            
            voice_description = ". ".join(description_parts)
            voice_name = specification.get("title", "Untitled Voice")

            print(f"Breeze: Creating voice with description: {voice_description}")


            response = requests.post(
                "https://api.fish.audio/v1/voice-design",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "model": "voice-design-1",
                },
                json={
                    "instruction": "Warm, confident studio narrator with a natural tone",
                    "reference_text": "Welcome to Fish Audio.",
                    "language": "en",
                    "n": 1,
                },
                timeout=120,
            )
            response.raise_for_status()

            candidate = response.json()["candidates"][0]
            temp_id: str = str(uuid4())
            parent_dir = Path(__file__).parent.parent
            reference_dir = parent_dir / "data" / "references"
            save_path: Path = reference_dir / f"{temp_id}.wav"
            with open(str(save_path), "wb") as f:
                f.write(base64.b64decode(candidate["audio_base64"]))

            voice = None

            with open(str(save_path), "rb") as f:
                voice = self.client.voices.create(
                    title=voice_name,
                    voices=[f.read()],
                    description=specification.get("description"),
                    visibility="private",
                )

            voice_id = voice.id
            print(f"Fish: Saved voice with voice name: {voice_name} and voice id: {voice_id}")

            # Step 6: Rename the voice
            new_save_path: Path = reference_dir / f"{voice_id}.wav"
            print(f"Renaming: {save_path} to: {new_save_path}")
            save_path.rename(new_save_path)
            print("Renamed successfully!")
            
            # Return None for preview_url since we're using local files
            return GeneratedVoice(provider_voice_id=voice_id, preview_url=None)
            
        except Exception as exc:
            if isinstance(exc, VoiceProviderError):
                raise
            raise VoiceProviderError(f"Breeze voice creation failed: {str(exc)}") from exc

    def synthesize(self, provider_voice_id: str, text: str, settings: dict) -> bytes:
        """Synthesize speech using Breeze TTS."""
        try:
            # Extract settings with defaults
            output_format = settings.get("output_format", "mp3")
            
            # Generate audio
            audio = self.client.tts.convert(
                text=text,
                reference_id=provider_voice_id,
                config=TTSConfig(format=output_format)
            )
            
            return audio
                    
        except Exception as exc:
            if isinstance(exc, VoiceProviderError):
                raise
            raise VoiceProviderError(f"Breeze speech synthesis failed: {str(exc)}") from exc

    def delete_voice(self, provider_voice_id: str) -> None:
        """Delete a voice using Breeze TTS."""
        try:
            result = self.client.voices.delete(voice_id=provider_voice_id)
            print(f"Breeze: Deleted voice with ID: {provider_voice_id}, result: {result}")
        except Exception as exc:
            if isinstance(exc, VoiceProviderError):
                raise
            raise VoiceProviderError(f"Breeze voice deletion failed: {str(exc)}") from exc


def provider_from_settings(settings: Settings) -> VoiceProvider | None:
    # Check for Breeze API key first
    if hasattr(settings, 'breeze_api_key') and settings.breeze_api_key:
        return BreezeVoiceProvider(settings.breeze_api_key.get_secret_value())

    if hasattr(settings, 'fish_api_key') and settings.fish_api_key:
            return FishVoiceProvider(settings.fish_api_key.get_secret_value())

    # Fall back to HTTP provider
    if not settings.voice_provider_base_url or not settings.voice_provider_api_key:
        return None
    return HttpVoiceProvider(
        settings.voice_provider_base_url,
        settings.voice_provider_api_key.get_secret_value(),
    )
