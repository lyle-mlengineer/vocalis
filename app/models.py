from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Column,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


album_voices = Table(
    "album_voices",
    Base.metadata,
    Column("album_id", ForeignKey("albums.id", ondelete="CASCADE"), primary_key=True),
    Column("voice_id", ForeignKey("voices.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    firebase_uid: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    credits_balance: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    voices: Mapped[list["VoiceRecord"]] = relationship(back_populates="owner", cascade="all, delete-orphan")
    albums: Mapped[list["AlbumRecord"]] = relationship(back_populates="owner", cascade="all, delete-orphan")


class VoiceRecord(Base):
    __tablename__ = "voices"
    __table_args__ = (UniqueConstraint("guest_id", name="uq_voices_guest_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    guest_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(100))
    gender: Mapped[str] = mapped_column(String(40))
    age_range: Mapped[str] = mapped_column(String(80))
    ethnicity: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    provider_voice_id: Mapped[str] = mapped_column(String(255))
    preview_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    owner: Mapped[User | None] = relationship(back_populates="voices")
    albums: Mapped[list["AlbumRecord"]] = relationship(secondary=album_voices, back_populates="voices")


class AlbumRecord(Base):
    __tablename__ = "albums"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    owner: Mapped[User] = relationship(back_populates="albums")
    voices: Mapped[list[VoiceRecord]] = relationship(secondary=album_voices, back_populates="albums")


class CreditLedger(Base):
    __tablename__ = "credit_ledger"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    delta: Mapped[int] = mapped_column(Integer)
    balance_after: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))
    reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class PaymentRecord(Base):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    pack_id: Mapped[str] = mapped_column(String(40))
    amount_kes: Mapped[int] = mapped_column(Integer)
    credits: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    account_reference: Mapped[str] = mapped_column(String(64), unique=True)
    checkout_request_id: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    merchant_request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    stripe_session_id: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    checkout_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    qr_code_base64: Mapped[str | None] = mapped_column(Text, nullable=True)
    receipt_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
