import os
from breeze_blue import BreezeBlue
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Initialize client (reads BREEZE_API_KEY from environment)
client = BreezeBlue(api_key=os.getenv("BREEZE_API_KEY"))

# Step 1: Design a preview from a text description (no reference audio needed)
design = client.voices.create_design_preview(
    voice_description="A warm, thoughtful young woman with a clear voice and a calm, reflective delivery."
)
generated_voice_id = design["previews"][0]["generated_voice_id"]

# Optional: Stream the preview to audition it
preview_audio = client.voices.stream_preview(generated_voice_id)
preview_audio.save("designed_voice_preview.mp3")

# Step 2: Save the preview as a persistent custom voice
saved_voice = client.voices.save_preview(
    generated_voice_id=generated_voice_id,
    voice_name="My Custom Narrator"
)
voice_id = saved_voice["voice_id"]
print(f"Voice saved successfully! ID: {voice_id}")

# Step 3: Use your new designed voice for Text-to-Speech
audio = client.text_to_speech.convert(
    voice_id=voice_id,
    text="(sigh) Welcome aboard. Our journey begins now.",  # Supports inline tags like (sigh) or (laugh)
    output_format="mp3"
)
save(audio, "final_output.mp3")