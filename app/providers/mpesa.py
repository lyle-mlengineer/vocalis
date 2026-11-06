import base64
from datetime import datetime
from decimal import Decimal

import httpx

from app.config import Settings


class MpesaError(RuntimeError):
    pass


class MpesaClient:
    def __init__(self, settings: Settings):
        required = (
            settings.mpesa_consumer_key,
            settings.mpesa_consumer_secret,
            settings.mpesa_shortcode,
            settings.mpesa_passkey,
        )
        if any(value is None for value in required):
            raise MpesaError("M-Pesa credentials are not configured.")
        self.settings = settings
        self.shortcode = settings.mpesa_shortcode
        self.base_url = settings.mpesa_base_url

    def _access_token(self) -> str:
        try:
            response = httpx.get(
                f"{self.base_url}/oauth/v1/generate",
                params={"grant_type": "client_credentials"},
                auth=(
                    self.settings.mpesa_consumer_key.get_secret_value(),
                    self.settings.mpesa_consumer_secret.get_secret_value(),
                ),
                timeout=20,
            )
            response.raise_for_status()
            token = response.json().get("access_token")
            if not isinstance(token, str) or not token:
                raise MpesaError("M-Pesa OAuth response did not contain an access token.")
            return token
        except (httpx.HTTPError, ValueError) as exc:
            raise MpesaError("Could not authenticate with M-Pesa.") from exc

    def stk_push(self, phone: str, amount: int, reference: str, callback_url: str) -> dict:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        password = base64.b64encode(
            f"{self.shortcode}{self.settings.mpesa_passkey.get_secret_value()}{timestamp}".encode()
        ).decode()
        phone = phone.removeprefix("+")
        if phone.startswith("0"):
            phone = f"254{phone[1:]}"
        elif phone.startswith("7") or phone.startswith("1"):
            phone = f"254{phone}"
        payload = {
            "BusinessShortCode": self.shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": amount,
            "PartyA": phone,
            "PartyB": self.shortcode,
            "PhoneNumber": phone,
            "CallBackURL": callback_url,
            "AccountReference": reference[:12],
            "TransactionDesc": "Vocalis credits",
        }
        return self._post("/mpesa/stkpush/v1/processrequest", payload)

    def generate_qr(self, amount: int, reference: str) -> str:
        trx_code = "BG" if self.settings.mpesa_merchant_type == "till" else "PB"
        cpi = self.settings.mpesa_till_number if trx_code == "BG" else self.shortcode
        if not cpi:
            raise MpesaError("Configure MPESA_TILL_NUMBER for QR payments by till.")
        payload = {
            "MerchantName": "Vocalis",
            "RefNo": reference[:12],
            "Amount": amount,
            "TrxCode": trx_code,
            "CPI": cpi,
            "Size": "300",
        }
        result = self._post("/mpesa/qrcode/v1/generate", payload)
        qr_code = result.get("QRCode")
        if not isinstance(qr_code, str) or not qr_code:
            raise MpesaError("M-Pesa QR response did not contain a QR code.")
        return qr_code

    def _post(self, path: str, payload: dict) -> dict:
        try:
            response = httpx.post(
                f"{self.base_url}{path}",
                json=payload,
                headers={"Authorization": f"Bearer {self._access_token()}"},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise MpesaError("M-Pesa returned an invalid response.")
            return data
        except (httpx.HTTPError, ValueError) as exc:
            raise MpesaError("M-Pesa request failed.") from exc


def callback_url(base_url: str, secret: str | None) -> str:
    if not secret:
        raise MpesaError("Configure MPESA_CALLBACK_SECRET before accepting M-Pesa payments.")
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}token={secret}"


def amount_matches(amount: Decimal, expected: int) -> bool:
    return amount == Decimal(expected)
