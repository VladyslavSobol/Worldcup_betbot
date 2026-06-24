from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.odds_api import OddsEvent, OddsOutcome
from app.integrations.providers import OddsProvider, ScoreEvent
from app.models import Bet, BetStatus, ExpressBetItem, Market, MarketStatus, MarketType, Match, MatchStatus, OddsSnapshot, utcnow
from app.services.betting import settle_match


@dataclass(frozen=True)
class ScoreSettlementResult:
    match_id: int
    home_goals: int
    away_goals: int
    settled_count: int
    single_bet_ids: list[int]
    express_bet_ids: list[int]


async def sync_odds(session: AsyncSession, client: OddsProvider, sport_key: str | None = None) -> int:
    events = await _fetch_odds(client, sport_key)
    count = 0
    for event in events:
        count += await upsert_event_odds(session, event)
    return count


async def sync_scores(session: AsyncSession, client: OddsProvider, sport_key: str | None = None) -> int:
    results = await sync_scores_with_results(session, client, sport_key)
    return len(results)


async def sync_scores_with_results(
    session: AsyncSession,
    client: OddsProvider,
    sport_key: str | None = None,
) -> list[ScoreSettlementResult]:
    events = await _fetch_scores(client, sport_key)
    results = []
    for event in events:
        completed = event.completed if isinstance(event, ScoreEvent) else bool(event.get("completed"))
        if not completed:
            continue
        match = await _find_match_for_score(session, event)
        if not match or match.status in {
            MatchStatus.finished,
            MatchStatus.canceled,
            MatchStatus.postponed,
        }:
            continue
        home_goals, away_goals = _score_values(event, match)
        if home_goals is None or away_goals is None:
            continue
        single_bet_ids, express_bet_ids = await _open_settlement_target_ids(session, match.id)
        settled_count = await settle_match(session, match.id, home_goals, away_goals)
        results.append(
            ScoreSettlementResult(
                match_id=match.id,
                home_goals=home_goals,
                away_goals=away_goals,
                settled_count=settled_count,
                single_bet_ids=single_bet_ids,
                express_bet_ids=express_bet_ids,
            )
        )
    return results


async def _open_settlement_target_ids(
    session: AsyncSession,
    match_id: int,
) -> tuple[list[int], list[int]]:
    single_bet_ids = (
        await session.scalars(
            select(Bet.id).where(Bet.match_id == match_id, Bet.status == BetStatus.open)
        )
    ).all()
    express_bet_ids = (
        await session.scalars(
            select(ExpressBetItem.express_bet_id).where(
                ExpressBetItem.match_id == match_id,
                ExpressBetItem.status == BetStatus.open,
            )
        )
    ).all()
    return list(single_bet_ids), list(dict.fromkeys(express_bet_ids))


async def upsert_event_odds(session: AsyncSession, event: OddsEvent) -> int:
    match = await _find_match(
        session,
        event.api_id,
        event.home_team,
        event.away_team,
        event.commence_time,
    )
    if not match:
        match = Match(
            api_id=event.api_id,
            sport_key=event.sport_key,
            home_team=event.home_team,
            away_team=event.away_team,
            kickoff_at=event.commence_time,
        )
        session.add(match)
        await session.flush()
    else:
        match.home_team = event.home_team
        match.away_team = event.away_team
        match.kickoff_at = event.commence_time
        match.updated_at = utcnow()

    added = 0
    for api_market in event.markets:
        for outcome in api_market.outcomes:
            market_type = _market_type(api_market.key)
            if market_type is None:
                continue
            line = _line_for_market(market_type, outcome)
            selection_scope = _selection_scope_for_market(market_type, outcome)
            market = await _get_or_create_market(
                session,
                match.id,
                market_type,
                line,
                selection_scope,
                api_market.bookmaker,
            )
            session.add(
                OddsSnapshot(
                    market_id=market.id,
                    selection=_selection_for_market(market_type, outcome),
                    decimal_odds=outcome.price,
                    source=api_market.bookmaker,
                )
            )
            added += 1
    return added


