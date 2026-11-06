from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    database_url: str = "sqlite:///./vocalis.db"
    jwt_secret_key: SecretStr = SecretStr("local-development-secret-change-before-deploying")
    jwt_expire_minutes: int = 60
    cors_origins: list[str] = ["http://localhost:8000", "http://127.0.0.1:8000"]
    frontend_base_url: str = "http://localhost:8000"

    voice_provider_base_url: str | None = None
    voice_provider_api_key: SecretStr | None = None
    breeze_api_key: SecretStr | None = None
    fish_api_key: SecretStr | None = None
    voice_generation_credit_cost: int = 1
    speech_credits_per_1000_chars: int = 1

    firebase_project_id: str | None = None
    firebase_service_account_file: str | None = None
    firebase_api_key: str | None = None
    firebase_auth_domain: str | None = None
    firebase_app_id: str | None = None

    mpesa_environment: str = "sandbox"
    mpesa_consumer_key: SecretStr | None = None
    mpesa_consumer_secret: SecretStr | None = None
    mpesa_shortcode: str | None = None
    mpesa_passkey: SecretStr | None = None
    mpesa_callback_url: str | None = None
    mpesa_c2b_confirmation_url: str | None = None
    mpesa_callback_secret: SecretStr | None = None
    mpesa_merchant_type: str = "paybill"
    mpesa_till_number: str | None = None

    stripe_secret_key: SecretStr | None = None
    stripe_webhook_secret: SecretStr | None = None

    @property
    def mpesa_base_url(self) -> str:
        if self.mpesa_environment == "production":
            return "https://api.safaricom.co.ke"
        return "https://sandbox.safaricom.co.ke"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.app_env == "production":
        secret = settings.jwt_secret_key.get_secret_value()
        if len(secret) < 32 or secret.startswith("local-development-"):
            raise ValueError("Set JWT_SECRET_KEY to a unique secret of at least 32 characters.")
    return settings
