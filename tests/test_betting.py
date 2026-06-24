from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from app.bot.handlers import _leaderboard_text, _openbets_text, _topwins_text
from app.models import Bet, BetStatus, ExpressBet, Market, MarketType, Match, MatchStatus, OddsSnapshot, User
from app.services.betting import (
    BettingError,
    add_to_bet_slip,
    get_or_create_user,
    leaderboard,
    place_bet,
    place_express_bet,
    reset_test_state,
    reset_user_state,
    settle_match,
    void_match,
)
from app.services.sync import sync_scores, sync_scores_with_results
from app.integrations.odds_api import OddsEvent, OddsMarket, OddsOutcome
from app.integrations.providers import ScoreEvent
from app.services.sync import sync_odds


async def test_user_gets_starting_balance(session_factory, settings):
    async with session_factory() as session:
        user = await get_or_create_user(session, 10, "friend", "Friend", settings)
        await session.commit()

    assert user.balance_cents == 10000


async def test_place_bet_deducts_balance_and_locks_odds(session_factory, settings):
    async with session_factory() as session:
        user = await get_or_create_user(session, 10, "friend", "Friend", settings)
        odds = await _seed_open_odds(session)
        bet = await place_bet(session, user.telegram_id, odds.id, 500, settings)
        await session.commit()

    assert user.balance_cents == 9500
    assert bet.stake_cents == 500
    assert bet.locked_decimal_odds == Decimal("2.500")


async def test_place_bet_allows_amount_above_old_max_when_balance_is_enough(session_factory, settings):
    async with session_factory() as session:
        user = await get_or_create_user(session, 10, "friend", "Friend", settings)
        odds = await _seed_open_odds(session)
        bet = await place_bet(session, user.telegram_id, odds.id, 3000, settings)
        await session.commit()

    assert bet.stake_cents == 3000
    assert user.balance_cents == 7000


async def test_place_bet_rejects_stake_below_minimum(session_factory, settings):
    async with session_factory() as session:
        user = await get_or_create_user(session, 10, "friend", "Friend", settings)
        odds = await _seed_open_odds(session)

        with pytest.raises(BettingError, match="мінімальну"):
            await place_bet(session, user.telegram_id, odds.id, 99, settings)


async def test_place_bet_rejects_stake_above_available_balance(session_factory, settings):
    async with session_factory() as session:
        user = await get_or_create_user(session, 10, "friend", "Friend", settings)
        odds = await _seed_open_odds(session)

        with pytest.raises(BettingError, match="Недостатньо коштів"):
            await place_bet(session, user.telegram_id, odds.id, 10001, settings)


async def test_bets_close_five_minutes_before_kickoff(session_factory, settings):
    async with session_factory() as session:
        user = await get_or_create_user(session, 10, "friend", "Friend", settings)
        open_odds = await _seed_open_odds(
            session,
            api_id="match-six-minutes",
            kickoff_delta=timedelta(minutes=6),
        )
        closed_odds = await _seed_open_odds(
            session,
            api_id="match-five-minutes",
            kickoff_delta=timedelta(minutes=5),
        )

        bet = await place_bet(session, user.telegram_id, open_odds.id, 100, settings)
        with pytest.raises(BettingError, match="закрито"):
            await place_bet(session, user.telegram_id, closed_odds.id, 100, settings)

    assert bet.stake_cents == 100


async def test_settle_match_updates_winner_balance(session_factory, settings):
    async with session_factory() as session:
        user = await get_or_create_user(session, 10, "friend", "Friend", settings)
        odds = await _seed_open_odds(session, selection="Brazil", price=Decimal("2.50"))
        await place_bet(session, user.telegram_id, odds.id, 1000, settings)
        settled = await settle_match(session, odds.market.match_id, 2, 1, 10)
        await session.commit()
        refreshed = await session.scalar(select(User).where(User.telegram_id == 10))
        bet = await session.scalar(select(Bet))

    assert settled == 1
    assert refreshed.balance_cents == 11500
    assert bet.status == BetStatus.won
    assert bet.payout_cents == 2500


async def test_void_returns_stake(session_factory, settings):
    async with session_factory() as session:
        user = await get_or_create_user(session, 10, "friend", "Friend", settings)
        odds = await _seed_open_odds(session)
        await place_bet(session, user.telegram_id, odds.id, 1000, settings)
        count = await void_match(session, odds.market.match_id, "postponed", 10)
        await session.commit()
        refreshed = await session.scalar(select(User).where(User.telegram_id == 10))
        bet = await session.scalar(select(Bet))

    assert count == 1
    assert refreshed.balance_cents == 10000
    assert bet.status == BetStatus.void


