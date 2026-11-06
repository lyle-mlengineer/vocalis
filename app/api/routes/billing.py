import hmac
from decimal import Decimal
from typing import Literal

import stripe
from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentUser, DbSession
from app.config import get_settings
from app.domain import CREDIT_PACKS
from app.models import AlbumRecord, CreditLedger, PaymentRecord, User, VoiceRecord
from app.providers.mpesa import MpesaClient, MpesaError, amount_matches, callback_url
from app.schemas import (
    CreditBalanceResponse,
    CreditPackResponse,
    LedgerEntryResponse,
    MpesaC2BRequest,
    MpesaCallbackResponse,
    MpesaStkRequest,
    PaymentCreateRequest,
    PaymentResponse,
    WebhookResult,
)
from app.services import get_pack, new_payment_reference, settle_payment

router = APIRouter(tags=["billing"])


def _payment_response(payment: PaymentRecord, instructions: dict[str, str] | None = None) -> PaymentResponse:
    return PaymentResponse(
        id=payment.id,
        pack_id=payment.pack_id,
        amount_kes=payment.amount_kes,
        credits=payment.credits,
        method=payment.method,
        status=payment.status,
        account_reference=payment.account_reference,
        checkout_url=payment.checkout_url,
        qr_code_base64=payment.qr_code_base64,
        instructions=instructions,
        created_at=payment.created_at,
    )


