from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.bot.handlers import _stats_text
from app.models import BetStatus, ExpressBet, ExpressBetItem, Market, MarketType, Match, OddsSnapshot, User
from app.services.betting import (
    add_to_bet_slip,
    calculate_express_payout,
    calculate_express_total_odds,
    leaderboard,
    place_express_bet,
    settle_match,
    void_match,
)


def test_express_calculations():
    total = calculate_express_total_odds([Decimal("1.50"), Decimal("2.00"), Decimal("1.20")])
    assert total == Decimal("3.600")
    assert calculate_express_payout(500, total) == 1800


async def test_express_all_win(session_factory, settings):
    async with session_factory() as session:
        user = await _seed_user(session)
        first = await _seed_open_odds(session, "match-a", "Brazil", "Japan", "Brazil", Decimal("2.00"))
        second = await _seed_open_odds(session, "match-b", "France", "Iraq", "France", Decimal("1.50"))
        await add_to_bet_slip(session, user.telegram_id, first.id, settings)
        await add_to_bet_slip(session, user.telegram_id, second.id, settings)
        express = await place_express_bet(session, user.telegram_id, 1000, settings)
        await settle_match(session, first.market.match_id, 2, 1)
        await settle_match(session, second.market.match_id, 1, 0)
        await session.commit()

        refreshed = await _get_express(session, express.id)
        refreshed_user = await session.scalar(select(User).where(User.telegram_id == user.telegram_id))

    assert refreshed.status == BetStatus.won
    assert refreshed.total_odds == Decimal("3.000")
    assert refreshed.payout_cents == 3000
    assert refreshed_user.balance_cents == 12000


async def test_express_one_loss(session_factory, settings):
    async with session_factory() as session:
        user = await _seed_user(session)
        first = await _seed_open_odds(session, "match-c", "Brazil", "Japan", "Brazil", Decimal("2.00"))
        second = await _seed_open_odds(session, "match-d", "France", "Iraq", "France", Decimal("1.50"))
        await add_to_bet_slip(session, user.telegram_id, first.id, settings)
        await add_to_bet_slip(session, user.telegram_id, second.id, settings)
        express = await place_express_bet(session, user.telegram_id, 1000, settings)
        await settle_match(session, first.market.match_id, 0, 1)
        await settle_match(session, second.market.match_id, 1, 0)
        await session.commit()

        refreshed = await _get_express(session, express.id)
        refreshed_user = await session.scalar(select(User).where(User.telegram_id == user.telegram_id))

    assert refreshed.status == BetStatus.lost
    assert refreshed.payout_cents == 0
    assert refreshed_user.balance_cents == 9000


async def test_express_one_void(session_factory, settings):
    async with session_factory() as session:
        user = await _seed_user(session)
        first = await _seed_open_odds(session, "match-e", "Brazil", "Japan", "Brazil", Decimal("2.00"))
        second = await _seed_open_odds(session, "match-f", "France", "Iraq", "France", Decimal("1.50"))
        await add_to_bet_slip(session, user.telegram_id, first.id, settings)
        await add_to_bet_slip(session, user.telegram_id, second.id, settings)
        express = await place_express_bet(session, user.telegram_id, 1000, settings)
        await settle_match(session, first.market.match_id, 2, 1)
        await void_match(session, second.market.match_id, "postponed")
        await session.commit()

        refreshed = await _get_express(session, express.id)
        refreshed_user = await session.scalar(select(User).where(User.telegram_id == user.telegram_id))

    assert refreshed.status == BetStatus.won
    assert refreshed.total_odds == Decimal("2.000")
    assert refreshed.payout_cents == 2000
    assert refreshed_user.balance_cents == 11000