async def test_leaderboard_uses_balance_plus_open_stakes(session_factory, settings):
    async with session_factory() as session:
        first = await get_or_create_user(session, 1, "first", "First", settings)
        second = await get_or_create_user(session, 2, "second", "Second", settings)
        odds = await _seed_open_odds(session)
        await place_bet(session, first.telegram_id, odds.id, 2500, settings)
        second.balance_cents = 9900
        rows = await leaderboard(session)

    assert rows[0][0].telegram_id == 1
    assert rows[0][1] == 2500
    assert rows[0][2] == 10000
    assert rows[1][0].telegram_id == 2


async def test_leaderboard_text_uses_compact_medal_format(session_factory, settings):
    async with session_factory() as session:
        first = await get_or_create_user(session, 1, "first", "First", settings)
        second = await get_or_create_user(session, 2, "second", "Second", settings)
        third = await get_or_create_user(session, 3, "third", "Third", settings)
        fourth = await get_or_create_user(session, 4, "fourth", "Fourth", settings)
        fifth = await get_or_create_user(session, 5, "fifth", "Fifth", settings)
        sixth = await get_or_create_user(session, 6, "sixth", "Sixth", settings)
        odds = await _seed_open_odds(session)
        await place_bet(session, first.telegram_id, odds.id, 2500, settings)
        second.balance_cents = 10900
        third.balance_cents = 10600
        fourth.balance_cents = 10200
        fifth.balance_cents = 9500
        sixth.balance_cents = 9400
        await session.commit()

    text = await _leaderboard_text(session_factory, settings)

    assert text.startswith("🏆 Лідерборд\n\nБанкрол = баланс + відкриті ставки")
    assert "🥇 second\n💰 Банкрол: $109.00\n💵 Баланс: $109.00\n🎟 Відкрито: $0.00\n📊 Профіт: +$9.00" in text
    assert "🥈 third" in text
    assert "🥉 fourth" in text
    assert "4. first" in text
    assert "5. fifth" in text
    assert "sixth" not in text
    assert " | " not in text


async def test_leaderboard_text_empty_state(session_factory, settings):
    text = await _leaderboard_text(session_factory, settings)

    assert text == "🏆 Лідерборд\n\nПоки що немає гравців для лідерборду."


async def test_topwins_text_uses_compact_blocks_for_single_and_express_wins(session_factory, settings):
    async with session_factory() as session:
        first = await get_or_create_user(session, 1, "first", "First", settings)
        second = await get_or_create_user(session, 2, "second", "Second", settings)
        odds = await _seed_open_odds(session, selection="Brazil", price=Decimal("1.40"))
        single = Bet(
            user_id=first.id,
            match_id=odds.market.match_id,
            market_id=odds.market_id,
            odds_snapshot_id=odds.id,
            selection="Brazil",
            stake_cents=2500,
            locked_decimal_odds=Decimal("1.400"),
            status=BetStatus.won,
            payout_cents=3500,
        )
        express = ExpressBet(
            user_id=second.id,
            stake_cents=500,
            total_odds=Decimal("1.200"),
            potential_payout_cents=600,
            status=BetStatus.won,
            payout_cents=600,
        )
        session.add_all([single, express])
        await session.commit()

    text = await _topwins_text(session_factory)

    assert text.startswith("💎 Топ виграшів")
    assert "🥇 first\n💸 Чистий виграш: +$10.00" in text
    assert "🇧🇷 Brazil — 🇯🇵 Japan" in text
    assert "📌 1X2: Brazil" in text
    assert "📈 Кеф: 1.40" in text
    assert "💵 $25.00 → $35.00" in text
    assert "━━━━━━━━━━━━" in text
    assert "🧾 Експрес #" in text
    assert "📈 Загальний кеф: 1.20" in text
    assert "Подій: 0" in text
    assert " | " not in text


async def test_topwins_text_empty_state(session_factory):
    text = await _topwins_text(session_factory)

    assert text == "💎 Топ виграшів\n\nПоки що виграних ставок немає."


async def test_openbets_text_uses_continuous_display_numbers_after_deleted_bets(
    session_factory,
    settings,
):
    async with session_factory() as session:
        user = await get_or_create_user(session, 1, "first", "First", settings)
        first_odds = await _seed_open_odds(session, api_id="match-open-1")
        second_odds = await _seed_open_odds(session, api_id="match-open-2")
        first_bet = await place_bet(session, user.telegram_id, first_odds.id, 100, settings)
        second_bet = await place_bet(session, user.telegram_id, second_odds.id, 100, settings)
        await session.execute(delete(Bet).where(Bet.id == first_bet.id))
        await session.commit()

    text = await _openbets_text(session_factory)

    assert "👀 Відкриті ставки друзів" in text
    assert "\n1. first —" in text
    assert f"#{second_bet.id}" not in text


