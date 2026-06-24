from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import aiohttp

from app.config import Settings
from app.integrations.odds_api import OddsEvent, OddsMarket, OddsOutcome
from app.integrations.providers import ScoreEvent


class OddsApiIoClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def fetch_odds(self) -> list[OddsEvent]:
        raw_events = await self._get("/events", {"sport": "football"})
        world_cup_events = [event for event in raw_events if _is_world_cup_event(event)]
        odds_by_id: dict[str, dict[str, Any]] = {}
        for batch in _chunks(world_cup_events, 10):
            data = await self._get(
                "/odds/multi",
                {
                    "eventIds": ",".join(str(event["id"]) for event in batch),
                    "bookmakers": self.settings.odds_api_io_bookmakers,
                },
            )
            rows = data if isinstance(data, list) else data.get("events", [])
            for row in rows:
                odds_by_id[str(row.get("id"))] = row

        events = []
        for raw in world_cup_events:
            odds_row = odds_by_id.get(str(raw.get("id")))
            if not odds_row:
                continue
            event = _parse_odds_event(raw, odds_row, self.settings.odds_api_io_bookmakers)
            if event.markets:
                events.append(event)
        return events

    async def fetch_scores(self) -> list[ScoreEvent]:
        raw_events = await self._get("/events", {"sport": "football"})
        return [
            _parse_score_event(event)
            for event in raw_events
            if _is_world_cup_event(event)
        ]

    async def _get(self, path: str, params: dict[str, str]) -> Any:
        merged_params = {"apiKey": self.settings.odds_api_io_key, **params}
        url = f"{self.settings.odds_api_io_base_url.rstrip('/')}{path}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=merged_params, timeout=30) as response:
                if response.status >= 400:
                    detail = await response.text()
                    safe_url = str(response.url).replace(self.settings.odds_api_io_key, "***")
                    raise RuntimeError(
                        f"Odds-API.io returned {response.status} for {safe_url}: {detail}"
                    )
                return await response.json()


def _parse_odds_event(
    event: dict[str, Any],
    odds_row: dict[str, Any],
    configured_bookmakers: str,
) -> OddsEvent:
    home_team = str(event.get("home") or odds_row.get("home") or "")
    away_team = str(event.get("away") or odds_row.get("away") or "")
    markets = []
    bookmaker_names = [name.strip() for name in configured_bookmakers.split(",") if name.strip()]
    bookmakers = odds_row.get("bookmakers") or {}
    for bookmaker_name in bookmaker_names:
        raw_markets = bookmakers.get(bookmaker_name) or []
        for market in raw_markets:
            parsed = _parse_market(market, bookmaker_name, home_team, away_team)
            if parsed:
                markets.append(parsed)
    return OddsEvent(
        api_id=f"odds_api_io:{event['id']}",
        sport_key="soccer_fifa_world_cup",
        home_team=home_team,
        away_team=away_team,
        commence_time=_parse_datetime(event.get("date") or odds_row.get("date")),
        markets=markets,
    )


def _parse_market(
    market: dict[str, Any],
    bookmaker: str,
    home_team: str,
    away_team: str,
) -> OddsMarket | None:
    name = market.get("name")
    rows = market.get("odds") or []
    outcomes = []
    if name == "ML" and rows:
        row = rows[0]
        outcomes = [
            _outcome(home_team, row.get("home")),
            _outcome("Draw", row.get("draw")),
            _outcome(away_team, row.get("away")),
        ]
        key = "h2h"
    elif name == "Spread":
        key = "spreads"
        for row in rows:
            point = _decimal(row.get("hdp"))
            if point is None:
                continue
            outcomes.extend(
                [
                    _outcome(home_team, row.get("home"), point),
                    _outcome(away_team, row.get("away"), -point),
                ]
            )
    elif name == "Totals":
        key = "totals"
        for row in rows:
            point = _decimal(row.get("hdp"))
            if point is None:
                continue
            outcomes.extend(
                [
                    _outcome("Over", row.get("over"), point),
                    _outcome("Under", row.get("under"), point),
                ]
            )
    else:
        return None
    valid_outcomes = [outcome for outcome in outcomes if outcome is not None]
    return OddsMarket(key=key, bookmaker=bookmaker, outcomes=valid_outcomes)


def _parse_score_event(event: dict[str, Any]) -> ScoreEvent:
    scores = event.get("scores") or {}
    full_time = (scores.get("periods") or {}).get("ft") or scores
    status = str(event.get("status") or "").lower()
    return ScoreEvent(
        api_id=f"odds_api_io:{event.get('id')}",
        home_team=str(event.get("home") or ""),
        away_team=str(event.get("away") or ""),
        commence_time=_parse_datetime(event.get("date")),
        completed=status in {"settled", "completed", "finished"},
        home_score=_int(full_time.get("home")),
        away_score=_int(full_time.get("away")),
    )


def _is_world_cup_event(event: dict[str, Any]) -> bool:
    league = event.get("league") or {}
    league_name = league.get("name", "") if isinstance(league, dict) else str(league)
    return "fifa world cup" in league_name.lower()


def _outcome(selection: str, price, point: Decimal | None = None) -> OddsOutcome | None:
    decimal_price = _decimal(price)
    if decimal_price is None:
        return None
    return OddsOutcome(selection=selection, price=decimal_price, point=point)


def _decimal(value) -> Decimal | None:
    if value in {None, "", "N/A"}:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_datetime(value) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _chunks(rows: list[dict[str, Any]], size: int):
    for index in range(0, len(rows), size):
        yield rows[index : index + size]
