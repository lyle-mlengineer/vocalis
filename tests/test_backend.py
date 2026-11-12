import pytest
from fastapi.testclient import TestClient

from app.api.routes import voices as voice_routes
from app.domain import Album, CreditAccount
from app.main import create_app
from app.models import CreditLedger, PaymentRecord, User, VoiceRecord
from app.providers.voice import GeneratedVoice
from app.services import charge_credits, settle_payment


class FakeVoiceProvider:
    def __init__(self):
        self.deleted_voice_ids = []

    def create_voice(self, specification: dict) -> GeneratedVoice:
        return GeneratedVoice("provider-voice-1", "https://audio.example.test/preview.mp3")

    def synthesize(self, provider_voice_id: str, text: str, settings: dict) -> bytes:
        return b"test-audio"

    def delete_voice(self, provider_voice_id: str) -> None:
        self.deleted_voice_ids.append(provider_voice_id)


@pytest.fixture
def client():
    application = create_app(
        database_url="sqlite://",
        voice_provider=FakeVoiceProvider(),
    )
    with TestClient(application) as test_client:
        yield test_client


def register(client: TestClient, email: str = "person@example.com") -> tuple[dict, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct horse battery"},
    )
    assert response.status_code == 201
    result = response.json()
    return result, result["access_token"]


def test_guest_can_generate_once_then_claim_voice(client: TestClient, monkeypatch, tmp_path):
    reference_dir = tmp_path / "references"
    reference_dir.mkdir()
    (reference_dir / "provider-voice-1.mp3").write_bytes(b"guest audio")
    monkeypatch.setattr(voice_routes, "REFERENCE_DIR", reference_dir)

    guest_id = "d1f6c650-79f8-44c8-8ea4-c548ee7166e3"
    payload = {
        "title": "Narrator",
        "gender": "woman",
        "age_range": "adult",
        "ethnicity": "East African",
        "description": "Warm, clear narration with a gentle Kenyan accent.",
    }
    response = client.post(
        "/api/v1/voices/generate",
        headers={"X-Guest-ID": guest_id},
        json=payload,
    )
    assert response.status_code == 201
    voice_id = response.json()["id"]
    assert client.post(
        "/api/v1/voices/generate",
        headers={"X-Guest-ID": guest_id},
        json=payload,
    ).status_code == 409

    claimed = client.post(
        "/api/v1/auth/register",
        headers={"X-Guest-ID": guest_id},
        json={"email": "duplicate@example.com", "password": "correct horse battery"},
    )
    assert claimed.status_code == 201
    token = claimed.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/voices", headers=headers).json()[0]["id"] == voice_id
    download = client.get(
        f"/api/v1/voices/{voice_id}/download",
        headers=headers,
        follow_redirects=False,
    )
    assert download.status_code == 200
    assert download.content == b"guest audio"


def test_registered_voice_generation_charges_credits(client: TestClient):
    _, token = register(client)
    headers = {"Authorization": f"Bearer {token}"}
    app = client.app
    with app.state.session_factory() as session:
        user = session.query(User).one()
        user.credits_balance = 3
        session.commit()

    response = client.post(
        "/api/v1/voices/generate",
        headers=headers,
        json={
            "title": "Guide",
            "gender": "man",
            "age_range": "adult",
            "ethnicity": "Kenyan",
            "description": "A calm and confident voice for an audio guide.",
        },
    )
    assert response.status_code == 201
    assert client.get("/api/v1/credits", headers=headers).json() == {"balance": 2}
    ledger = client.get("/api/v1/credits/ledger", headers=headers).json()
    assert ledger[0]["delta"] == -1


