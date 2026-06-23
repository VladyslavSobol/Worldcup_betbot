from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.models import (
    Bet,
    BetSlip,
    BetSlipItem,
    BetStatus,
    ExpressBet,
    ExpressBetItem,
    Market,
    MarketStatus,
    Match,
    MatchStatus,
    OddsSnapshot,
    SettlementLog,
    User,
    utcnow,
)
from app.money import payout_cents
from app.services.settlement import settle_selection


class BettingError(Exception):
    pass


async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    username: str | None,
    first_name: str | None,
    settings: Settings,
) -> User:
    user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    if user:
        user.username = username
        user.first_name = first_name
        return user
    user = User(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        balance_cents=settings.starting_balance_cents,
    )
    session.add(user)
    await session.flush()
    return user


async def place_bet(
    session: AsyncSession,
    telegram_id: int,
    odds_snapshot_id: int,
    stake_cents: int,
    settings: Settings,
) -> Bet:
    if stake_cents < settings.min_stake_cents:
        raise BettingError("Ставка менша за мінімальну.")

    user = await session.scalar(select(User).where(User.telegram_id == telegram_id).with_for_update())
    if not user:
        raise BettingError("Спочатку натисни /start.")
    if user.balance_cents < stake_cents:
        raise BettingError("Недостатньо коштів на балансі.")

    odds = await session.scalar(
        select(OddsSnapshot)
        .where(OddsSnapshot.id == odds_snapshot_id)
        .options(selectinload(OddsSnapshot.market).selectinload(Market.match))
    )
    if not odds:
        raise BettingError("Такий варіант ставки не знайдено.")

    market = odds.market
    match = market.match
    now = datetime.now(timezone.utc)
    kickoff_at = match.kickoff_at
    if kickoff_at.tzinfo is None:
        kickoff_at = kickoff_at.replace(tzinfo=timezone.utc)
    close_at = kickoff_at - timedelta(minutes=settings.bet_close_minutes)
    if market.status != MarketStatus.open:
        raise BettingError("Цей ринок уже закритий.")
    if match.status != MatchStatus.scheduled:
        raise BettingError("На цей матч зараз не можна ставити.")
    if now >= close_at:
        raise BettingError("Прийом ставок на цей матч уже закрито.")

    user.balance_cents -= stake_cents
    bet = Bet(
        user_id=user.id,
        match_id=match.id,
        market_id=market.id,
        odds_snapshot_id=odds.id,
        selection=odds.selection,
        stake_cents=stake_cents,
        locked_decimal_odds=odds.decimal_odds,
    )
    session.add(bet)
    await session.flush()
    return bet


def calculate_express_total_odds(odds_values: list[Decimal]) -> Decimal:
    total = Decimal("1")
    for value in odds_values:
        total *= Decimal(value)
    return total.quantize(Decimal("0.001"))


def calculate_express_payout(stake_cents: int, total_odds: Decimal) -> int:
    return payout_cents(stake_cents, total_odds)


async def get_bet_slip(session: AsyncSession, telegram_id: int) -> BetSlip | None:
    user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    if not user:
        return None
    return await session.scalar(
        select(BetSlip)
        .where(BetSlip.user_id == user.id)
        .options(
            selectinload(BetSlip.items).selectinload(BetSlipItem.match),
            selectinload(BetSlip.items).selectinload(BetSlipItem.market),
        )
    )


async def add_to_bet_slip(
    session: AsyncSession,
    telegram_id: int,
    odds_snapshot_id: int,
    settings: Settings,
) -> BetSlip:
    user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    if not user:
        raise BettingError("Спочатку натисни /start.")

    odds = await _get_open_odds_for_betting(session, odds_snapshot_id, settings)
    existing_match = await session.scalar(
        select(BetSlipItem)
        .join(BetSlip)
        .where(BetSlip.user_id == user.id, BetSlipItem.match_id == odds.market.match_id)
    )
    if existing_match:
        raise BettingError(
            "⚠️ У експресі вже є вибір з цього матчу.\n"
            "Для експресу можна додати тільки один вибір з одного матчу."
        )

    slip = await session.scalar(
        select(BetSlip)
        .where(BetSlip.user_id == user.id)
        .options(selectinload(BetSlip.items))
    )
    if not slip:
        slip = BetSlip(user_id=user.id)
        session.add(slip)
        await session.flush()

    session.add(
        BetSlipItem(
            bet_slip_id=slip.id,
            match_id=odds.market.match_id,
            market_id=odds.market_id,
            odds_snapshot_id=odds.id,
            selection=odds.selection,
            locked_decimal_odds=odds.decimal_odds,
        )
    )
    slip.updated_at = utcnow()
    await session.flush()
    return await get_bet_slip(session, telegram_id)


