from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import aiohttp

from app.config import Settings


@dataclass(frozen=True)
class OddsOutcome:
    selection: str
    price: Decimal
    point: Decimal | None


@dataclass(frozen=True)
class OddsMarket:
    key: str
    bookmaker: str
    outcomes: list[OddsOutcome]


@dataclass(frozen=True)
class OddsEvent:
    api_id: str
    sport_key: str
    home_team: str
    away_team: str
    commence_time: datetime
    markets: list[OddsMarket]


class OddsApiClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def find_worldcup_sport_key(self) -> str | None:
        data = await self._get("/v4/sports/", {"all": "true"})
        for sport in data:
            key = sport.get("key", "").lower()
            title = sport.get("title", "").lower()
            description = sport.get("description", "").lower()
            haystack = f"{key} {title} {description}"
            if "soccer" not in key:
                continue
            if "club" in haystack:
                continue
            if key == "soccer_fifa_world_cup" or "fifa world cup" in haystack:
                return sport["key"]
        return None

    async def fetch_odds(self, sport_key: str) -> list[OddsEvent]:
        params = {
            "regions": self.settings.odds_regions,
            "markets": self.settings.odds_markets,
            "oddsFormat": "decimal",
        }
        data = await self._get(f"/v4/sports/{sport_key}/odds/", params)
        return [_parse_event(event) for event in data]

    async def fetch_scores(self, sport_key: str) -> list[dict[str, Any]]:
        return await self._get(f"/v4/sports/{sport_key}/scores/", {"daysFrom": "3"})

    async def _get(self, path: str, params: dict[str, str]) -> Any:
        if not self.settings.odds_api_key:
            raise RuntimeError("ODDS_API_KEY is not configured")
        merged_params = {"apiKey": self.settings.odds_api_key, **params}
        url = f"{self.settings.odds_api_base_url.rstrip('/')}{path}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=merged_params, timeout=30) as response:
                if response.status >= 400:
                    detail = await response.text()
                    safe_url = str(response.url).replace(self.settings.odds_api_key, "***")
                    raise RuntimeError(
                        f"The Odds API returned {response.status} for {safe_url}: {detail}"
                    )
                return await response.json()


def _parse_event(raw: dict[str, Any]) -> OddsEvent:
    markets: list[OddsMarket] = []
    for bookmaker in raw.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            outcomes = [
                OddsOutcome(
                    selection=outcome["name"],
                    price=Decimal(str(outcome["price"])),
                    point=Decimal(str(outcome["point"])) if outcome.get("point") is not None else None,
                )
                for outcome in market.get("outcomes", [])
            ]
            markets.append(
                OddsMarket(
                    key=market["key"],
                    bookmaker=bookmaker.get("title") or bookmaker.get("key", "unknown"),
                    outcomes=outcomes,
                )
            )
    return OddsEvent(
        api_id=raw["id"],
        sport_key=raw.get("sport_key", ""),
        home_team=raw["home_team"],
        away_team=raw["away_team"],
        commence_time=datetime.fromisoformat(raw["commence_time"].replace("Z", "+00:00")),
        markets=markets,
    )