def _new_payment(db: Session, user: User, pack_id: str, method: str) -> PaymentRecord:
    pack = get_pack(pack_id)
    payment = PaymentRecord(
        user_id=user.id,
        pack_id=pack.pack_id,
        amount_kes=int(pack.amount_kes),
        credits=pack.credits,
        method=method,
        status="pending",
        account_reference=new_payment_reference(),
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


def _mark_failed(db: Session, payment: PaymentRecord) -> None:
    payment.status = "failed"
    db.commit()


def _assert_callback_token(token: str) -> None:
    secret = get_settings().mpesa_callback_secret
    if secret is None or not hmac.compare_digest(token, secret.get_secret_value()):
        raise HTTPException(status_code=403, detail="Invalid payment callback token.")


def _mpesa_client() -> MpesaClient:
    try:
        return MpesaClient(get_settings())
    except MpesaError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/credit-packs", response_model=list[CreditPackResponse])
def credit_packs() -> list[CreditPackResponse]:
    return [
        CreditPackResponse(id=pack.pack_id, title=pack.title, credits=pack.credits, amount_kes=pack.amount_kes)
        for pack in CREDIT_PACKS
    ]


@router.get("/credits", response_model=CreditBalanceResponse)
def credit_balance(user: CurrentUser) -> CreditBalanceResponse:
    return CreditBalanceResponse(balance=user.credits_balance)


@router.get("/credits/ledger", response_model=list[LedgerEntryResponse])
def credit_ledger(db: DbSession, user: CurrentUser) -> list[LedgerEntryResponse]:
    entries = (
        db.query(CreditLedger)
        .filter(CreditLedger.user_id == user.id)
        .order_by(CreditLedger.created_at.desc())
        .limit(100)
        .all()
    )
    return [LedgerEntryResponse.model_validate(entry, from_attributes=True) for entry in entries]


@router.get("/dashboard")
def dashboard(db: DbSession, user: CurrentUser) -> dict:
    return {
        "credits_balance": user.credits_balance,
        "voice_count": db.query(VoiceRecord).filter(VoiceRecord.owner_id == user.id).count(),
        "album_count": db.query(AlbumRecord).filter(AlbumRecord.owner_id == user.id).count(),
        "recent_transactions": credit_ledger(db, user)[:5],
    }


@router.get("/payments/{payment_id}", response_model=PaymentResponse)
def get_payment(payment_id: str, db: DbSession, user: CurrentUser) -> PaymentResponse:
    payment = db.query(PaymentRecord).filter(
        PaymentRecord.id == payment_id,
        PaymentRecord.user_id == user.id,
    ).one_or_none()
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found.")
    return _payment_response(payment)


@router.get("/payments", response_model=list[PaymentResponse])
def list_payments(db: DbSession, user: CurrentUser) -> list[PaymentResponse]:
    payments = (
        db.query(PaymentRecord)
        .filter(PaymentRecord.user_id == user.id)
        .order_by(PaymentRecord.created_at.desc())
        .limit(100)
        .all()
    )
    return [_payment_response(payment) for payment in payments]


@router.post("/payments/mpesa/stk", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
def mpesa_stk(body: MpesaStkRequest, db: DbSession, user: CurrentUser) -> PaymentResponse:
    settings = get_settings()
    if not settings.mpesa_callback_url:
        raise HTTPException(status_code=503, detail="Configure MPESA_CALLBACK_URL before accepting payments.")
    client = _mpesa_client()
    payment = _new_payment(db, user, body.pack_id, "mpesa_stk")
    try:
        url = callback_url(
            settings.mpesa_callback_url,
            settings.mpesa_callback_secret.get_secret_value() if settings.mpesa_callback_secret else None,
        )
        result = client.stk_push(body.phone_number, payment.amount_kes, payment.account_reference, url)
    except MpesaError as exc:
        _mark_failed(db, payment)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if str(result.get("ResponseCode")) != "0":
        _mark_failed(db, payment)
        raise HTTPException(status_code=502, detail=result.get("ResponseDescription", "M-Pesa rejected the request."))
    payment.checkout_request_id = result.get("CheckoutRequestID")
    payment.merchant_request_id = result.get("MerchantRequestID")
    db.commit()
    db.refresh(payment)
    return _payment_response(payment)


@router.post("/payments/mpesa/manual", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
def mpesa_manual(
    body: PaymentCreateRequest,
    db: DbSession,
    user: CurrentUser,
    method: Literal["paybill", "till", "qr"] = Query(),
) -> PaymentResponse:
    settings = get_settings()
    if not settings.mpesa_c2b_confirmation_url:
        raise HTTPException(status_code=503, detail="Configure MPESA_C2B_CONFIRMATION_URL before offering manual payments.")
    client = _mpesa_client() if method == "qr" else None
    payment = _new_payment(db, user, body.pack_id, f"mpesa_{method}")
    if method == "qr":
        try:
            qr_code = client.generate_qr(payment.amount_kes, payment.account_reference)
        except MpesaError as exc:
            _mark_failed(db, payment)
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        payment.qr_code_base64 = qr_code
        db.commit()
        db.refresh(payment)
        instructions = {"scan": "Scan the returned M-Pesa QR code and complete the payment."}
    elif method == "paybill":
        if not settings.mpesa_shortcode:
            _mark_failed(db, payment)
            raise HTTPException(status_code=503, detail="Configure MPESA_SHORTCODE before offering Paybill.")
        instructions = {
            "paybill": settings.mpesa_shortcode,
            "account_reference": payment.account_reference,
            "amount_kes": str(payment.amount_kes),
        }
    else:
        if not settings.mpesa_till_number:
            _mark_failed(db, payment)
            raise HTTPException(status_code=503, detail="Configure MPESA_TILL_NUMBER before offering Till.")
        instructions = {
            "till": settings.mpesa_till_number,
            "account_reference": payment.account_reference,
            "amount_kes": str(payment.amount_kes),
        }
    return _payment_response(payment, instructions)


@router.post("/payments/card", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
def card_checkout(body: PaymentCreateRequest, db: DbSession, user: CurrentUser) -> PaymentResponse:
    settings = get_settings()
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Card payments are not configured.")
    payment = _new_payment(db, user, body.pack_id, "card")
    pack = get_pack(body.pack_id)
    try:
        stripe.api_key = settings.stripe_secret_key.get_secret_value()
        checkout = stripe.checkout.Session.create(
            mode="payment",
            success_url=f"{settings.frontend_base_url.rstrip('/')}/billing?payment_id={payment.id}",
            cancel_url=f"{settings.frontend_base_url.rstrip('/')}/billing?cancelled=true",
            client_reference_id=payment.id,
            metadata={"payment_id": payment.id, "user_id": user.id},
            line_items=[
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": "kes",
                        "unit_amount": int(pack.amount_kes * 100),
                        "product_data": {"name": f"{pack.title} Vocalis credits"},
                    },
                }
            ],
        )
    except stripe.StripeError as exc:
        _mark_failed(db, payment)
        raise HTTPException(status_code=502, detail="Card checkout could not be created.") from exc
    payment.stripe_session_id = checkout.id
    payment.checkout_url = checkout.url
    db.commit()
    db.refresh(payment)
    return _payment_response(payment)


@router.post("/webhooks/mpesa/stk", response_model=WebhookResult)
async def mpesa_stk_webhook(request: Request, db: DbSession, token: str = Query()) -> WebhookResult:
    _assert_callback_token(token)
    data = await request.json()
    callback = data.get("Body", {}).get("stkCallback", {})
    checkout_id = callback.get("CheckoutRequestID")
    result_code = callback.get("ResultCode")
    if not isinstance(checkout_id, str):
        raise HTTPException(status_code=400, detail="M-Pesa callback is missing CheckoutRequestID.")
    payment = db.query(PaymentRecord).filter(PaymentRecord.checkout_request_id == checkout_id).one_or_none()
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment for M-Pesa callback was not found.")
    if result_code != 0:
        if payment.status == "pending":
            payment.status = "failed"
            db.commit()
        return WebhookResult(received=True)

    metadata = callback.get("CallbackMetadata", {}).get("Item", [])
    values = {item.get("Name"): item.get("Value") for item in metadata if isinstance(item, dict)}
    amount = values.get("Amount")
    receipt = values.get("MpesaReceiptNumber")
    if amount is None or not amount_matches(Decimal(str(amount)), payment.amount_kes):
        raise HTTPException(status_code=400, detail="M-Pesa payment amount does not match the order.")
    settle_payment(db, payment, receipt_number=str(receipt) if receipt else None)
    return WebhookResult(received=True)


@router.post("/webhooks/mpesa/c2b", response_model=MpesaCallbackResponse)
def mpesa_c2b_webhook(body: MpesaC2BRequest, db: DbSession, token: str = Query()) -> MpesaCallbackResponse:
    _assert_callback_token(token)
    payment = db.query(PaymentRecord).filter(
        PaymentRecord.account_reference == body.BillRefNumber
    ).one_or_none()
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment reference was not found.")
    if payment.status == "paid":
        return MpesaCallbackResponse()
    if payment.method not in {"mpesa_paybill", "mpesa_till", "mpesa_qr"}:
        raise HTTPException(status_code=409, detail="Payment reference is not for a manual M-Pesa payment.")
    if not amount_matches(body.TransAmount, payment.amount_kes):
        raise HTTPException(status_code=400, detail="M-Pesa payment amount does not match the order.")
    settle_payment(db, payment, receipt_number=body.TransID)
    return MpesaCallbackResponse()


@router.post("/webhooks/stripe")
async def stripe_webhook(
    request: Request,
    db: DbSession,
    stripe_signature: str | None = Header(default=None),
) -> Response:
    settings = get_settings()
    if not settings.stripe_webhook_secret or not stripe_signature:
        raise HTTPException(status_code=503, detail="Stripe webhook verification is not configured.")
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(
            payload,
            stripe_signature,
            settings.stripe_webhook_secret.get_secret_value(),
        )
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature or payload.") from exc
    if event["type"] == "checkout.session.completed":
        checkout = event["data"]["object"]
        payment_id = checkout.get("metadata", {}).get("payment_id")
        if checkout.get("payment_status") == "paid" and isinstance(payment_id, str):
            payment = db.get(PaymentRecord, payment_id)
            if payment is not None and payment.stripe_session_id == checkout.get("id"):
                settle_payment(db, payment, receipt_number=checkout.get("payment_intent"))
    return Response(status_code=200)
