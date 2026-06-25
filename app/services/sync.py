from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.odds_api import OddsEvent, OddsOutcome
from app.integrations.providers import OddsProvider, ScoreEvent
from app.models import Bet, BetStatus, ExpressBet, ExpressBetItem, Market, MarketStatus, MarketType, Match, MatchStatus, OddsSnapshot, utcnow
from app.services.betting import settle_match
from app.team_names import canonical_team_name


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
        matches = await _find_matches_for_score(session, event)
        for match in matches:
            if match.status in {
                MatchStatus.canceled,
                MatchStatus.postponed,
            }:
                continue
            advancing_team = _advancing_team_for_match(event, match)
            if match.status == MatchStatus.finished and not (
                advancing_team and await _has_open_qualification_market(session, match.id)
            ):
                continue
            home_goals, away_goals = _score_values(event, match)
            if home_goals is None or away_goals is None:
                continue
            single_bet_ids, express_bet_ids = await _open_settlement_target_ids(session, match.id)
            settled_count = await settle_match(
                session,
                match.id,
                home_goals,
                away_goals,
                advancing_team=advancing_team,
            )
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
            select(ExpressBetItem.express_bet_id)
            .join(ExpressBet, ExpressBet.id == ExpressBetItem.express_bet_id)
            .where(
                ExpressBetItem.match_id == match_id,
                ExpressBetItem.status == BetStatus.open,
                ExpressBet.status == BetStatus.open,
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
        match.kickoff_at = event.commence_time
        match.updated_at = utcnow()

    added = 0
    for api_market in event.markets:
        for outcome in api_market.outcomes:
            market_type = _market_type(api_market.key)
            if market_type is None:
                continue
            line = _line_for_market(market_type, outcome)
            selection = _selection_for_match(market_type, outcome, event, match)
            selection_scope = (
                selection if market_type == MarketType.spreads else None
            )
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
                    selection=selection,
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
        "double_chance": MarketType.double_chance,
        "totals": MarketType.totals,
        "spreads": MarketType.spreads,
        "btts": MarketType.btts,
        "to_qualify": MarketType.to_qualify,
        "outrights": MarketType.outrights,
    }
    return mapping.get(key)


def _line_for_market(market_type: MarketType, outcome: OddsOutcome) -> Decimal | None:
    if market_type in {MarketType.totals, MarketType.spreads}:
        return outcome.point
    return None


def _selection_for_match(
    market_type: MarketType,
    outcome: OddsOutcome,
    event: OddsEvent,
    match: Match,
) -> str:
    if market_type == MarketType.totals:
        return outcome.selection.title()
    if market_type in {MarketType.h2h, MarketType.spreads, MarketType.to_qualify}:
        if canonical_team_name(outcome.selection) == canonical_team_name(event.home_team):
            return match.home_team
        if canonical_team_name(outcome.selection) == canonical_team_name(event.away_team):
            return match.away_team
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


async def _find_matches_for_score(
    session: AsyncSession,
    event: ScoreEvent | dict,
) -> list[Match]:
    if isinstance(event, ScoreEvent):
        matches = []
        exact = await session.scalar(select(Match).where(Match.api_id == event.api_id))
        if exact:
            matches.append(exact)
        if event.commence_time is not None:
            matches.extend(
                await _matching_team_time_candidates(
                    session,
                    event.home_team,
                    event.away_team,
                    event.commence_time,
                )
            )
        return list({match.id: match for match in matches}.values())
    match = await session.scalar(select(Match).where(Match.api_id == event.get("id")))
    return [match] if match else []


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

    candidates = await _matching_team_time_candidates(
        session,
        home_team,
        away_team,
        commence_time,
    )
    return candidates[0] if candidates else None


async def _matching_team_time_candidates(
    session: AsyncSession,
    home_team: str,
    away_team: str,
    commence_time: datetime,
) -> list[Match]:
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
    return [
        candidate
        for candidate in candidates
        if (
            _normalize_team(candidate.home_team) == normalized_home
            and _normalize_team(candidate.away_team) == normalized_away
        )
    ]


def _score_values(
    event: ScoreEvent | dict,
    match: Match,
) -> tuple[int | None, int | None]:
    if isinstance(event, ScoreEvent):
        return event.home_score, event.away_score
    score_map = _score_map(event)
    return score_map.get(match.home_team), score_map.get(match.away_team)


def _advancing_team_for_match(
    event: ScoreEvent | dict,
    match: Match,
) -> str | None:
    if not isinstance(event, ScoreEvent) or not event.advancing_team:
        return None
    if canonical_team_name(event.advancing_team) == canonical_team_name(event.home_team):
        return match.home_team
    if canonical_team_name(event.advancing_team) == canonical_team_name(event.away_team):
        return match.away_team
    return None


async def _has_open_qualification_market(session: AsyncSession, match_id: int) -> bool:
    market_id = await session.scalar(
        select(Market.id).where(
            Market.match_id == match_id,
            Market.type == MarketType.to_qualify,
            Market.status == MarketStatus.open,
        )
    )
    return market_id is not None


def _normalize_team(name: str) -> str:
    return canonical_team_name(name)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