async def clear_bet_slip(session: AsyncSession, telegram_id: int) -> int:
    slip = await get_bet_slip(session, telegram_id)
    if not slip:
        return 0
    count = len(slip.items)
    await session.delete(slip)
    await session.flush()
    return count


async def remove_from_bet_slip(
    session: AsyncSession,
    telegram_id: int,
    item_id: int,
) -> BetSlip | None:
    user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    if not user:
        raise BettingError("Спочатку натисни /start.")

    slip = await session.scalar(
        select(BetSlip)
        .where(BetSlip.user_id == user.id)
        .options(selectinload(BetSlip.items))
    )
    if not slip or not slip.items:
        raise BettingError("Купон порожній.")

    item = next((item for item in slip.items if item.id == item_id), None)
    if not item:
        raise BettingError("Такого вибору в експресі немає.")

    await session.delete(item)
    slip.updated_at = utcnow()
    await session.flush()
    session.expire(slip, ["items"])
    return await get_bet_slip(session, telegram_id)


async def place_express_bet(
    session: AsyncSession,
    telegram_id: int,
    stake_cents: int,
    settings: Settings,
) -> ExpressBet:
    if stake_cents < settings.min_stake_cents:
        raise BettingError("Ставка менша за мінімальну.")

    user = await session.scalar(select(User).where(User.telegram_id == telegram_id).with_for_update())
    if not user:
        raise BettingError("Спочатку натисни /start.")
    if user.balance_cents < stake_cents:
        raise BettingError("Недостатньо коштів на балансі.")

    slip = await session.scalar(
        select(BetSlip)
        .where(BetSlip.user_id == user.id)
        .options(
            selectinload(BetSlip.items).selectinload(BetSlipItem.match),
            selectinload(BetSlip.items).selectinload(BetSlipItem.market),
            selectinload(BetSlip.items).selectinload(BetSlipItem.odds_snapshot),
        )
    )
    if not slip or len(slip.items) < 2:
        raise BettingError("Для експресу потрібно мінімум 2 події.")

    match_ids = {item.match_id for item in slip.items}
    if len(match_ids) != len(slip.items):
        raise BettingError("В експресі не може бути кілька виборів з одного матчу.")

    for item in slip.items:
        _ensure_match_is_open_for_betting(item.match, item.market, settings)

    total_odds = calculate_express_total_odds([Decimal(item.locked_decimal_odds) for item in slip.items])
    potential_payout = calculate_express_payout(stake_cents, total_odds)
    user.balance_cents -= stake_cents
    express = ExpressBet(
        user_id=user.id,
        stake_cents=stake_cents,
        total_odds=total_odds,
        potential_payout_cents=potential_payout,
    )
    session.add(express)
    await session.flush()
    for item in slip.items:
        session.add(
            ExpressBetItem(
                express_bet_id=express.id,
                match_id=item.match_id,
                market_id=item.market_id,
                odds_snapshot_id=item.odds_snapshot_id,
                selection=item.selection,
                locked_decimal_odds=item.locked_decimal_odds,
            )
        )
    await session.delete(slip)
    await session.flush()
    return express


async def _get_open_odds_for_betting(
    session: AsyncSession,
    odds_snapshot_id: int,
    settings: Settings,
) -> OddsSnapshot:
    odds = await session.scalar(
        select(OddsSnapshot)
        .where(OddsSnapshot.id == odds_snapshot_id)
        .options(selectinload(OddsSnapshot.market).selectinload(Market.match))
    )
    if not odds:
        raise BettingError("Такий варіант ставки не знайдено.")
    _ensure_match_is_open_for_betting(odds.market.match, odds.market, settings)
    return odds


