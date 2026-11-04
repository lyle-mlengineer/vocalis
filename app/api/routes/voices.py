from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentUser, DbSession, OptionalUser
from app.domain import CreditsDebited, VoiceCreated, VoiceRegenerated
from app.models import VoiceRecord
from app.providers.voice import VoiceProviderError
from app.schemas import DeleteResponse, VoiceGenerateRequest, VoiceResponse, VoiceUpdateRequest
from app.services import charge_credits, refund_credits

router = APIRouter(tags=["voices"])
REFERENCE_DIR = Path(__file__).resolve().parents[2] / "data" / "references"


def _guest_id(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="X-Guest-ID must be a UUID.") from exc


def _owned_voice(db: Session, voice_id: str, user_id: str) -> VoiceRecord:
    voice = db.query(VoiceRecord).filter(
        VoiceRecord.id == voice_id,
        VoiceRecord.owner_id == user_id,
    ).one_or_none()
    if voice is None:
        raise HTTPException(status_code=404, detail="Voice not found.")
    return voice


@router.post("/voices/generate", response_model=VoiceResponse, status_code=status.HTTP_201_CREATED)
def generate_voice(
    body: VoiceGenerateRequest,
    request: Request,
    db: DbSession,
    user: OptionalUser,
    x_guest_id: str | None = Header(default=None, alias="X-Guest-ID"),
) -> VoiceResponse:
    guest_id = _guest_id(x_guest_id)
    if user is None and guest_id is None:
        raise HTTPException(status_code=400, detail="Sign in or provide an X-Guest-ID to generate a guest voice.")

    # Guest limitation: only 1 voice per guest session
    if user is None and db.query(VoiceRecord).filter(VoiceRecord.guest_id == guest_id).first():
        raise HTTPException(status_code=409, detail="Guest generation has already been used. Sign in to continue.")

    provider = request.app.state.voice_provider
    if provider is None:
        raise HTTPException(status_code=503, detail="Voice generation provider is not configured.")

    # Skip credit charging for testing
    cost = 0

    print("\n" + "="*60)
    print("VOICE DESIGN PARAMETERS")
    print("="*60)
    print(f"Title: {body.title}")
    print(f"Gender: {body.gender}")
    print(f"Age Range: {body.age_range}")
    print(f"Ethnicity: {body.ethnicity}")
    print(f"Description: {body.description}")
    print("="*60)
    print("Your voice is being designed...")
    print("="*60 + "\n")

    try:
        generated = provider.create_voice(body.model_dump())
        preview_url = request.url_for("references", path=f'{generated.provider_voice_id}.mp3').__str__()
        print(f"Preview URL: {preview_url}")
        record = VoiceRecord(
            owner_id=user.id if user else None,
            guest_id=guest_id if user is None else None,
            title=body.title,
            gender=body.gender,
            age_range=body.age_range,
            ethnicity=body.ethnicity,
            description=body.description,
            provider_voice_id=generated.provider_voice_id,
            preview_url=preview_url,
            status="completed",
        )
        db.add(record)
        db.commit()
        db.refresh(record)
    except VoiceProviderError as exc:
        if user and cost:
            refund_credits(db, user.id, cost, "voice-generation-failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        if user and cost:
            refund_credits(db, user.id, cost, "voice-generation-save-failed")
        raise HTTPException(status_code=409, detail="A voice with this title already exists. Please choose a different title.") from exc
    except Exception:
        db.rollback()
        if user and cost:
            refund_credits(db, user.id, cost, "voice-generation-failed")
        raise
    request.app.state.event_bus.publish(VoiceCreated("voice.created", record.id, record.owner_id))
    return VoiceResponse.model_validate(record)


@router.get("/voices", response_model=list[VoiceResponse])
def list_voices(
    db: DbSession,
    user: OptionalUser,
    x_guest_id: str | None = Header(default=None, alias="X-Guest-ID"),
    status: str | None = None,
) -> list[VoiceResponse]:
    if user:
        query = db.query(VoiceRecord).filter(VoiceRecord.owner_id == user.id)
        if status:
            query = query.filter(VoiceRecord.status == status)
        records = query.order_by(VoiceRecord.created_at.desc()).all()
    else:
        guest_id = _guest_id(x_guest_id)
        if guest_id is None:
            raise HTTPException(status_code=401, detail="Sign in or provide X-Guest-ID.")
        query = db.query(VoiceRecord).filter(VoiceRecord.guest_id == guest_id)
        if status:
            query = query.filter(VoiceRecord.status == status)
        records = query.all()
    return [VoiceResponse.model_validate(record) for record in records]


@router.get("/voices/{voice_id}", response_model=VoiceResponse)
def get_voice(voice_id: str, db: DbSession, user: OptionalUser, x_guest_id: str | None = Header(default=None, alias="X-Guest-ID")) -> VoiceResponse:
    if user:
        record = _owned_voice(db, voice_id, user.id)
    else:
        guest_id = _guest_id(x_guest_id)
        if guest_id is None:
            raise HTTPException(status_code=401, detail="Sign in or provide X-Guest-ID.")
        record = db.query(VoiceRecord).filter(
            VoiceRecord.id == voice_id,
            VoiceRecord.guest_id == guest_id,
        ).one_or_none()
        if record is None:
            raise HTTPException(status_code=404, detail="Voice not found.")
    return VoiceResponse.model_validate(record)


@router.patch("/voices/{voice_id}", response_model=VoiceResponse)
def update_voice(voice_id: str, body: VoiceUpdateRequest, db: DbSession, user: CurrentUser) -> VoiceResponse:
    record = _owned_voice(db, voice_id, user.id)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(record, key, value)
    db.commit()
    db.refresh(record)
    return VoiceResponse.model_validate(record)


@router.post("/voices/{voice_id}/regenerate", response_model=VoiceResponse)
def regenerate_voice(
    voice_id: str,
    body: VoiceGenerateRequest,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> VoiceResponse:
    record = _owned_voice(db, voice_id, user.id)
    provider = request.app.state.voice_provider
    if provider is None:
        raise HTTPException(status_code=503, detail="Voice generation provider is not configured.")

    # Skip credit charging for testing
    cost = 0

    print("\n" + "="*60)
    print("VOICE REGENERATION PARAMETERS")
    print("="*60)
    print(f"Voice ID: {voice_id}")
    print(f"Title: {body.title}")
    print(f"Gender: {body.gender}")
    print(f"Age Range: {body.age_range}")
    print(f"Ethnicity: {body.ethnicity}")
    print(f"Description: {body.description}")
    print("="*60)
    print("Your voice is being regenerated...")
    print("="*60 + "\n")

    try:
        generated = provider.create_voice(body.model_dump())
        record.title = body.title
        record.gender = body.gender
        record.age_range = body.age_range
        record.ethnicity = body.ethnicity
        record.description = body.description
        record.provider_voice_id = generated.provider_voice_id
        record.preview_url = generated.preview_url
        record.status = "completed"
        db.commit()
        db.refresh(record)
    except VoiceProviderError as exc:
        db.rollback()
        refund_credits(db, user.id, cost, f"voice-regeneration-failed:{voice_id}")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        refund_credits(db, user.id, cost, f"voice-regeneration-failed:{voice_id}")
        raise

    request.app.state.event_bus.publish(
        CreditsDebited("credits.debited", user.id, cost, "voice_regeneration")
    )
    request.app.state.event_bus.publish(VoiceRegenerated("voice.regenerated", record.id, user.id))
    return VoiceResponse.model_validate(record)


@router.delete("/voices/{voice_id}", response_model=DeleteResponse)
def delete_voice(voice_id: str, request: Request, db: DbSession, user: CurrentUser) -> DeleteResponse:
    record = _owned_voice(db, voice_id, user.id)
    reference_path = None
    if record.provider_voice_id:
        reference_dir = REFERENCE_DIR.resolve()
        candidate = (reference_dir / f"{record.provider_voice_id}.mp3").resolve()
        if candidate.parent != reference_dir:
            raise HTTPException(status_code=500, detail="Voice reference path is invalid.")
        reference_path = candidate

        provider = request.app.state.voice_provider
        if provider is not None:
            try:
                provider.delete_voice(record.provider_voice_id)
            except VoiceProviderError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc

    db.delete(record)
    db.commit()
    if reference_path is not None:
        try:
            reference_path.unlink(missing_ok=True)
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail="Voice was deleted, but its local reference could not be removed.",
            ) from exc
    return DeleteResponse(deleted=True)


@router.get("/voices/{voice_id}/download")
def download_voice(voice_id: str, db: DbSession, user: CurrentUser):
    record = _owned_voice(db, voice_id, user.id)
    if not record.provider_voice_id:
        raise HTTPException(status_code=404, detail="No downloadable audio is available for this voice.")
    reference_dir = REFERENCE_DIR.resolve()
    reference_path = (reference_dir / f"{record.provider_voice_id}.mp3").resolve()
    if reference_path.parent != reference_dir:
        raise HTTPException(status_code=500, detail="Voice reference path is invalid.")
    if not reference_path.is_file():
        raise HTTPException(status_code=404, detail="Voice reference audio is not available for download.")
    return FileResponse(
        reference_path,
        media_type="audio/mpeg",
        filename=f"{record.id}.mp3",
    )