async def test_reset_test_state_deletes_bets_and_resets_balances(session_factory, settings):
    async with session_factory() as session:
        first = await get_or_create_user(session, 1, "first", "First", settings)
        second = await get_or_create_user(session, 2, "second", "Second", settings)
        odds = await _seed_open_odds(session)
        await place_bet(session, first.telegram_id, odds.id, 500, settings)
        second.balance_cents = 4200

        bets_deleted, users_reset = await reset_test_state(session, settings)
        await session.commit()

        bets = (await session.scalars(select(Bet))).all()
        users = (await session.scalars(select(User).order_by(User.telegram_id))).all()

    assert bets_deleted == 1
    assert users_reset == 2
    assert bets == []
    assert [user.balance_cents for user in users] == [10000, 10000]


async def test_reset_user_state_deletes_only_that_users_bets(session_factory, settings):
    async with session_factory() as session:
        first = await get_or_create_user(session, 1, "first", "First", settings)
        second = await get_or_create_user(session, 2, "second", "Second", settings)
        first_odds = await _seed_open_odds(session, api_id="match-reset-first")
        second_odds = await _seed_open_odds(session, api_id="match-reset-second")
        await place_bet(session, first.telegram_id, first_odds.id, 500, settings)
        await place_bet(session, second.telegram_id, second_odds.id, 500, settings)

        user, bets_deleted = await reset_user_state(session, "@first", settings)
        await session.commit()

        bets = (await session.scalars(select(Bet).order_by(Bet.user_id))).all()
        refreshed_first = await session.scalar(select(User).where(User.telegram_id == 1))
        refreshed_second = await session.scalar(select(User).where(User.telegram_id == 2))

    assert user.telegram_id == 1
    assert bets_deleted == 1
    assert len(bets) == 1
    assert refreshed_first.balance_cents == 10000
    assert refreshed_second.balance_cents == 9500


async def test_sync_scores_settles_completed_api_match(session_factory, settings):
    class FakeScoresClient:
        async def find_worldcup_sport_key(self):
            return "soccer_fifa_world_cup"

        async def fetch_scores(self, sport_key):
            return [
                {
                    "id": "match-score-sync",
                    "completed": True,
                    "scores": [
                        {"name": "Brazil", "score": "2"},
                        {"name": "Japan", "score": "1"},
                    ],
                }
            ]

    async with session_factory() as session:
        user = await get_or_create_user(session, 10, "friend", "Friend", settings)
        odds = await _seed_open_odds(
            session,
            selection="Brazil",
            price=Decimal("2.50"),
            api_id="match-score-sync",
        )
        await place_bet(session, user.telegram_id, odds.id, 1000, settings)

        count = await sync_scores(session, FakeScoresClient())
        await session.commit()

        match = await session.scalar(select(Match).where(Match.api_id == "match-score-sync"))
        bet = await session.scalar(select(Bet))
        refreshed = await session.scalar(select(User).where(User.telegram_id == 10))

    assert count == 1
    assert match.status == MatchStatus.finished
    assert bet.status == BetStatus.won
    assert refreshed.balance_cents == 11500


async def test_sync_scores_with_results_returns_settled_bet_targets(session_factory, settings):
    class FakeScoresClient:
        async def find_worldcup_sport_key(self):
            return "soccer_fifa_world_cup"

        async def fetch_scores(self, sport_key):
            return [
                {
                    "id": "match-score-results-a",
                    "completed": True,
                    "scores": [
                        {"name": "Brazil", "score": "2"},
                        {"name": "Japan", "score": "1"},
                    ],
                },
                {
                    "id": "match-score-results-b",
                    "completed": True,
                    "scores": [
                        {"name": "France", "score": "1"},
                        {"name": "Iraq", "score": "0"},
                    ],
                },
            ]

    async with session_factory() as session:
        single_user = await get_or_create_user(session, 10, "single", "Single", settings)
        express_user = await get_or_create_user(session, 20, "express", "Express", settings)
        first = await _seed_open_odds(
            session,
            selection="Brazil",
            price=Decimal("2.00"),
            api_id="match-score-results-a",
        )
        second = await _seed_open_odds(
            session,
            selection="France",
            price=Decimal("1.50"),
            api_id="match-score-results-b",
        )
        second.market.match.home_team = "France"
        second.market.match.away_team = "Iraq"
        await place_bet(session, single_user.telegram_id, first.id, 1000, settings)
        await add_to_bet_slip(session, express_user.telegram_id, first.id, settings)
        await add_to_bet_slip(session, express_user.telegram_id, second.id, settings)
        express = await place_express_bet(session, express_user.telegram_id, 500, settings)

        results = await sync_scores_with_results(session, FakeScoresClient())
        await session.commit()

    assert [result.match_id for result in results] == [first.market.match_id, second.market.match_id]
    assert results[0].home_goals == 2
    assert results[0].away_goals == 1
    assert results[0].single_bet_ids
    assert express.id in results[0].express_bet_ids


