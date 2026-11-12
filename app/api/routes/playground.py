import math

from fastapi import APIRouter, HTTPException, Request, Response

from app.api.dependencies import CurrentUser, DbSession
from app.domain import CreditsDebited
from app.models import VoiceRecord
from app.providers.voice import VoiceProviderError
from app.schemas import SpeechRequest
from app.services import charge_credits, refund_credits

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
    provider = request.app.state.voice_provider
    if provider is None:
        raise HTTPException(status_code=503, detail="Voice generation provider is not configured.")

    settings = request.app.state.settings
    cost = max(1, math.ceil(len(body.text) / 1000)) * settings.speech_credits_per_1000_chars
    if cost:
        charge_credits(db, user, cost, "speech_synthesis")

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

    try:
        audio = provider.synthesize(
            voice.provider_voice_id,
            body.text,
            {
                "speaking_rate": body.speaking_rate,
                "volume": body.volume,
                "style": body.style,
            },
        )
    except VoiceProviderError as exc:
        if cost:
            refund_credits(db, user.id, cost, f"speech-failed:{voice.id}")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        if cost:
            refund_credits(db, user.id, cost, f"speech-failed:{voice.id}")
        raise

    request.app.state.event_bus.publish(
        CreditsDebited("credits.debited", user.id, cost, "speech_synthesis")
    )
    return Response(content=audio, media_type="audio/mpeg")
