from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class DomainEvent:
    name: str


@dataclass(frozen=True)
class VoiceCreated(DomainEvent):
    voice_id: str
    owner_id: str | None


@dataclass(frozen=True)
class VoiceRegenerated(DomainEvent):
    voice_id: str
    owner_id: str


@dataclass(frozen=True)
class CreditsDebited(DomainEvent):
    account_id: str
    amount: int
    reason: str


@dataclass(frozen=True)
class AlbumVoiceAdded(DomainEvent):
    album_id: str
    voice_id: str


@dataclass
class CreditAccount:
    account_id: str
    balance: int
    events: list[DomainEvent] = field(default_factory=list)

    def debit(self, amount: int, reason: str) -> None:
        if amount <= 0:
            raise ValueError("Debit amount must be positive.")
        self.balance -= amount
        self.events.append(CreditsDebited("credits.debited", self.account_id, amount, reason))

    def credit(self, amount: int) -> None:
        if amount <= 0:
            raise ValueError("Credit amount must be positive.")
        self.balance += amount


@dataclass
class Album:
    album_id: str
    owner_id: str
    title: str
    description: str
    voice_ids: set[str] = field(default_factory=set)
    events: list[DomainEvent] = field(default_factory=list)

    def add_voice(self, voice_id: str) -> None:
        if voice_id not in self.voice_ids:
            self.voice_ids.add(voice_id)
            self.events.append(AlbumVoiceAdded("album.voice_added", self.album_id, voice_id))

    def remove_voice(self, voice_id: str) -> None:
        self.voice_ids.discard(voice_id)


@dataclass(frozen=True)
class VoiceSpec:
    title: str
    gender: str
    age_range: str
    ethnicity: str
    description: str


@dataclass(frozen=True)
class CreditPack:
    pack_id: str
    title: str
    credits: int
    amount_kes: Decimal


CREDIT_PACKS = (
    CreditPack("starter", "Starter", 100, Decimal("100.00")),
    CreditPack("creator", "Creator", 600, Decimal("500.00")),
    CreditPack("studio", "Studio", 1500, Decimal("1000.00")),
)
