import os
from pathlib import Path

from breeze_blue import BreezeBlue, save
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

client = BreezeBlue(api_key=os.environ["BREEZE_API_KEY"])

voice_id: str = 'voc_dmv4t9egp3ma'

# Delete the voice
response = client.voices.delete(voice_id=voice_id)
print(response)