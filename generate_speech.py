import os
from pathlib import Path

from breeze_blue import BreezeBlue, save
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

client = BreezeBlue(api_key=os.environ["BREEZE_API_KEY"])

voice_id: str = 'voc_dmv4t9egp3ma'

audio = client.text_to_speech.convert(
    voice_id=voice_id,
    text="I can't believe you brought him here!",
    output_format="mp3",
)

save(audio, Path("surprise.mp3"))

audio_bytes: bytes = audio.content
content_type: str = audio.content_type