async def test_express_all_void(session_factory, settings):
    async with session_factory() as session:
        user = await _seed_user(session)
        first = await _seed_open_odds(session, "match-g", "Brazil", "Japan", "Brazil", Decimal("2.00"))
        second = await _seed_open_odds(session, "match-h", "France", "Iraq", "France", Decimal("1.50"))
        await add_to_bet_slip(session, user.telegram_id, first.id, settings)
        await add_to_bet_slip(session, user.telegram_id, second.id, settings)
        express = await place_express_bet(session, user.telegram_id, 1000, settings)
        await void_match(session, first.market.match_id, "postponed")
        await void_match(session, second.market.match_id, "postponed")
        await session.commit()

        refreshed = await _get_express(session, express.id)
        refreshed_user = await session.scalar(select(User).where(User.telegram_id == user.telegram_id))

    assert refreshed.status == BetStatus.void
    assert refreshed.payout_cents == 1000
    assert refreshed_user.balance_cents == 10000


async def test_leaderboard_counts_open_express_bets(session_factory, settings):
    async with session_factory() as session:
        first_user = await _seed_user(session, telegram_id=1, username="first")
        second_user = await _seed_user(session, telegram_id=2, username="second")
        first = await _seed_open_odds(session, "match-i", "Brazil", "Japan", "Brazil", Decimal("2.00"))
        second = await _seed_open_odds(session, "match-j", "France", "Iraq", "France", Decimal("1.50"))
        await add_to_bet_slip(session, first_user.telegram_id, first.id, settings)
        await add_to_bet_slip(session, first_user.telegram_id, second.id, settings)
        await place_express_bet(session, first_user.telegram_id, 2500, settings)
        second_user.balance_cents = 9900

        rows = await leaderboard(session)

    assert rows[0][0].telegram_id == 1
    assert rows[0][1] == 2500
    assert rows[0][2] == 10000
    assert rows[1][0].telegram_id == 2


async def test_stats_text_counts_settled_express_bets(session_factory, settings):
    async with session_factory() as session:
        user = await _seed_user(session)
        first = await _seed_open_odds(session, "match-stats-a", "Brazil", "Japan", "Brazil", Decimal("2.00"))
        second = await _seed_open_odds(session, "match-stats-b", "France", "Iraq", "France", Decimal("1.50"))
        await add_to_bet_slip(session, user.telegram_id, first.id, settings)
        await add_to_bet_slip(session, user.telegram_id, second.id, settings)
        await place_express_bet(session, user.telegram_id, 1000, settings)
        await settle_match(session, first.market.match_id, 2, 1)
        await settle_match(session, second.market.match_id, 1, 0)
        await session.commit()

    text = await _stats_text(session_factory, user.telegram_id, settings)

    assert "Ставок всього: 1" in text
    assert "Відкриті: 0 · виграні: 1 · програні: 0 · void/push: 0" in text
    assert "Win rate: 100%" in text
    assert "Найкращий чистий виграш: +$20.00" in text


async def _seed_user(session, telegram_id: int = 10, username: str = "friend") -> User:
    user = User(telegram_id=telegram_id, username=username, first_name=username.title(), balance_cents=10000)
    session.add(user)
    await session.flush()
    return user


async def _seed_open_odds(
    session,
    api_id: str,
    home_team: str,
    away_team: str,
    selection: str,
    price: Decimal,
) -> OddsSnapshot:
    match = Match(
        api_id=api_id,
        sport_key="soccer_fifa_world_cup",
        home_team=home_team,
        away_team=away_team,
        kickoff_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    session.add(match)
    await session.flush()
    market = Market(match_id=match.id, type=MarketType.h2h, source="test")
    session.add(market)
    await session.flush()
    odds = OddsSnapshot(
        market_id=market.id,
        selection=selection,
        decimal_odds=price,
        source="test-book",
    )
    session.add(odds)
    await session.flush()
    odds.market = market
    market.match = match
    return odds


async def _get_express(session, express_id: int) -> ExpressBet:
    return await session.scalar(
        select(ExpressBet)
        .where(ExpressBet.id == express_id)
        .options(selectinload(ExpressBet.items).selectinload(ExpressBetItem.match))
    )
