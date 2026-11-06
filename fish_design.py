import base64
import os
import requests
from dotenv import load_dotenv
from fishaudio import FishAudio
from fishaudio.types import TTSConfig

# Load environment variables from .env file
load_dotenv()

client = FishAudio(api_key=os.environ['FISH_API_KEY'])

# response = requests.post(
#     "https://api.fish.audio/v1/voice-design",
#     headers={
#         "Authorization": f"Bearer {os.environ['FISH_API_KEY']}",
#         "Content-Type": "application/json",
#         "model": "voice-design-1",
#     },
#     json={
#         "instruction": "Warm, confident studio narrator with a natural tone",
#         "reference_text": "Welcome to Fish Audio.",
#         "language": "en",
#         "n": 1,
#     },
#     timeout=120,
# )
# response.raise_for_status()

# candidate = response.json()["candidates"][0]
# with open("voice.wav", "wb") as f:
#     f.write(base64.b64decode(candidate["audio_base64"]))

# print(candidate["sample_rate"], candidate["duration_ms"])
# print(response.json()["candidates"][0])

audio = client.tts.convert(
    text="High quality",
    config=TTSConfig(format="wav", sample_rate=44100),
)

print(audio)