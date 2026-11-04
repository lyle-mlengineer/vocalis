from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, StringConstraints
from typing import Annotated


class RegisterRequest(BaseModel):
    email: EmailStr
    password: Annotated[str, StringConstraints(min_length=10, max_length=128)]


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class FirebaseLoginRequest(BaseModel):
    id_token: str = Field(min_length=1)


class UserResponse(BaseModel):
    id: str
    email: EmailStr
    credits_balance: int


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class VoiceGenerateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    gender: str = Field(min_length=1, max_length=40)
    age_range: str = Field(min_length=1, max_length=80)
    ethnicity: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=20, max_length=2000)


class VoiceUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    gender: str | None = Field(default=None, min_length=1, max_length=40)
    age_range: str | None = Field(default=None, min_length=1, max_length=80)
    ethnicity: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, min_length=20, max_length=2000)


class VoiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    gender: str
    age_range: str
    ethnicity: str
    description: str
    preview_url: HttpUrl | None
    status: str
    created_at: datetime


class AlbumCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)


class AlbumUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)


class AlbumResponse(BaseModel):
    id: str
    title: str
    description: str
    voice_ids: list[str]
    created_at: datetime


class SpeechRequest(BaseModel):
    voice_id: str
    text: str = Field(min_length=1, max_length=5000)
    speaking_rate: float = Field(default=1.0, ge=0.5, le=2.0)
    volume: float = Field(default=1.0, ge=0.0, le=1.0)
    style: str | None = Field(default=None, max_length=100)


class CreditPackResponse(BaseModel):
    id: str
    title: str
    credits: int
    amount_kes: Decimal


class CreditBalanceResponse(BaseModel):
    balance: int


class LedgerEntryResponse(BaseModel):
    id: str
    delta: int
    balance_after: int
    kind: str
    reference: str | None
    created_at: datetime


class PaymentCreateRequest(BaseModel):
    pack_id: str


class MpesaStkRequest(PaymentCreateRequest):
    phone_number: str = Field(pattern=r"^(?:\+?254|0)?[17]\d{8}$")


class PaymentResponse(BaseModel):
    id: str
    pack_id: str
    amount_kes: int
    credits: int
    method: str
    status: str
    account_reference: str
    checkout_url: HttpUrl | None = None
    qr_code_base64: str | None = None
    instructions: dict[str, str] | None = None
    created_at: datetime


class WebhookResult(BaseModel):
    received: bool


class MpesaCallbackResponse(BaseModel):
    ResultCode: int = 0
    ResultDesc: str = "Accepted"


class MpesaC2BRequest(BaseModel):
    TransID: str
    TransAmount: Decimal
    BillRefNumber: str
    MSISDN: str | None = None


class DeleteResponse(BaseModel):
    deleted: bool