async def test_new_provider_odds_reuse_existing_match_by_teams_and_kickoff(
    session_factory,
):
    kickoff = datetime.now(timezone.utc) + timedelta(days=1)

    class FakeProvider:
        async def fetch_odds(self):
            return [
                OddsEvent(
                    api_id="odds_api_io:101",
                    sport_key="soccer_fifa_world_cup",
                    home_team="Colombia",
                    away_team="Congo DR",
                    commence_time=kickoff + timedelta(minutes=5),
                    markets=[
                        OddsMarket(
                            key="h2h",
                            bookmaker="Unibet",
                            outcomes=[
                                OddsOutcome(
                                    selection="Colombia",
                                    price=Decimal("2.33"),
                                    point=None,
                                )
                            ],
                        )
                    ],
                )
            ]

    async with session_factory() as session:
        existing = Match(
            api_id="legacy-event-id",
            sport_key="soccer_fifa_world_cup",
            home_team="Colombia",
            away_team="DR Congo",
            kickoff_at=kickoff,
        )
        session.add(existing)
        await session.flush()

        count = await sync_odds(session, FakeProvider())
        await session.commit()

        matches = (await session.scalars(select(Match))).all()
        odds = (await session.scalars(select(OddsSnapshot))).all()

    assert count == 1
    assert len(matches) == 1
    assert matches[0].id == existing.id
    assert matches[0].api_id == "legacy-event-id"
    assert matches[0].home_team == "Colombia"
    assert matches[0].away_team == "DR Congo"
    assert odds[0].source == "Unibet"


async def test_new_provider_score_settles_existing_legacy_match(
    session_factory,
    settings,
):
    kickoff = datetime.now(timezone.utc) - timedelta(hours=3)

    class FakeProvider:
        async def fetch_scores(self):
            return [
                ScoreEvent(
                    api_id="odds_api_io:101",
                    home_team="Colombia",
                    away_team="Congo DR",
                    commence_time=kickoff + timedelta(minutes=5),
                    completed=True,
                    home_score=2,
                    away_score=1,
                )
            ]

    async with session_factory() as session:
        user = await get_or_create_user(session, 10, "friend", "Friend", settings)
        odds = await _seed_open_odds(
            session,
            selection="Colombia",
            price=Decimal("2.00"),
            api_id="legacy-event-id",
            kickoff_delta=timedelta(days=1),
        )
        odds.market.match.home_team = "Colombia"
        odds.market.match.away_team = "DR Congo"
        await place_bet(session, user.telegram_id, odds.id, 1000, settings)
        odds.market.match.kickoff_at = kickoff
        duplicate = Match(
            api_id="odds_api_io:101",
            sport_key="soccer_fifa_world_cup",
            home_team="Colombia",
            away_team="Congo DR",
            kickoff_at=kickoff + timedelta(minutes=5),
        )
        session.add(duplicate)
        await session.flush()

        results = await sync_scores_with_results(session, FakeProvider())
        await session.commit()

        match = await session.get(Match, odds.market.match_id)
        duplicate = await session.get(Match, duplicate.id)
        bet = await session.scalar(select(Bet))

    assert len(results) == 2
    assert match.api_id == "legacy-event-id"
    assert match.status == MatchStatus.finished
    assert duplicate.status == MatchStatus.finished
    assert bet.status == BetStatus.won


async def _seed_open_odds(
    session,
    selection: str = "Brazil",
    price: Decimal = Decimal("2.50"),
    api_id: str = "match-1",
    kickoff_delta: timedelta = timedelta(days=1),
) -> OddsSnapshot:
    match = Match(
        api_id=api_id,
        sport_key="soccer_fifa_world_cup",
        home_team="Brazil",
        away_team="Japan",
        kickoff_at=datetime.now(timezone.utc) + kickoff_delta,
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
