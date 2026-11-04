from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentUser, DbSession
from app.domain import Album, AlbumVoiceAdded
from app.models import AlbumRecord, VoiceRecord
from app.schemas import AlbumCreateRequest, AlbumResponse, AlbumUpdateRequest, DeleteResponse

router = APIRouter(prefix="/albums", tags=["albums"])


def _owned_album(db: Session, album_id: str, user_id: str) -> AlbumRecord:
    album = db.query(AlbumRecord).filter(
        AlbumRecord.id == album_id,
        AlbumRecord.owner_id == user_id,
    ).one_or_none()
    if album is None:
        raise HTTPException(status_code=404, detail="Album not found.")
    return album


def _response(album: AlbumRecord) -> AlbumResponse:
    return AlbumResponse(
        id=album.id,
        title=album.title,
        description=album.description,
        voice_ids=sorted(voice.id for voice in album.voices),
        created_at=album.created_at,
    )


@router.post("", response_model=AlbumResponse, status_code=status.HTTP_201_CREATED)
def create_album(body: AlbumCreateRequest, db: DbSession, user: CurrentUser) -> AlbumResponse:
    album = AlbumRecord(owner_id=user.id, title=body.title, description=body.description)
    db.add(album)
    db.commit()
    db.refresh(album)
    return _response(album)


@router.get("", response_model=list[AlbumResponse])
def list_albums(db: DbSession, user: CurrentUser) -> list[AlbumResponse]:
    albums = db.query(AlbumRecord).filter(AlbumRecord.owner_id == user.id).order_by(AlbumRecord.created_at.desc()).all()
    return [_response(album) for album in albums]


@router.get("/{album_id}", response_model=AlbumResponse)
def get_album(album_id: str, db: DbSession, user: CurrentUser) -> AlbumResponse:
    return _response(_owned_album(db, album_id, user.id))


@router.patch("/{album_id}", response_model=AlbumResponse)
def update_album(album_id: str, body: AlbumUpdateRequest, db: DbSession, user: CurrentUser) -> AlbumResponse:
    album = _owned_album(db, album_id, user.id)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(album, key, value)
    db.commit()
    db.refresh(album)
    return _response(album)


@router.delete("/{album_id}", response_model=DeleteResponse)
def delete_album(album_id: str, db: DbSession, user: CurrentUser) -> DeleteResponse:
    album = _owned_album(db, album_id, user.id)
    db.delete(album)
    db.commit()
    return DeleteResponse(deleted=True)


@router.post("/{album_id}/voices/{voice_id}", response_model=AlbumResponse)
def add_voice(
    album_id: str,
    voice_id: str,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> AlbumResponse:
    album_record = _owned_album(db, album_id, user.id)
    voice_record = db.query(VoiceRecord).filter(
        VoiceRecord.id == voice_id,
        VoiceRecord.owner_id == user.id,
    ).one_or_none()
    if voice_record is None:
        raise HTTPException(status_code=404, detail="Voice not found.")

    album = Album(
        album_id=album_record.id,
        owner_id=album_record.owner_id,
        title=album_record.title,
        description=album_record.description,
        voice_ids={voice.id for voice in album_record.voices},
    )
    album.add_voice(voice_id)
    if voice_record not in album_record.voices:
        album_record.voices.append(voice_record)
        db.commit()
        for event in album.events:
            request.app.state.event_bus.publish(event)
    return _response(album_record)


@router.delete("/{album_id}/voices/{voice_id}", response_model=AlbumResponse)
def remove_voice(album_id: str, voice_id: str, db: DbSession, user: CurrentUser) -> AlbumResponse:
    album = _owned_album(db, album_id, user.id)
    voice = next((item for item in album.voices if item.id == voice_id), None)
    if voice is None:
        raise HTTPException(status_code=404, detail="Voice is not in this album.")
    album.voices.remove(voice)
    db.commit()
    return _response(album)