def test_delete_voice_removes_local_reference(client: TestClient, monkeypatch, tmp_path):
    _, token = register(client)
    headers = {"Authorization": "Bearer " + token}
    reference_dir = tmp_path / "references"
    reference_dir.mkdir()
    reference = reference_dir / "provider-voice-1.mp3"
    reference.write_bytes(b"voice reference")
    monkeypatch.setattr(voice_routes, "REFERENCE_DIR", reference_dir)

    with client.app.state.session_factory() as session:
        user = session.query(User).one()
        voice = VoiceRecord(
            owner_id=user.id,
            title="Voice",
            gender="woman",
            age_range="adult",
            ethnicity="Kenyan",
            description="A clear and expressive voice.",
            provider_voice_id="provider-voice-1",
        )
        session.add(voice)
        session.commit()
        voice_id = voice.id

    download = client.get(f"/api/v1/voices/{voice_id}/download", headers=headers)
    assert download.status_code == 200
    assert download.content == b"voice reference"
    assert download.headers["content-disposition"].startswith("attachment;")

    response = client.delete(f"/api/v1/voices/{voice_id}", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json() == {"deleted": True}
    assert not reference.exists()
    assert client.app.state.voice_provider.deleted_voice_ids == ["provider-voice-1"]
    with client.app.state.session_factory() as session:
        assert session.query(VoiceRecord).filter_by(id=voice_id).one_or_none() is None


def test_playground_synthesizes_and_charges(client: TestClient):
    _, token = register(client)
    headers = {"Authorization": f"Bearer {token}"}
    with client.app.state.session_factory() as session:
        user = session.query(User).one()
        user.credits_balance = 2
        voice = VoiceRecord(
            owner_id=user.id,
            title="Voice",
            gender="woman",
            age_range="adult",
            ethnicity="Kenyan",
            description="A clear and expressive voice.",
            provider_voice_id="provider-voice-1",
        )
        session.add(voice)
        session.commit()
        voice_id = voice.id

    response = client.post(
        "/api/v1/playground/speech",
        headers=headers,
        json={"voice_id": voice_id, "text": "Hello there."},
    )
    assert response.status_code == 200
    assert response.content == b"test-audio"
    assert client.get("/api/v1/credits", headers=headers).json()["balance"] == 1


def test_payment_settlement_is_idempotent(client: TestClient):
    with client.app.state.session_factory() as session:
        user = User(email="paid@example.com", credits_balance=10)
        session.add(user)
        session.flush()
        payment = PaymentRecord(
            user_id=user.id,
            pack_id="starter",
            amount_kes=100,
            credits=100,
            method="mpesa_stk",
            status="pending",
            account_reference="AB12CD34EF56",
        )
        session.add(payment)
        session.commit()

        assert settle_payment(session, payment, receipt_number="MPESA1") is True
        assert settle_payment(session, payment, receipt_number="MPESA1") is False
        session.refresh(user)
        assert user.credits_balance == 110
        assert session.query(CreditLedger).filter(CreditLedger.kind == "purchase").count() == 1


def test_charge_credits_allows_negative_balance(client: TestClient):
    register(client)
    with client.app.state.session_factory() as session:
        user = session.query(User).one()
        user.credits_balance = 0
        session.commit()

        charge_credits(session, user, 1, "synthesis")

        assert user.credits_balance == -1
        ledger = session.query(CreditLedger).filter(CreditLedger.kind == "synthesis").one()
        assert ledger.delta == -1
        assert ledger.balance_after == -1


def test_domain_rules_and_events():
    account = CreditAccount("user-1", 2)
    account.debit(1, "synthesis")
    assert account.balance == 1
    account.debit(2, "synthesis")
    assert account.balance == -1
    assert len(account.events) == 2

    album = Album("album-1", "user-1", "Trailers", "")
    album.add_voice("voice-1")
    album.add_voice("voice-1")
    assert album.voice_ids == {"voice-1"}
    assert len(album.events) == 1
    album.remove_voice("voice-1")
    assert not album.voice_ids


def test_web_pages_and_static_assets_are_served(client: TestClient):
    paths = ("/", "/studio", "/voices", "/playground", "/dashboard", "/billing", "/login", "/register", "/pricing", "/faq")
    for path in paths:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Vocalis" in response.text

    css = client.get("/static/css/app.css")
    javascript = client.get("/static/js/app.js")
    assert css.status_code == javascript.status_code == 200
    assert "--amber" in css.text
    assert "[hidden]" in css.text
    assert 'const API = "/api/v1"' in javascript.text
    assert '"/voices/generate"' in javascript.text
