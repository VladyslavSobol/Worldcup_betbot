from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import aiohttp

from app.config import Settings
from app.integrations.odds_api import OddsApiClient, OddsEvent


@dataclass(frozen=True)
class ScoreEvent:
    api_id: str
    home_team: str
    away_team: str
    commence_time: datetime | None
    completed: bool
    home_score: int | None
    away_score: int | None


class OddsProvider(Protocol):
    async def fetch_odds(self) -> list[OddsEvent]: ...

    async def fetch_scores(self) -> list[ScoreEvent]: ...


class LegacyOddsProvider:
    def __init__(self, settings: Settings):
        self.client = OddsApiClient(settings)

    async def fetch_odds(self) -> list[OddsEvent]:
        sport_key = await self.client.find_worldcup_sport_key()
        if not sport_key:
            return []
        return await self.client.fetch_odds(sport_key)

    async def fetch_scores(self) -> list[ScoreEvent]:
        sport_key = await self.client.find_worldcup_sport_key()
        if not sport_key:
            return []
        events = await self.client.fetch_scores(sport_key)
        normalized = []
        for event in events:
            score_map = {
                str(row.get("name")): _as_int(row.get("score"))
                for row in event.get("scores") or []
                if row.get("name") is not None
            }
            home_team = str(event.get("home_team") or "")
            away_team = str(event.get("away_team") or "")
            normalized.append(
                ScoreEvent(
                    api_id=str(event.get("id") or ""),
                    home_team=home_team,
                    away_team=away_team,
                    commence_time=_as_datetime(event.get("commence_time")),
                    completed=bool(event.get("completed")),
                    home_score=score_map.get(home_team),
                    away_score=score_map.get(away_team),
                )
            )
        return normalized


class FallbackOddsProvider:
    def __init__(self, primary: OddsProvider, fallback: OddsProvider | None = None):
        self.primary = primary
        self.fallback = fallback

    async def fetch_odds(self) -> list[OddsEvent]:
        return await self._call("fetch_odds")

    async def fetch_scores(self) -> list[ScoreEvent]:
        return await self._call("fetch_scores")

    async def _call(self, method_name: str):
        try:
            return await getattr(self.primary, method_name)()
        except (RuntimeError, TimeoutError, aiohttp.ClientError):
            if self.fallback is None:
                raise
            return await getattr(self.fallback, method_name)()


def build_odds_provider(settings: Settings) -> OddsProvider:
    legacy = LegacyOddsProvider(settings) if settings.odds_api_key else None
    if settings.odds_provider.strip().lower() != "odds_api_io":
        if legacy is None:
            raise RuntimeError("ODDS_API_KEY is not configured")
        return legacy

    if not settings.odds_api_io_key:
        raise RuntimeError("ODDS_API_IO_KEY is not configured")

    from app.integrations.odds_api_io import OddsApiIoClient

    primary = OddsApiIoClient(settings)
    return FallbackOddsProvider(primary, legacy) if legacy else primary


def _as_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_datetime(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
