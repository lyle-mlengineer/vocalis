<<<<<<< HEAD
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain import CREDIT_PACKS, CreditPack
from app.models import CreditLedger, PaymentRecord, User


def get_pack(pack_id: str) -> CreditPack:
    for pack in CREDIT_PACKS:
        if pack.pack_id == pack_id:
            return pack
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credit pack not found.")


def charge_credits(db: Session, user: User, amount: int, kind: str, reference: str | None = None) -> None:
    if amount <= 0:
        raise ValueError("Debit amount must be positive.")

    result = db.execute(
        update(User)
        .where(User.id == user.id)
        .values(credits_balance=User.credits_balance - amount)
        .returning(User.credits_balance)
    )
    balance_after = result.scalar_one_or_none()
    if balance_after is None:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    db.add(
        CreditLedger(
            user_id=user.id,
            delta=-amount,
            balance_after=balance_after,
            kind=kind,
            reference=reference,
        )
    )
    db.commit()
    db.refresh(user)


def credit_user(db: Session, user_id: str, amount: int, kind: str, reference: str | None = None) -> None:
    if amount <= 0:
        raise ValueError("Credit amount must be positive.")
    result = db.execute(
        update(User)
        .where(User.id == user_id)
        .values(credits_balance=User.credits_balance + amount)
        .returning(User.credits_balance)
    )
    balance_after = result.scalar_one_or_none()
    if balance_after is None:
        raise ValueError("Credit account was not found.")
    db.add(
        CreditLedger(
            user_id=user_id,
            delta=amount,
            balance_after=balance_after,
            kind=kind,
            reference=reference,
        )
    )


def refund_credits(db: Session, user_id: str, amount: int, reference: str) -> None:
    credit_user(db, user_id, amount, "refund", reference)
    db.commit()


def settle_payment(
    db: Session,
    payment: PaymentRecord,
    *,
    receipt_number: str | None = None,
) -> bool:
    result = db.execute(
        update(PaymentRecord)
        .where(PaymentRecord.id == payment.id, PaymentRecord.status == "pending")
        .values(status="paid", receipt_number=receipt_number)
    )
    if result.rowcount != 1:
        db.rollback()
        return False
    result = db.execute(
        update(User)
        .where(User.id == payment.user_id)
        .values(credits_balance=User.credits_balance + payment.credits)
        .returning(User.credits_balance)
    )
    balance_after = result.scalar_one_or_none()
    if balance_after is None:
        raise ValueError("Payment owner was not found.")
    db.add(
        CreditLedger(
            user_id=payment.user_id,
            delta=payment.credits,
            balance_after=balance_after,
            kind="purchase",
            reference=payment.id,
        )
    )
    db.commit()
    db.refresh(payment)
    return True


def new_payment_reference() -> str:
    return uuid4().hex[:12].upper()
=======
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain import CREDIT_PACKS, CreditPack
from app.models import CreditLedger, PaymentRecord, User


def get_pack(pack_id: str) -> CreditPack:
    for pack in CREDIT_PACKS:
        if pack.pack_id == pack_id:
            return pack
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credit pack not found.")


def charge_credits(db: Session, user: User, amount: int, kind: str, reference: str | None = None) -> None:
    if amount <= 0:
        raise ValueError("Debit amount must be positive.")

    result = db.execute(
        update(User)
        .where(User.id == user.id)
        .values(credits_balance=User.credits_balance - amount)
        .returning(User.credits_balance)
    )
    balance_after = result.scalar_one_or_none()
    if balance_after is None:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    db.add(
        CreditLedger(
            user_id=user.id,
            delta=-amount,
            balance_after=balance_after,
            kind=kind,
            reference=reference,
        )
    )
    db.commit()
    db.refresh(user)


def credit_user(db: Session, user_id: str, amount: int, kind: str, reference: str | None = None) -> None:
    if amount <= 0:
        raise ValueError("Credit amount must be positive.")
    result = db.execute(
        update(User)
        .where(User.id == user_id)
        .values(credits_balance=User.credits_balance + amount)
        .returning(User.credits_balance)
    )
    balance_after = result.scalar_one_or_none()
    if balance_after is None:
        raise ValueError("Credit account was not found.")
    db.add(
        CreditLedger(
            user_id=user_id,
            delta=amount,
            balance_after=balance_after,
            kind=kind,
            reference=reference,
        )
    )


def refund_credits(db: Session, user_id: str, amount: int, reference: str) -> None:
    credit_user(db, user_id, amount, "refund", reference)
    db.commit()


def settle_payment(
    db: Session,
    payment: PaymentRecord,
    *,
    receipt_number: str | None = None,
) -> bool:
    result = db.execute(
        update(PaymentRecord)
        .where(PaymentRecord.id == payment.id, PaymentRecord.status == "pending")
        .values(status="paid", receipt_number=receipt_number)
    )
    if result.rowcount != 1:
        db.rollback()
        return False
    result = db.execute(
        update(User)
        .where(User.id == payment.user_id)
        .values(credits_balance=User.credits_balance + payment.credits)
        .returning(User.credits_balance)
    )
    balance_after = result.scalar_one_or_none()
    if balance_after is None:
        raise ValueError("Payment owner was not found.")
    db.add(
        CreditLedger(
            user_id=payment.user_id,
            delta=payment.credits,
            balance_after=balance_after,
            kind="purchase",
            reference=payment.id,
        )
    )
    db.commit()
    db.refresh(payment)
    return True


def new_payment_reference() -> str:
    return uuid4().hex[:12].upper()
>>>>>>> c5c55290575735360adacb87281c2854b91419d0
