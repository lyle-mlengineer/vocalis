from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentUser, DbSession, OptionalUser
from app.domain import VoiceCreated, VoiceRegenerated
from app.models import VoiceRecord
from app.schemas import DeleteResponse, VoiceGenerateRequest, VoiceResponse, VoiceUpdateRequest

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

    # Guest limitation: only 1 voice per guest session
    if user is None and db.query(VoiceRecord).filter(VoiceRecord.guest_id == guest_id).first():
        raise HTTPException(status_code=409, detail="Guest generation has already been used. Sign in to continue.")

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
        record = VoiceRecord(
            owner_id=user.id if user else None,
            guest_id=guest_id if user is None else None,
            title=body.title,
            gender=body.gender,
            age_range=body.age_range,
            ethnicity=body.ethnicity,
            description=body.description,
            provider_voice_id=None,
            preview_url=None,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
    except IntegrityError as exc:
        db.rollback()
        # raise HTTPException(status_code=409, detail="A guest voice was already generated for this session.") from exc
        raise HTTPException(status_code=409, detail="Database integrity error.") from exc
    except Exception:
        db.rollback()
        raise
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
        record.title = body.title
        record.gender = body.gender
        record.age_range = body.age_range
        record.ethnicity = body.ethnicity
        record.description = body.description
        record.provider_voice_id = None
        record.preview_url = None
        db.commit()
        db.refresh(record)
    except Exception:
        db.rollback()
        raise
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