def _ensure_match_is_open_for_betting(match: Match, market: Market, settings: Settings) -> None:
    now = datetime.now(timezone.utc)
    kickoff_at = match.kickoff_at
    if kickoff_at.tzinfo is None:
        kickoff_at = kickoff_at.replace(tzinfo=timezone.utc)
    close_at = kickoff_at - timedelta(minutes=settings.bet_close_minutes)
    if market.status != MarketStatus.open:
        raise BettingError("Цей ринок уже закритий.")
    if match.status != MatchStatus.scheduled:
        raise BettingError("На цей матч зараз не можна ставити.")
    if now >= close_at:
        raise BettingError("Прийом ставок на цей матч уже закрито.")

async def settle_match(
    session: AsyncSession,
    match_id: int,
    home_score: int,
    away_score: int,
    admin_telegram_id: int | None = None,
) -> int:
    match = await session.scalar(select(Match).where(Match.id == match_id))
    if not match:
        raise BettingError("Матч не знайдено.")
    match.home_score = home_score
    match.away_score = away_score
    match.status = MatchStatus.finished
    match.updated_at = utcnow()

    bets = (
        await session.scalars(
            select(Bet)
            .where(Bet.match_id == match_id, Bet.status == BetStatus.open)
            .options(selectinload(Bet.market), selectinload(Bet.user))
        )
    ).all()

    settled = 0
    for bet in bets:
        result = settle_selection(
            market_type=bet.market.type,
            selection=bet.selection,
            home_team=match.home_team,
            away_team=match.away_team,
            home_score=home_score,
            away_score=away_score,
            line=bet.market.line,
            selection_scope=bet.market.selection_scope,
        )
        bet.status = result.status
        bet.settled_at = utcnow()
        if result.status == BetStatus.won:
            bet.payout_cents = payout_cents(bet.stake_cents, Decimal(bet.locked_decimal_odds))
            bet.user.balance_cents += bet.payout_cents
        elif result.status == BetStatus.push:
            bet.payout_cents = bet.stake_cents
            bet.user.balance_cents += bet.stake_cents
        else:
            bet.payout_cents = 0
        settled += 1

    express_settled = await settle_express_items_for_match(
        session,
        match,
        home_score=home_score,
        away_score=away_score,
        void=False,
    )

    for market in (
        await session.scalars(select(Market).where(Market.match_id == match_id))
    ).all():
        market.status = MarketStatus.settled

    session.add(
        SettlementLog(
            match_id=match_id,
            admin_telegram_id=admin_telegram_id,
            action="settle",
            reason=f"{home_score}-{away_score}",
        )
    )
    await session.flush()
    return settled + express_settled


async def void_match(
    session: AsyncSession,
    match_id: int,
    reason: str,
    admin_telegram_id: int | None = None,
) -> int:
    match = await session.scalar(select(Match).where(Match.id == match_id))
    if not match:
        raise BettingError("Матч не знайдено.")

    bets = (
        await session.scalars(
            select(Bet)
            .where(Bet.match_id == match_id, Bet.status == BetStatus.open)
            .options(selectinload(Bet.user))
        )
    ).all()
    for bet in bets:
        bet.status = BetStatus.void
        bet.payout_cents = bet.stake_cents
        bet.settled_at = utcnow()
        bet.user.balance_cents += bet.stake_cents

    for market in (
        await session.scalars(select(Market).where(Market.match_id == match_id))
    ).all():
        market.status = MarketStatus.void

    express_settled = await settle_express_items_for_match(
        session,
        match,
        home_score=match.home_score or 0,
        away_score=match.away_score or 0,
        void=True,
        reason=reason,
    )

    session.add(
        SettlementLog(
            match_id=match_id,
            admin_telegram_id=admin_telegram_id,
            action="void",
            reason=reason,
        )
    )
    return len(bets) + express_settled

async def settle_express_items_for_match(
    session: AsyncSession,
    match: Match,
    home_score: int,
    away_score: int,
    void: bool = False,
    reason: str = "",
) -> int:
    items = (
        await session.scalars(
            select(ExpressBetItem)
            .where(ExpressBetItem.match_id == match.id, ExpressBetItem.status == BetStatus.open)
            .options(
                selectinload(ExpressBetItem.market),
                selectinload(ExpressBetItem.express_bet).selectinload(ExpressBet.user),
                selectinload(ExpressBetItem.express_bet).selectinload(ExpressBet.items),
            )
        )
    ).all()
    settled_express_ids: set[int] = set()
    for item in items:
        if void:
            item.status = BetStatus.void
            item.result_info = reason
        else:
            result = settle_selection(
                market_type=item.market.type,
                selection=item.selection,
                home_team=match.home_team,
                away_team=match.away_team,
                home_score=home_score,
                away_score=away_score,
                line=item.market.line,
                selection_scope=item.market.selection_scope,
            )
            item.status = result.status
        item.settled_at = utcnow()
        if _settle_express_if_ready(item.express_bet):
            settled_express_ids.add(item.express_bet.id)
    await session.flush()
    return len(settled_express_ids)


