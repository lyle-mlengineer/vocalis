from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentUser, DbSession, OptionalUser
from app.domain import CreditsDebited, VoiceCreated, VoiceRegenerated
from app.models import VoiceRecord
from app.providers.voice import VoiceProviderError
from app.schemas import DeleteResponse, VoiceGenerateRequest, VoiceResponse, VoiceUpdateRequest
from app.services import charge_credits, refund_credits

router = APIRouter(tags=["voices"])


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
    if user is None and db.query(VoiceRecord).filter(VoiceRecord.guest_id == guest_id).first():
        raise HTTPException(status_code=409, detail="Guest generation has already been used. Sign in to continue.")

    provider = request.app.state.voice_provider
    if provider is None:
        raise HTTPException(status_code=503, detail="Voice generation provider is not configured.")

    settings = request.app.state.settings
    cost = settings.voice_generation_credit_cost if user else 0
    if user:
        charge_credits(db, user, cost, "voice_generation")

    try:
        generated = provider.create_voice(body.model_dump())
        record = VoiceRecord(
            owner_id=user.id if user else None,
            guest_id=guest_id if user is None else None,
            title=body.title,
            gender=body.gender,
            age_range=body.age_range,
            ethnicity=body.ethnicity,
            description=body.description,
            provider_voice_id=generated.provider_voice_id,
            preview_url=generated.preview_url,
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
        raise HTTPException(status_code=409, detail="A guest voice was already generated for this session.") from exc
    except Exception:
        db.rollback()
        if user and cost:
            refund_credits(db, user.id, cost, "voice-generation-failed")
        raise

    if user and cost:
        request.app.state.event_bus.publish(
            CreditsDebited("credits.debited", user.id, cost, "voice_generation")
        )
    request.app.state.event_bus.publish(VoiceCreated("voice.created", record.id, record.owner_id))
    return VoiceResponse.model_validate(record)


@router.get("/voices", response_model=list[VoiceResponse])
def list_voices(
    db: DbSession,
    user: OptionalUser,
    x_guest_id: str | None = Header(default=None, alias="X-Guest-ID"),
) -> list[VoiceResponse]:
    if user:
        records = db.query(VoiceRecord).filter(VoiceRecord.owner_id == user.id).order_by(VoiceRecord.created_at.desc()).all()
    else:
        guest_id = _guest_id(x_guest_id)
        if guest_id is None:
            raise HTTPException(status_code=401, detail="Sign in or provide X-Guest-ID.")
        records = db.query(VoiceRecord).filter(VoiceRecord.guest_id == guest_id).all()
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

    cost = request.app.state.settings.voice_generation_credit_cost
    charge_credits(db, user, cost, "voice_regeneration", voice_id)
    try:
        generated = provider.create_voice(body.model_dump())
        record.title = body.title
        record.gender = body.gender
        record.age_range = body.age_range
        record.ethnicity = body.ethnicity
        record.description = body.description
        record.provider_voice_id = generated.provider_voice_id
        record.preview_url = generated.preview_url
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
def delete_voice(voice_id: str, db: DbSession, user: CurrentUser) -> DeleteResponse:
    record = _owned_voice(db, voice_id, user.id)
    db.delete(record)
    db.commit()
    return DeleteResponse(deleted=True)


@router.get("/voices/{voice_id}/download")
def download_voice(voice_id: str, db: DbSession, user: CurrentUser):
    record = _owned_voice(db, voice_id, user.id)
    if not record.preview_url:
        raise HTTPException(status_code=404, detail="No downloadable audio is available for this voice.")
    return RedirectResponse(record.preview_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
