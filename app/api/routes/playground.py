from fastapi import APIRouter, HTTPException, Request, Response

from app.api.dependencies import CurrentUser, DbSession
from app.models import VoiceRecord
from app.schemas import SpeechRequest

router = APIRouter(prefix="/playground", tags=["playground"])


@router.post("/speech")
def synthesize_speech(
    body: SpeechRequest,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> Response:
    voice = db.query(VoiceRecord).filter(
        VoiceRecord.id == body.voice_id,
        VoiceRecord.owner_id == user.id,
    ).one_or_none()
    if voice is None:
        raise HTTPException(status_code=404, detail="Voice not found.")

    # Skip credit charging for testing
    cost = 0

    print("\n" + "="*60)
    print("SPEECH GENERATION PARAMETERS")
    print("="*60)
    print(f"Voice ID: {body.voice_id}")
    print(f"Voice Title: {voice.title}")
    print(f"Text: {body.text}")
    print(f"Speaking Rate: {body.speaking_rate}")
    print(f"Volume: {body.volume}")
    print(f"Style: {body.style}")
    print("="*60)
    print("Your speech is being generated...")
    print("="*60 + "\n")

    return Response(content=b"", media_type="audio/mpeg")
