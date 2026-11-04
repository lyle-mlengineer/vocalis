import threading
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import CurrentUser, DbSession
from app.config import get_settings
from app.models import User, VoiceRecord
from app.schemas import AuthResponse, FirebaseLoginRequest, LoginRequest, RegisterRequest, UserResponse
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["authentication"])
_firebase_lock = threading.Lock()


def auth_response(user: User) -> AuthResponse:
    return AuthResponse(
        access_token=create_access_token(user.id),
        user=UserResponse(id=user.id, email=user.email, credits_balance=user.credits_balance),
    )


def _validate_guest_id(guest_id: str | None) -> str | None:
    if guest_id is None:
        return None
    try:
        return str(UUID(guest_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="X-Guest-ID must be a UUID.") from exc


def _claim_guest_voice(db, user: User, guest_id: str | None) -> None:
    if guest_id:
        db.query(VoiceRecord).filter(
            VoiceRecord.guest_id == guest_id,
            VoiceRecord.owner_id.is_(None),
        ).update(
            {VoiceRecord.owner_id: user.id, VoiceRecord.guest_id: None},
            synchronize_session=False,
        )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(
    body: RegisterRequest,
    db: DbSession,
    x_guest_id: str | None = Header(default=None, alias="X-Guest-ID"),
) -> AuthResponse:
    guest_id = _validate_guest_id(x_guest_id)
    user = User(email=str(body.email).lower(), password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.flush()
        _claim_guest_voice(db, user, guest_id)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists.") from exc
    db.refresh(user)
    return auth_response(user)


@router.post("/login", response_model=AuthResponse)
def login(body: LoginRequest, db: DbSession) -> AuthResponse:
    user = db.query(User).filter(User.email == str(body.email).lower()).one_or_none()
    if user is None or user.password_hash is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    return auth_response(user)


@router.post("/firebase", response_model=AuthResponse)
def firebase_login(body: FirebaseLoginRequest, db: DbSession) -> AuthResponse:
    settings = get_settings()
    if not settings.firebase_project_id:
        raise HTTPException(status_code=503, detail="Firebase authentication is not configured.")
    try:
        import firebase_admin
        from firebase_admin import auth, credentials
        from firebase_admin.exceptions import FirebaseError
        from google.auth.exceptions import DefaultCredentialsError
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="Firebase authentication dependencies are unavailable.") from exc

    try:
        with _firebase_lock:
            try:
                firebase_app = firebase_admin.get_app("vocalis")
            except ValueError:
                if settings.firebase_service_account_file:
                    firebase_credential = credentials.Certificate(
                        str(Path(settings.firebase_service_account_file))
                    )
                    firebase_app = firebase_admin.initialize_app(
                        firebase_credential,
                        {"projectId": settings.firebase_project_id},
                        name="vocalis",
                    )
                else:
                    firebase_app = firebase_admin.initialize_app(
                        options={"projectId": settings.firebase_project_id},
                        name="vocalis",
                    )
    except (ValueError, OSError, FirebaseError, DefaultCredentialsError) as exc:
        raise HTTPException(status_code=503, detail="Firebase authentication credentials could not be loaded.") from exc

    try:
        identity = auth.verify_id_token(body.id_token, app=firebase_app)
    except (FirebaseError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Firebase ID token could not be verified.") from exc

    email = identity.get("email")
    uid = identity.get("uid")
    if not isinstance(email, str) or not email or not isinstance(uid, str) or not uid:
        raise HTTPException(status_code=401, detail="Firebase token must include a user email and id.")
    if identity.get("email_verified") is not True:
        raise HTTPException(status_code=403, detail="Verify your Google account email before continuing.")

    user = db.query(User).filter(or_(User.firebase_uid == uid, User.email == email.lower())).one_or_none()
    if user is None:
        user = User(email=email.lower(), firebase_uid=uid)
        db.add(user)
    else:
        user.firebase_uid = uid
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="This Firebase account is linked to another user.") from exc
    db.refresh(user)
    return auth_response(user)


@router.get("/me", response_model=UserResponse)
def me(user: CurrentUser) -> UserResponse:
    return UserResponse(id=user.id, email=user.email, credits_balance=user.credits_balance)
