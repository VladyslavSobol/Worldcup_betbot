from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.bot import handlers
from app.bot.keyboards import group_menu_keyboard, group_private_keyboard
from app.models import Market, MarketType, Match, OddsSnapshot, User
from app.services.betting import add_to_bet_slip, get_or_create_user


async def _seed_odds(session, api_id: str, selection: str = "Brazil") -> OddsSnapshot:
    match = Match(
        api_id=api_id,
        sport_key="soccer_fifa_world_cup",
        home_team="Brazil",
        away_team="Japan",
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
        decimal_odds=Decimal("2.00"),
        source="test",
    )
    session.add(odds)
    await session.flush()
    return odds


def test_group_keyboards_show_approved_actions_and_leaderboard():
    expected = [
        "🎯 Ставити в приваті",
        "📅 Ставки на сьогодні",
        "👀 Відкриті ставки",
        "🏆 Лідерборд",
    ]

    for keyboard in (group_menu_keyboard(), group_private_keyboard()):
        labels = [button.text for row in keyboard.inline_keyboard for button in row]
        assert labels == expected


async def test_single_stake_selection_shows_available_balance(session_factory, settings):
    async with session_factory() as session:
        user = await get_or_create_user(session, 10, "friend", "Friend", settings)
        user.balance_cents = 7350
        odds = await _seed_odds(session, "balance-single")
        await session.commit()

    text, _ = await handlers._single_stake_view(session_factory, 10, odds.id)

    assert "Доступний баланс: $73.50" in text
    assert "Brazil" in text
    assert "2" in text


async def test_single_confirmation_shows_balance_before_and_after(
    session_factory,
    settings,
):
    async with session_factory() as session:
        user = await get_or_create_user(session, 10, "friend", "Friend", settings)
        user.balance_cents = 7350
        odds = await _seed_odds(session, "balance-confirm")
        await session.commit()

    text, _ = await handlers._bet_confirmation_view(
        session_factory,
        settings,
        telegram_id=10,
        odds_id=odds.id,
        stake_cents=500,
    )

    assert "Баланс до ставки: $73.50" in text
    assert "Після ставки: $68.50" in text


async def test_express_stake_and_confirmation_show_balance(session_factory, settings):
    async with session_factory() as session:
        user = await get_or_create_user(session, 10, "friend", "Friend", settings)
        user.balance_cents = 7350
        first = await _seed_odds(session, "balance-express-a")
        second = await _seed_odds(session, "balance-express-b")
        await add_to_bet_slip(session, user.telegram_id, first.id, settings)
        await add_to_bet_slip(session, user.telegram_id, second.id, settings)
        await session.commit()

    stake_text, _ = await handlers._express_stake_view(session_factory, 10)
    confirm_text, _ = await handlers._express_confirmation_view(
        session_factory,
        settings,
        10,
        500,
    )

    assert "Доступний баланс: $73.50" in stake_text
    assert "Баланс до ставки: $73.50" in confirm_text
    assert "Після ставки: $68.50" in confirm_text
