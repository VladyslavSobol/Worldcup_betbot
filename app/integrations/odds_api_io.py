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
    name = str(market.get("name") or "")
    normalized_name = " ".join(name.casefold().replace("-", " ").split())
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
        selected_rows = _balanced_rows(rows, "home", "away")
        for row in selected_rows:
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
        selected_rows = _balanced_rows(rows, "over", "under")
        for row in selected_rows:
            point = _decimal(row.get("hdp"))
            if point is None:
                continue
            outcomes.extend(
                [
                    _outcome("Over", row.get("over"), point),
                    _outcome("Under", row.get("under"), point),
                ]
            )
    elif name == "Double Chance" and rows:
        key = "double_chance"
        row = rows[0]
        outcomes = [
            _outcome("1X", _first_value(row, "homeDraw", "1X", "1x")),
            _outcome("X2", _first_value(row, "awayDraw", "X2", "x2")),
        ]
    elif normalized_name in {
        "to qualify",
        "to advance",
        "qualification",
        "team to qualify",
        "winner incl. overtime",
    } and rows:
        key = "to_qualify"
        row = rows[0]
        outcomes = [
            _outcome(home_team, _first_value(row, "home", "team1", "1")),
            _outcome(away_team, _first_value(row, "away", "team2", "2")),
        ]
    elif name == "Both Teams To Score" and rows:
        key = "btts"
        row = rows[0]
        outcomes = [
            _outcome("Yes", row.get("yes")),
            _outcome("No", row.get("no")),
        ]
    else:
        return None
    valid_outcomes = [outcome for outcome in outcomes if outcome is not None]
    return OddsMarket(key=key, bookmaker=bookmaker, outcomes=valid_outcomes)


def _parse_score_event(event: dict[str, Any]) -> ScoreEvent:
    scores = event.get("scores") or {}
    periods = scores.get("periods") or {}
    full_time = periods.get("ft") or scores
    home_team = str(event.get("home") or "")
    away_team = str(event.get("away") or "")
    status = str(event.get("status") or "").lower()
    return ScoreEvent(
        api_id=f"odds_api_io:{event.get('id')}",
        home_team=home_team,
        away_team=away_team,
        commence_time=_parse_datetime(event.get("date")),
        completed=status in {"settled", "completed", "finished"},
        home_score=_int(full_time.get("home")),
        away_score=_int(full_time.get("away")),
        advancing_team=_advancing_team(scores, periods, home_team, away_team),
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


def _balanced_rows(
    rows: list[dict[str, Any]],
    first_price: str,
    second_price: str,
    limit: int = 3,
) -> list[dict[str, Any]]:
    valid = []
    for row in rows:
        line = _decimal(row.get("hdp"))
        first = _decimal(row.get(first_price))
        second = _decimal(row.get(second_price))
        if line is not None and first is not None and second is not None:
            valid.append((row, line, abs(first - second)))
    if not valid:
        return []
    _, main_line, _ = min(valid, key=lambda item: (item[2], abs(item[1])))
    selected = sorted(valid, key=lambda item: (abs(item[1] - main_line), item[2]))[:limit]
    return [row for row, _, _ in sorted(selected, key=lambda item: item[1])]


def _first_value(row: dict[str, Any], *keys: str):
    for key in keys:
        if row.get(key) not in {None, "", "N/A"}:
            return row[key]
    return None


def _advancing_team(
    scores: dict[str, Any],
    periods: dict[str, Any],
    home_team: str,
    away_team: str,
) -> str | None:
    top_home = _int(scores.get("home"))
    top_away = _int(scores.get("away"))
    if top_home is not None and top_away is not None and top_home != top_away:
        return home_team if top_home > top_away else away_team
    penalties = periods.get("ap") or {}
    penalty_home = _int(penalties.get("home"))
    penalty_away = _int(penalties.get("away"))
    if (
        penalty_home is not None
        and penalty_away is not None
        and penalty_home != penalty_away
    ):
        return home_team if penalty_home > penalty_away else away_team
    return None
