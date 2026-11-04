from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routes import albums, auth, billing, playground, voices
from app.config import Settings, get_settings
from app.database import Base, build_engine, build_session_factory
from app.events import DomainEventBus
from app.providers.voice import VoiceProvider, provider_from_settings
from app.web import router as web_router


def create_app(
    *,
    settings: Settings | None = None,
    database_url: str | None = None,
    voice_provider: VoiceProvider | None = None,
    create_schema: bool = True,
) -> FastAPI:
    configuration = settings or get_settings()
    engine = build_engine(database_url or configuration.database_url)
    session_factory = build_session_factory(engine)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if create_schema:
            import app.models  # noqa: F401

            Base.metadata.create_all(bind=engine)
        yield
        engine.dispose()

    application = FastAPI(
        title="Vocalis API",
        version="1.0.0",
        description="Voice design, speech synthesis, credits, and payment API.",
        lifespan=lifespan,
    )
    application.state.engine = engine
    application.state.session_factory = session_factory
    application.state.settings = configuration
    application.state.voice_provider = voice_provider or provider_from_settings(configuration)
    application.state.event_bus = DomainEventBus()
    application.state.frontend_firebase_config = {
        "apiKey": configuration.firebase_api_key,
        "authDomain": configuration.firebase_auth_domain,
        "projectId": configuration.firebase_project_id,
        "appId": configuration.firebase_app_id,
    }
    application.add_middleware(
        CORSMiddleware,
        allow_origins=configuration.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    root = Path(__file__).parent
    application.mount("/static", StaticFiles(directory=root / "static"), name="static")

    @application.get("/health", tags=["operations"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    for route_module in (auth, voices, albums, playground, billing):
        application.include_router(route_module.router, prefix="/api/v1")
    application.include_router(web_router)
    return application


app = create_app()