async def _get_or_create_market(
    session: AsyncSession,
    match_id: int,
    market_type: MarketType,
    line: Decimal | None,
    selection_scope: str | None,
    source: str,
) -> Market:
    market = await session.scalar(
        select(Market).where(
            Market.match_id == match_id,
            Market.type == market_type,
            Market.line == line,
            Market.selection_scope == selection_scope,
        )
    )
    if market:
        return market
    market = Market(
        match_id=match_id,
        type=market_type,
        line=line,
        selection_scope=selection_scope,
        status=MarketStatus.open,
        source=source,
    )
    session.add(market)
    await session.flush()
    return market


def _market_type(key: str) -> MarketType | None:
    mapping = {
        "h2h": MarketType.h2h,
        "totals": MarketType.totals,
        "spreads": MarketType.spreads,
        "outrights": MarketType.outrights,
    }
    return mapping.get(key)


def _line_for_market(market_type: MarketType, outcome: OddsOutcome) -> Decimal | None:
    if market_type in {MarketType.totals, MarketType.spreads}:
        return outcome.point
    return None


def _selection_scope_for_market(market_type: MarketType, outcome: OddsOutcome) -> str | None:
    if market_type == MarketType.spreads:
        return outcome.selection
    return None


def _selection_for_market(market_type: MarketType, outcome: OddsOutcome) -> str:
    if market_type == MarketType.totals:
        return outcome.selection.title()
    return outcome.selection


def _score_map(event: dict) -> dict[str, int]:
    scores: dict[str, int] = {}
    for row in event.get("scores") or []:
        name = row.get("name")
        score = row.get("score")
        if name is None or score is None:
            continue
        try:
            scores[str(name)] = int(score)
        except (TypeError, ValueError):
            continue
    return scores


async def _fetch_odds(client, sport_key: str | None):
    if hasattr(client, "find_worldcup_sport_key"):
        selected_sport_key = sport_key or await client.find_worldcup_sport_key()
        if not selected_sport_key:
            return []
        return await client.fetch_odds(selected_sport_key)
    return await client.fetch_odds()


async def _fetch_scores(client, sport_key: str | None):
    if hasattr(client, "find_worldcup_sport_key"):
        selected_sport_key = sport_key or await client.find_worldcup_sport_key()
        if not selected_sport_key:
            return []
        return await client.fetch_scores(selected_sport_key)
    return await client.fetch_scores()


async def _find_match_for_score(
    session: AsyncSession,
    event: ScoreEvent | dict,
) -> Match | None:
    if isinstance(event, ScoreEvent):
        return await _find_match(
            session,
            event.api_id,
            event.home_team,
            event.away_team,
            event.commence_time,
        )
    return await session.scalar(select(Match).where(Match.api_id == event.get("id")))


async def _find_match(
    session: AsyncSession,
    api_id: str,
    home_team: str,
    away_team: str,
    commence_time: datetime | None,
) -> Match | None:
    match = await session.scalar(select(Match).where(Match.api_id == api_id))
    if match or commence_time is None:
        return match

    kickoff = _aware_utc(commence_time)
    candidates = (
        await session.scalars(
            select(Match).where(
                Match.kickoff_at >= kickoff - timedelta(minutes=15),
                Match.kickoff_at <= kickoff + timedelta(minutes=15),
            )
        )
    ).all()
    normalized_home = _normalize_team(home_team)
    normalized_away = _normalize_team(away_team)
    for candidate in candidates:
        if (
            _normalize_team(candidate.home_team) == normalized_home
            and _normalize_team(candidate.away_team) == normalized_away
        ):
            return candidate
    return None


def _score_values(
    event: ScoreEvent | dict,
    match: Match,
) -> tuple[int | None, int | None]:
    if isinstance(event, ScoreEvent):
        return event.home_score, event.away_score
    score_map = _score_map(event)
    return score_map.get(match.home_team), score_map.get(match.away_team)


def _normalize_team(name: str) -> str:
    return " ".join(sorted(name.casefold().split()))


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