def _settle_express_if_ready(express: ExpressBet) -> bool:
    if express.status != BetStatus.open:
        return False
    items = list(express.items)
    if not items or any(item.status == BetStatus.open for item in items):
        return False

    express.settled_at = utcnow()
    if any(item.status == BetStatus.lost for item in items):
        express.status = BetStatus.lost
        express.payout_cents = 0
        return True

    active_items = [item for item in items if item.status == BetStatus.won]
    if not active_items:
        express.status = BetStatus.void
        express.payout_cents = express.stake_cents
        express.user.balance_cents += express.stake_cents
        return True

    effective_odds = calculate_express_total_odds(
        [Decimal(item.locked_decimal_odds) for item in active_items]
    )
    express.status = BetStatus.won
    express.total_odds = effective_odds
    express.potential_payout_cents = calculate_express_payout(express.stake_cents, effective_odds)
    express.payout_cents = express.potential_payout_cents
    express.user.balance_cents += express.payout_cents
    return True

async def close_match_markets(session: AsyncSession, match_id: int) -> int:
    markets = (
        await session.scalars(
            select(Market).where(Market.match_id == match_id, Market.status == MarketStatus.open)
        )
    ).all()
    for market in markets:
        market.status = MarketStatus.closed
    return len(markets)


async def reset_test_state(session: AsyncSession, settings: Settings) -> tuple[int, int]:
    await session.execute(delete(BetSlip))
    await session.execute(delete(ExpressBet))
    bets_result = await session.execute(delete(Bet))
    users_result = await session.execute(
        update(User).values(balance_cents=settings.starting_balance_cents)
    )
    return int(bets_result.rowcount or 0), int(users_result.rowcount or 0)


async def reset_user_state(
    session: AsyncSession,
    identifier: str,
    settings: Settings,
) -> tuple[User | None, int]:
    normalized = identifier.strip().lstrip("@")
    if not normalized:
        return None, 0

    if normalized.isdigit():
        user = await session.scalar(select(User).where(User.telegram_id == int(normalized)))
    else:
        user = await session.scalar(select(User).where(func.lower(User.username) == normalized.lower()))
    if not user:
        return None, 0

    await session.execute(delete(BetSlip).where(BetSlip.user_id == user.id))
    await session.execute(delete(ExpressBet).where(ExpressBet.user_id == user.id))
    bets_result = await session.execute(delete(Bet).where(Bet.user_id == user.id))
    user.balance_cents = settings.starting_balance_cents
    await session.flush()
    return user, int(bets_result.rowcount or 0)


async def leaderboard(session: AsyncSession) -> list[tuple[User, int, int]]:
    single_open_stakes = (
        select(Bet.user_id, func.coalesce(func.sum(Bet.stake_cents), 0).label("open_stakes"))
        .where(Bet.status == BetStatus.open)
        .group_by(Bet.user_id)
        .subquery()
    )
    express_open_stakes = (
        select(ExpressBet.user_id, func.coalesce(func.sum(ExpressBet.stake_cents), 0).label("open_stakes"))
        .where(ExpressBet.status == BetStatus.open)
        .group_by(ExpressBet.user_id)
        .subquery()
    )
    total_open = func.coalesce(single_open_stakes.c.open_stakes, 0) + func.coalesce(
        express_open_stakes.c.open_stakes,
        0,
    )
    statement: Select[tuple[User, int]] = (
        select(User, total_open)
        .outerjoin(single_open_stakes, User.id == single_open_stakes.c.user_id)
        .outerjoin(express_open_stakes, User.id == express_open_stakes.c.user_id)
        .order_by((User.balance_cents + total_open).desc())
    )
    rows = (await session.execute(statement)).all()
    return [(user, int(open_stake), user.balance_cents + int(open_stake)) for user, open_stake in rows]



