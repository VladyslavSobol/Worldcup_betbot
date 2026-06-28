from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import logging
from zoneinfo import ZoneInfo

from aiogram import Bot, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.bot.formatting import (
    flags_test_text,
    format_bets_list,
    format_decimal,
    format_express_bet_card,
    format_leaderboard,
    format_market_selection,
    format_match_pair,
    format_money,
    format_odds,
    format_profit,
    format_single_bet_card,
    format_top_wins,
    market_block_title,
    market_title,
    match_line,
    match_title,
    odds_line,
    user_label,
)
from app.bot.keyboards import (
    MATCHES_PER_PAGE,
    ODDS_BLOCKS_PER_PAGE,
    confirm_bet_keyboard,
    confirm_express_keyboard,
    express_coupon_keyboard,
    express_stake_keyboard,
    group_menu_keyboard,
    group_private_keyboard,
    main_menu_keyboard,
    matches_keyboard,
    mybets_filter_keyboard,
    odds_keyboard,
    openbets_pagination_keyboard,
    selected_odds_keyboard,
    stake_keyboard,
)
from app.config import Settings
from app.integrations.providers import build_odds_provider
from app.models import Bet, BetStatus, ExpressBet, ExpressBetItem, Market, MarketStatus, MarketType, Match, MatchStatus, OddsSnapshot, User
from app.money import format_cents, parse_cents, payout_cents
from app.services.betting import (
    BettingError,
    add_to_bet_slip,
    calculate_express_payout,
    calculate_express_total_odds,
    clear_bet_slip,
    close_match_markets,
    get_bet_slip,
    get_or_create_user,
    grant_playoff_bonus,
    leaderboard,
    place_bet,
    place_express_bet,
    remove_from_bet_slip,
    reset_test_state,
    reset_user_state,
    settle_match,
    void_match,
)
from app.services.groups import bind_group_chat, get_primary_group_chat
from app.services.sync import sync_odds
from app.team_names import canonical_team_name


PENDING_CUSTOM_BETS: dict[int, int] = {}
PENDING_CUSTOM_EXPRESS: set[int] = set()
OPEN_BETS_PER_PAGE = 5
MY_BETS_PER_PAGE = 10
logger = logging.getLogger(__name__)


def build_router(session_factory: async_sessionmaker[AsyncSession], settings: Settings) -> Router:
    router = Router()

    @router.message(Command("start"))
    async def start(message: Message) -> None:
        if _is_group_message(message):
            await message.answer(
                "Я готовий бути спільним табло для ваших фан-ставок.\n\n"
                "У групі показую лідерборд, правила й анонси.\n"
                "Ставки кожен робить у приваті, щоб ніхто нікому не ламав екран.",
                reply_markup=group_menu_keyboard(),
            )
            return

        async with session_factory() as session:
            user = await get_or_create_user(
                session,
                message.from_user.id,
                message.from_user.username,
                message.from_user.first_name,
                settings,
            )
            await session.commit()
        await message.answer(
            "Привіт! Це приватний бот для фан-ставок між друзями, без реальних грошей.\n\n"
            f"Твій баланс: {format_cents(user.balance_cents)}\n"
            "Обери дію кнопками нижче.",
            reply_markup=main_menu_keyboard(),
        )

    @router.message(Command("bind_group"))
    async def bind_group(message: Message) -> None:
        if not _is_group_message(message):
            await message.answer("Цю команду треба викликати саме в груповому чаті.")
            return
        if not _is_admin(message, settings):
            await message.answer("Ця команда тільки для адміна.")
            return
        async with session_factory() as session:
            group = await bind_group_chat(session, message.chat.id, message.chat.title)
            await session.commit()
        await message.answer(
            f"Групу прив'язано: {group.title or group.chat_id}.\n\n"
            "Тепер після ставок і розрахунків я буду писати сюди оновлення.",
            reply_markup=group_menu_keyboard(),
        )

    @router.message(Command("help"))
    async def help_command(message: Message) -> None:
        keyboard = group_menu_keyboard() if _is_group_message(message) else main_menu_keyboard()
        await message.answer(_help_text(), reply_markup=keyboard)

    @router.message(Command("test_flags"))
    async def test_flags(message: Message) -> None:
        await message.answer(flags_test_text())

    @router.message(Command("matches"))
    async def matches(message: Message) -> None:
        if _is_group_message(message):
            await message.answer(
                "Матчі й ставки відкриваються в приваті з ботом.\n"
                "Так кожен має свій екран і кнопки не конфліктують у групі.",
                reply_markup=group_private_keyboard(),
            )
            return
        text, keyboard = await _matches_view(session_factory, settings, page=0)
        await message.answer(text, reply_markup=keyboard)

    @router.message(Command("markets"))
    async def markets(message: Message) -> None:
        args = _args(message)
        if len(args) != 1:
            await message.answer("Формат: /markets <id_матчу>")
            return
        try:
            text, keyboard = await _odds_view(session_factory, settings, match_id=int(args[0]), page=0)
            await message.answer(text, reply_markup=keyboard)
        except ValueError as exc:
            await message.answer(str(exc))

    @router.message(Command("bet"))
    async def bet(message: Message) -> None:
        args = _args(message)
        if len(args) != 2:
            await message.answer("Формат: /bet <id_коеф> <сума>, наприклад /bet 42 5")
            return
        try:
            text, keyboard = await _bet_confirmation_view(
                session_factory,
                settings,
                telegram_id=message.from_user.id,
                odds_id=int(args[0]),
                stake_cents=parse_cents(args[1]),
            )
            await message.answer(text, reply_markup=keyboard)
        except (ValueError, BettingError) as exc:
            await message.answer(str(exc))

    @router.message(lambda message: _looks_like_amount(message.text))
    async def custom_amount_bet(message: Message) -> None:
        if message.from_user.id in PENDING_CUSTOM_EXPRESS:
            try:
                text, keyboard = await _express_confirmation_view(
                    session_factory,
                    settings,
                    message.from_user.id,
                    parse_cents(_normalize_amount(message.text)),
                )
                await message.answer(text, reply_markup=keyboard)
            except (ValueError, BettingError) as exc:
                await message.answer(str(exc))
            return
        odds_id = PENDING_CUSTOM_BETS.get(message.from_user.id)
        if not odds_id:
            return
        try:
            text, keyboard = await _bet_confirmation_view(
                session_factory,
                settings,
                telegram_id=message.from_user.id,
                odds_id=odds_id,
                stake_cents=parse_cents(_normalize_amount(message.text)),
            )
            await message.answer(text, reply_markup=keyboard)
        except (ValueError, BettingError) as exc:
            await message.answer(str(exc))

    @router.message(Command("mybets"))
    async def mybets(message: Message) -> None:
        text, keyboard = await _mybets_view(session_factory, message.from_user.id, "open")
        await message.answer(text, reply_markup=keyboard)

    @router.message(Command("leaderboard"))
    async def show_leaderboard(message: Message) -> None:
        text = await _leaderboard_text(session_factory, settings)
        keyboard = group_menu_keyboard() if _is_group_message(message) else main_menu_keyboard()
        await message.answer(text, reply_markup=keyboard)

    @router.message(Command("openbets"))
    async def openbets(message: Message) -> None:
        text, keyboard = await _openbets_view(session_factory, page=0)
        await message.answer(text, reply_markup=keyboard)

    @router.message(Command("stats"))
    async def stats(message: Message) -> None:
        text = await _stats_text(session_factory, message.from_user.id, settings)
        await message.answer(text, reply_markup=main_menu_keyboard())

    @router.message(Command("topwins"))
    async def topwins(message: Message) -> None:
        text = await _topwins_text(session_factory)
        keyboard = group_menu_keyboard() if _is_group_message(message) else main_menu_keyboard()
        await message.answer(text, reply_markup=keyboard)

    @router.message(Command("balance"))
    async def balance(message: Message) -> None:
        text = await _balance_text(session_factory, message.from_user.id, settings)
        await message.answer(text, reply_markup=main_menu_keyboard())

    @router.message(Command("rules"))
    async def rules(message: Message) -> None:
        keyboard = group_menu_keyboard() if _is_group_message(message) else main_menu_keyboard()
        await message.answer(_rules_text(settings), reply_markup=keyboard)

    @router.message(Command("explain"))
    async def explain(message: Message) -> None:
        keyboard = group_menu_keyboard() if _is_group_message(message) else main_menu_keyboard()
        await message.answer(_explain_text(), reply_markup=keyboard)

    @router.callback_query(lambda call: call.data == "u:menu")
    async def menu_callback(callback: CallbackQuery) -> None:
        keyboard = group_menu_keyboard() if _is_group_chat(callback.message.chat) else main_menu_keyboard()
        await callback.message.edit_text("Головне меню:", reply_markup=keyboard)
        await callback.answer()

    @router.callback_query(lambda call: call.data == "u:help")
    async def help_callback(callback: CallbackQuery) -> None:
        keyboard = group_menu_keyboard() if _is_group_chat(callback.message.chat) else main_menu_keyboard()
        await callback.message.edit_text(_help_text(), reply_markup=keyboard)
        await callback.answer()

    @router.callback_query(lambda call: call.data == "u:bets")
    async def mybets_callback(callback: CallbackQuery) -> None:
        text, keyboard = await _mybets_view(session_factory, callback.from_user.id, "open")
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()

    @router.callback_query(lambda call: call.data and call.data.startswith("u:bets:"))
    async def mybets_filter_callback(callback: CallbackQuery) -> None:
        parts = callback.data.split(":")
        status = parts[2]
        page = int(parts[4]) if len(parts) >= 5 and parts[3] == "p" else 0
        text, keyboard = await _mybets_view(session_factory, callback.from_user.id, status, page)
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()

    @router.callback_query(lambda call: call.data == "u:board")
    async def leaderboard_callback(callback: CallbackQuery) -> None:
        text = await _leaderboard_text(session_factory, settings)
        keyboard = group_menu_keyboard() if _is_group_chat(callback.message.chat) else main_menu_keyboard()
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()

    @router.callback_query(lambda call: call.data == "u:openbets")
    async def openbets_callback(callback: CallbackQuery) -> None:
        text, keyboard = await _openbets_view(session_factory, page=0)
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()

    @router.callback_query(lambda call: call.data and call.data.startswith("u:openbets:p:"))
    async def openbets_page_callback(callback: CallbackQuery) -> None:
        page = int(callback.data.split(":")[3])
        text, keyboard = await _openbets_view(session_factory, page=page)
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()

    @router.callback_query(lambda call: call.data == "u:stats")
    async def stats_callback(callback: CallbackQuery) -> None:
        try:
            text = await _stats_text(session_factory, callback.from_user.id, settings)
            await callback.message.edit_text(text, reply_markup=main_menu_keyboard())
            await callback.answer()
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                await callback.answer("Статистика вже відкрита")
                return
            logger.exception("Could not render stats for telegram_id=%s", callback.from_user.id)
            await callback.answer("Не вдалося відкрити статистику. Помилка записана в логи.", show_alert=True)
        except Exception:
            logger.exception("Could not render stats for telegram_id=%s", callback.from_user.id)
            await callback.answer("Не вдалося відкрити статистику. Помилка записана в логи.", show_alert=True)

    @router.callback_query(lambda call: call.data == "u:topwins")
    async def topwins_callback(callback: CallbackQuery) -> None:
        text = await _topwins_text(session_factory)
        keyboard = group_menu_keyboard() if _is_group_chat(callback.message.chat) else main_menu_keyboard()
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()

    @router.callback_query(lambda call: call.data == "u:balance")
    async def balance_callback(callback: CallbackQuery) -> None:
        text = await _balance_text(session_factory, callback.from_user.id, settings)
        await callback.message.edit_text(text, reply_markup=main_menu_keyboard())
        await callback.answer()

    @router.callback_query(lambda call: call.data == "u:rules")
    async def rules_callback(callback: CallbackQuery) -> None:
        keyboard = group_menu_keyboard() if _is_group_chat(callback.message.chat) else main_menu_keyboard()
        await callback.message.edit_text(_rules_text(settings), reply_markup=keyboard)
        await callback.answer()

    @router.callback_query(lambda call: call.data == "u:explain")
    async def explain_callback(callback: CallbackQuery) -> None:
        keyboard = group_menu_keyboard() if _is_group_chat(callback.message.chat) else main_menu_keyboard()
        await callback.message.edit_text(_explain_text(), reply_markup=keyboard)
        await callback.answer()

    @router.callback_query(lambda call: call.data == "noop")
    async def noop_callback(callback: CallbackQuery) -> None:
        await callback.answer()


    @router.callback_query(lambda call: call.data and call.data.startswith("m:today:"))
    async def today_matches_callback(callback: CallbackQuery) -> None:
        if _is_group_chat(callback.message.chat):
            await callback.answer(
                "Ставки відкриваються в приваті з ботом.",
                show_alert=True,
            )
            return
        page = int(callback.data.split(":")[2])
        text, keyboard = await _today_matches_view(session_factory, settings, page)
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()
    @router.callback_query(lambda call: call.data and call.data.startswith("m:p:"))
    async def matches_callback(callback: CallbackQuery) -> None:
        if _is_group_chat(callback.message.chat):
            await callback.answer(
                "Ставки відкриваються в приваті з ботом, щоб у кожного був свій екран.",
                show_alert=True,
            )
            return
        page = int(callback.data.split(":")[2])
        text, keyboard = await _matches_view(session_factory, settings, page)
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()

    @router.callback_query(lambda call: call.data and call.data.startswith("m:o:"))
    async def odds_callback(callback: CallbackQuery) -> None:
        if _is_group_chat(callback.message.chat):
            await callback.answer(
                "Обирай матч у приваті з ботом. У групі це спільне повідомлення для всіх.",
                show_alert=True,
            )
            return
        _, _, match_id, page = callback.data.split(":")
        try:
            text, keyboard = await _odds_view(session_factory, settings, int(match_id), int(page))
            await callback.message.edit_text(text, reply_markup=keyboard)
            await callback.answer()
        except ValueError as exc:
            await callback.answer(str(exc), show_alert=True)

    @router.callback_query(lambda call: call.data and call.data.startswith("o:s:"))
    async def select_odds_callback(callback: CallbackQuery) -> None:
        if _is_group_chat(callback.message.chat):
            await callback.answer(
                "Ставку треба робити в приваті з ботом.",
                show_alert=True,
            )
            return
        odds_id = int(callback.data.split(":")[2])
        async with session_factory() as session:
            odds = await session.scalar(
                select(OddsSnapshot)
                .where(OddsSnapshot.id == odds_id)
                .options(selectinload(OddsSnapshot.market).selectinload(Market.match))
            )
        if not odds:
            await callback.answer("Коефіцієнт не знайдено.", show_alert=True)
            return
        await callback.message.edit_text(
            "Обраний варіант:\n"
            f"{match_title(odds.market.match)}\n"
            f"{odds_line(odds)}\n\n"
            "Можна поставити одиночну ставку або додати вибір в експрес.",
            reply_markup=selected_odds_keyboard(odds.id, odds.market.match_id),
        )
        await callback.answer()


    @router.callback_query(lambda call: call.data and call.data.startswith("o:single:"))
    async def single_odds_callback(callback: CallbackQuery) -> None:
        if _is_group_chat(callback.message.chat):
            await callback.answer("Ставку треба робити в приваті з ботом.", show_alert=True)
            return
        odds_id = int(callback.data.split(":")[2])
        PENDING_CUSTOM_BETS[callback.from_user.id] = odds_id
        text, keyboard = await _single_stake_view(
            session_factory,
            callback.from_user.id,
            odds_id,
        )
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()

    @router.callback_query(lambda call: call.data and call.data.startswith("x:add:"))
    async def add_to_express_callback(callback: CallbackQuery) -> None:
        if _is_group_chat(callback.message.chat):
            await callback.answer("Експрес збирається тільки в приваті з ботом.", show_alert=True)
            return
        odds_id = int(callback.data.split(":")[2])
        try:
            logger.debug("Adding odds to express slip: telegram_id=%s odds_id=%s", callback.from_user.id, odds_id)
            async with session_factory() as session:
                await get_or_create_user(
                    session,
                    callback.from_user.id,
                    callback.from_user.username,
                    callback.from_user.first_name,
                    settings,
                )
                await add_to_bet_slip(session, callback.from_user.id, odds_id, settings)
                await session.commit()
            async with session_factory() as session:
                slip = await get_bet_slip(session, callback.from_user.id)
            item_count = len(slip.items) if slip else 0
            logger.debug(
                "Express slip updated: telegram_id=%s slip_id=%s item_count=%s",
                callback.from_user.id,
                getattr(slip, "id", None),
                item_count,
            )
            await callback.message.edit_text(
                _bet_slip_added_text(slip),
                reply_markup=express_coupon_keyboard(
                    item_count >= 2,
                    item_count > 0,
                    _bet_slip_remove_buttons(slip),
                ),
            )
            await callback.answer("✅ Додано в експрес")
        except BettingError as exc:
            logger.debug(
                "Could not add odds to express slip: telegram_id=%s odds_id=%s reason=%s",
                callback.from_user.id,
                odds_id,
                str(exc),
            )
            await callback.answer(str(exc), show_alert=True)

    @router.callback_query(lambda call: call.data == "u:slip")
    async def bet_slip_callback(callback: CallbackQuery) -> None:
        if _is_group_chat(callback.message.chat):
            await callback.answer("Купон доступний у приваті з ботом.", show_alert=True)
            return
        text, keyboard = await _bet_slip_view(session_factory, callback.from_user.id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()

    @router.callback_query(lambda call: call.data == "x:clear")
    async def clear_express_callback(callback: CallbackQuery) -> None:
        if _is_group_chat(callback.message.chat):
            await callback.answer("Купон доступний у приваті з ботом.", show_alert=True)
            return
        async with session_factory() as session:
            await clear_bet_slip(session, callback.from_user.id)
            await session.commit()
        text, keyboard = await _bet_slip_view(session_factory, callback.from_user.id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer("Купон очищено")

    @router.callback_query(lambda call: call.data and call.data.startswith("x:remove:"))
    async def remove_express_item_callback(callback: CallbackQuery) -> None:
        if _is_group_chat(callback.message.chat):
            await callback.answer("Купон доступний у приваті з ботом.", show_alert=True)
            return
        try:
            item_id = int(callback.data.split(":")[2])
            async with session_factory() as session:
                slip = await remove_from_bet_slip(session, callback.from_user.id, item_id)
                await session.commit()
            item_count = len(slip.items) if slip else 0
            await callback.message.edit_text(
                _bet_slip_text(slip),
                reply_markup=express_coupon_keyboard(
                    item_count >= 2,
                    item_count > 0,
                    _bet_slip_remove_buttons(slip),
                ),
            )
            await callback.answer("Вибір прибрано з експресу")
        except (ValueError, BettingError) as exc:
            await callback.answer(str(exc), show_alert=True)

    @router.callback_query(lambda call: call.data == "x:stake")
    async def express_stake_callback(callback: CallbackQuery) -> None:
        if _is_group_chat(callback.message.chat):
            await callback.answer("Експрес ставиться тільки в приваті з ботом.", show_alert=True)
            return
        text, keyboard = await _express_stake_view(session_factory, callback.from_user.id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()

    @router.callback_query(lambda call: call.data == "x:custom")
    async def custom_express_stake_callback(callback: CallbackQuery) -> None:
        if _is_group_chat(callback.message.chat):
            await callback.answer("Суму експресу вводь у приваті з ботом.", show_alert=True)
            return
        PENDING_CUSTOM_EXPRESS.add(callback.from_user.id)
        await callback.message.edit_text(
            "Напиши суму експресу повідомленням.\n\nНаприклад: 4, 4.50 або 12",
            reply_markup=express_coupon_keyboard(True, True),
        )
        await callback.answer()

    @router.callback_query(lambda call: call.data and call.data.startswith("x:c:"))
    async def confirm_express_stake_callback(callback: CallbackQuery) -> None:
        if _is_group_chat(callback.message.chat):
            await callback.answer("Експрес ставиться тільки в приваті з ботом.", show_alert=True)
            return
        stake_cents = int(callback.data.split(":")[2])
        try:
            text, keyboard = await _express_confirmation_view(
                session_factory,
                settings,
                callback.from_user.id,
                stake_cents,
            )
            await callback.message.edit_text(text, reply_markup=keyboard)
            await callback.answer()
        except BettingError as exc:
            await callback.answer(str(exc), show_alert=True)

    @router.callback_query(lambda call: call.data and call.data.startswith("x:final:"))
    async def final_express_callback(callback: CallbackQuery, bot: Bot) -> None:
        if _is_group_chat(callback.message.chat):
            await callback.answer("Експрес ставиться тільки в приваті з ботом.", show_alert=True)
            return
        stake_cents = int(callback.data.split(":")[2])
        try:
            PENDING_CUSTOM_EXPRESS.discard(callback.from_user.id)
            result = await _place_express_by_user(
                session_factory,
                settings,
                callback.from_user,
                stake_cents,
            )
            await callback.message.edit_text(result.user_text, reply_markup=main_menu_keyboard())
            await _announce_to_group(
                session_factory,
                bot,
                result.group_text,
                source_chat_id=callback.message.chat.id,
            )
            await callback.answer("Експрес прийнято")
        except BettingError as exc:
            await callback.answer(str(exc), show_alert=True)
    @router.callback_query(lambda call: call.data and call.data.startswith("b:custom:"))
    async def custom_stake_callback(callback: CallbackQuery) -> None:
        if _is_group_chat(callback.message.chat):
            await callback.answer("Суму ставки вводь у приваті з ботом.", show_alert=True)
            return
        odds_id = int(callback.data.split(":")[2])
        PENDING_CUSTOM_BETS[callback.from_user.id] = odds_id
        await callback.message.edit_text(
            "Напиши суму ставки повідомленням.\n\n"
            "Наприклад: 4, 4.50 або 12",
            reply_markup=main_menu_keyboard(),
        )
        await callback.answer()

    @router.callback_query(lambda call: call.data and call.data.startswith("b:c:"))
    async def confirm_bet_callback(callback: CallbackQuery) -> None:
        if _is_group_chat(callback.message.chat):
            await callback.answer("Підтвердження ставки працює тільки в приваті.", show_alert=True)
            return
        _, _, odds_id, stake_cents = callback.data.split(":")
        try:
            text, keyboard = await _bet_confirmation_view(
                session_factory,
                settings,
                telegram_id=callback.from_user.id,
                odds_id=int(odds_id),
                stake_cents=int(stake_cents),
            )
            await callback.message.edit_text(text, reply_markup=keyboard)
            await callback.answer()
        except BettingError as exc:
            await callback.answer(str(exc), show_alert=True)

    @router.callback_query(lambda call: call.data and call.data.startswith("b:final:"))
    async def final_bet_callback(callback: CallbackQuery, bot: Bot) -> None:
        if _is_group_chat(callback.message.chat):
            await callback.answer("Підтвердження ставки працює тільки в приваті.", show_alert=True)
            return
        _, _, odds_id, stake_cents = callback.data.split(":")
        try:
            PENDING_CUSTOM_BETS.pop(callback.from_user.id, None)
            result = await _place_bet_by_id(
                session_factory,
                settings,
                callback.from_user,
                int(odds_id),
                int(stake_cents),
            )
            keyboard = group_menu_keyboard() if _is_group_chat(callback.message.chat) else main_menu_keyboard()
            await callback.message.edit_text(result.user_text, reply_markup=keyboard)
            await _announce_to_group(
                session_factory,
                bot,
                result.group_text,
                source_chat_id=callback.message.chat.id,
            )
            await callback.answer("Ставку прийнято")
        except BettingError as exc:
            await callback.answer(str(exc), show_alert=True)

    @router.message(Command("admin_settle"))
    async def admin_settle(message: Message, bot: Bot) -> None:
        if not _is_admin(message, settings):
            await message.answer("Ця команда тільки для адміна.")
            return
        args = _args(message)
        if len(args) != 3:
            await message.answer("Формат: /admin_settle <id_матчу> <голи_1> <голи_2>")
            return
        try:
            match_id = int(args[0])
            home_goals = int(args[1])
            away_goals = int(args[2])
            async with session_factory() as session:
                single_bet_ids, express_bet_ids = await _open_settlement_target_ids(session, match_id)
                count = await settle_match(
                    session,
                    match_id,
                    home_goals,
                    away_goals,
                    message.from_user.id,
                )
                match = await session.scalar(select(Match).where(Match.id == match_id))
                details = await _settlement_results_for_targets(
                    session,
                    match,
                    single_bet_ids,
                    express_bet_ids,
                )
                await session.commit()
            text = f"Розраховано відкритих ставок: {count}."
            await message.answer(text)
            if match:
                board = await _leaderboard_text(session_factory, settings)
                details_block = f"{details}\n\n" if details else ""
                await _announce_to_group(
                    session_factory,
                    bot,
                    "Матч розраховано.\n\n"
                    f"{match.home_team} {home_goals}:{away_goals} {match.away_team}\n\n"
                    f"{details_block}"
                    f"{board}",
                    source_chat_id=message.chat.id,
                    settlements_only=True,
                )
        except (ValueError, BettingError) as exc:
            await message.answer(str(exc))

    @router.message(Command("admin_void"))
    async def admin_void(message: Message, bot: Bot) -> None:
        if not _is_admin(message, settings):
            await message.answer("Ця команда тільки для адміна.")
            return
        args = _args(message)
        if len(args) < 1:
            await message.answer("Формат: /admin_void <id_матчу> [причина]")
            return
        reason = " ".join(args[1:]) or "ручне скасування"
        async with session_factory() as session:
            count = await void_match(session, int(args[0]), reason, message.from_user.id)
            await session.commit()
        await message.answer(f"Скасовано відкритих ставок: {count}.")
        await _announce_to_group(
            session_factory,
            bot,
            f"Ставки по матчу #{args[0]} скасовано.\nПричина: {reason}\nПовернено ставок: {count}.",
            source_chat_id=message.chat.id,
            settlements_only=True,
        )

    @router.message(Command("admin_open_bets"))
    @router.message(Command("admin_debug_settlement"))
    async def admin_debug_settlement(message: Message) -> None:
        if not _is_admin(message, settings):
            await message.answer("Ця команда тільки для адміна.")
            return
        text = await _admin_debug_settlement_text(session_factory)
        await message.answer(text)

    @router.message(Command("admin_close"))
    async def admin_close(message: Message) -> None:
        if not _is_admin(message, settings):
            await message.answer("Ця команда тільки для адміна.")
            return
        args = _args(message)
        if len(args) != 1:
            await message.answer("Формат: /admin_close <id_матчу>")
            return
        async with session_factory() as session:
            count = await close_match_markets(session, int(args[0]))
            await session.commit()
        await message.answer(f"Закрито ринків: {count}.")

    @router.message(Command("admin_reset"))
    async def admin_reset(message: Message) -> None:
        if not _is_admin(message, settings):
            await message.answer("Ця команда тільки для адміна.")
            return
        async with session_factory() as session:
            bets_deleted, users_reset = await reset_test_state(session, settings)
            await session.commit()
        await message.answer(
            "Тестовий стан скинуто.\n\n"
            f"Видалено ставок: {bets_deleted}.\n"
            f"Баланс оновлено для гравців: {users_reset}."
        )

    @router.message(Command("admin_reset_user"))
    async def admin_reset_user(message: Message) -> None:
        if not _is_admin(message, settings):
            await message.answer("Ця команда тільки для адміна.")
            return
        args = _args(message)
        if len(args) != 1:
            await message.answer("Формат: /admin_reset_user <@username або telegram_id>")
            return
        async with session_factory() as session:
            user, bets_deleted = await reset_user_state(session, args[0], settings)
            await session.commit()
        if not user:
            await message.answer("Користувача не знайдено.")
            return
        await message.answer(
            f"Користувача {user_label(user)} обнулено.\n"
            f"Видалено ставок: {bets_deleted}.\n"
            f"Баланс: {format_cents(settings.starting_balance_cents + user.playoff_bonus_cents)}."
        )

    @router.message(Command("admin_playoff_bonus"))
    async def admin_playoff_bonus(message: Message) -> None:
        if not _is_admin(message, settings):
            await message.answer("Ця команда тільки для адміна.")
            return
        async with session_factory() as session:
            users_changed, total_granted = await grant_playoff_bonus(session, settings)
            await session.commit()
        await message.answer(
            "Плейоф-бонус нараховано.\n\n"
            f"Гравців оновлено: {users_changed}.\n"
            f"Додано всього: {format_cents(total_granted)}.\n"
            "Бонус не рахується як профіт у статистиці."
        )

    @router.message(Command("admin_sync"))
    async def admin_sync(message: Message) -> None:
        if not _is_admin(message, settings):
            await message.answer("Ця команда тільки для адміна.")
            return
        if not settings.odds_api_key and not settings.odds_api_io_key:
            await message.answer("API для коефіцієнтів не налаштований.")
            return
        try:
            async with session_factory() as session:
                count = await sync_odds(session, build_odds_provider(settings))
                await session.commit()
            await message.answer(f"Оновлено коефіцієнтів: {count}.")
        except Exception as exc:
            await message.answer(f"Не вдалося оновити лінії: {exc}")

    return router


class BetPlacementResult:
    def __init__(self, user_text: str, group_text: str):
        self.user_text = user_text
        self.group_text = group_text


async def _matches_view(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    page: int,
):
    cutoff = datetime.now(timezone.utc) + timedelta(minutes=settings.bet_close_minutes)
    async with session_factory() as session:
        rows = (
            await session.scalars(
                select(Match)
                .where(Match.kickoff_at > cutoff, Match.status == MatchStatus.scheduled)
                .order_by(Match.kickoff_at, Match.id)
            )
        ).all()
    unique_matches = _dedupe_matches(rows)
    offset = max(page, 0) * MATCHES_PER_PAGE
    matches = unique_matches[offset : offset + MATCHES_PER_PAGE]
    has_next = len(unique_matches) > offset + MATCHES_PER_PAGE
    if not matches:
        return (
            "Поки немає синхронізованих майбутніх матчів. Адмін може натиснути /admin_sync.",
            main_menu_keyboard(),
        )
    lines = ["Оберіть матч:", f"Сторінка {page + 1}", ""]
    lines.extend(match_line(match) for match in matches)
    return "\n\n".join(lines), matches_keyboard(matches, page, has_next)

async def _today_matches_view(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    page: int,
):
    tz = ZoneInfo(settings.app_timezone)
    now_local = datetime.now(tz)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)
    cutoff = datetime.now(timezone.utc) + timedelta(minutes=settings.bet_close_minutes)
    async with session_factory() as session:
        rows = (
            await session.scalars(
                select(Match)
                .where(
                    Match.kickoff_at >= start_utc,
                    Match.kickoff_at < end_utc,
                    Match.kickoff_at > cutoff,
                    Match.status == MatchStatus.scheduled,
                )
                .order_by(Match.kickoff_at, Match.id)
            )
        ).all()
    unique_matches = _dedupe_matches(rows)
    offset = max(page, 0) * MATCHES_PER_PAGE
    matches = unique_matches[offset : offset + MATCHES_PER_PAGE]
    has_next = len(unique_matches) > offset + MATCHES_PER_PAGE
    if not matches:
        return (
            "📅 Ставки на сьогодні\n\nНа сьогодні матчів для ставок немає.",
            main_menu_keyboard(),
        )
    lines = ["📅 Ставки на сьогодні", f"Сторінка {page + 1}", ""]
    lines.extend(match_line(match) for match in matches)
    return "\n\n".join(lines), matches_keyboard(matches, page, has_next, page_callback="m:today")

async def _odds_view(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    match_id: int,
    page: int,
):
    async with session_factory() as session:
        match = await session.scalar(select(Match).where(Match.id == match_id))
        if not match:
            raise ValueError("Матч не знайдено.")
        kickoff_at = _aware_utc(match.kickoff_at)
        close_at = kickoff_at - timedelta(minutes=settings.bet_close_minutes)
        if match.status != MatchStatus.scheduled or datetime.now(timezone.utc) >= close_at:
            return (
                f"Прийом ставок на цей матч уже закрито.\n\n{match_title(match)}",
                matches_keyboard([], 0, False),
            )
        rows = (
            await session.scalars(
                select(OddsSnapshot)
                .join(OddsSnapshot.market)
                .where(Market.match_id == match_id, Market.status == MarketStatus.open)
                .options(selectinload(OddsSnapshot.market).selectinload(Market.match))
                .order_by(OddsSnapshot.id.desc())
                .limit(250)
            )
        ).all()
    odds_blocks = _odds_blocks(rows)
    offset = max(page, 0) * ODDS_BLOCKS_PER_PAGE
    page_blocks = odds_blocks[offset : offset + ODDS_BLOCKS_PER_PAGE]
    has_next = len(odds_blocks) > offset + ODDS_BLOCKS_PER_PAGE
    if not page_blocks:
        return "Для цього матчу немає відкритих ринків.", matches_keyboard([], 0, False)
    lines = [
        f"🏟 {match_title(match)}",
        f"🕐 {_aware_utc(match.kickoff_at).strftime('%Y-%m-%d %H:%M UTC')}",
        "🟢 Ставки відкриті",
        "",
        "👇 Натисніть потрібний коефіцієнт. Після цього бот покаже підтвердження ставки.",
        "",
        "ℹ️ 1X2, подвійний шанс, тотали, фори й обидві заб’ють рахуються за 90 хв.",
        "🏁 Прохід далі рахується з овертаймом і пенальті.",
        "",
    ]
    for block in page_blocks:
        lines.append(f"▾ {market_block_title(block)}")
        lines.append("   " + "  |  ".join(odds_line(option) for option in block[:3]))
        if len(block) > 3:
            lines.extend(f"   {odds_line(option)}" for option in block[3:])
        lines.append("")
    return "\n".join(lines), odds_keyboard(match_id, page_blocks, page, has_next)


def _odds_blocks(rows: list[OddsSnapshot]) -> list[list[OddsSnapshot]]:
    latest_by_selection: dict[tuple, OddsSnapshot] = {}
    for option in rows:
        key = (
            option.market.type,
            option.market.line,
            option.market.selection_scope,
            option.selection,
        )
        if key not in latest_by_selection:
            latest_by_selection[key] = option

    blocks: dict[tuple, list[OddsSnapshot]] = {}
    for option in latest_by_selection.values():
        if option.market.type == MarketType.spreads:
            key = (MarketType.spreads, abs(option.market.line or Decimal("0")))
        elif option.market.type == MarketType.totals:
            key = (MarketType.totals, option.market.line)
        else:
            key = (option.market.type, None)
        blocks.setdefault(key, []).append(option)

    for key, block in list(blocks.items()):
        if key[0] == MarketType.spreads:
            blocks[key] = _latest_spread_pair(block)

    total_keys = [key for key in blocks if key[0] == MarketType.totals]
    spread_keys = [key for key in blocks if key[0] == MarketType.spreads]
    selected_keys = [
        key
        for key in blocks
        if key[0]
        in {
            MarketType.h2h,
            MarketType.double_chance,
            MarketType.to_qualify,
            MarketType.btts,
        }
    ]
    selected_keys.extend(_three_balanced_market_keys(total_keys, blocks))
    selected_keys.extend(_three_balanced_market_keys(spread_keys, blocks))

    type_rank = {
        MarketType.h2h: 0,
        MarketType.double_chance: 1,
        MarketType.to_qualify: 2,
        MarketType.totals: 3,
        MarketType.spreads: 4,
        MarketType.btts: 5,
    }
    selected_keys.sort(key=lambda key: (type_rank.get(key[0], 9), str(key[1] or "")))

    def selection_rank(option: OddsSnapshot) -> tuple[int, str]:
        normalized = option.selection.lower()
        if option.market.match and option.selection == option.market.match.home_team:
            return (0, option.selection)
        if normalized == "draw":
            return (1, option.selection)
        if option.market.match and option.selection == option.market.match.away_team:
            return (2, option.selection)
        if normalized.startswith("over"):
            return (0, option.selection)
        if normalized.startswith("under"):
            return (1, option.selection)
        if normalized == "yes":
            return (0, option.selection)
        if normalized == "no":
            return (1, option.selection)
        return (3, option.selection)

    return [sorted(blocks[key], key=selection_rank) for key in selected_keys]


def _latest_spread_pair(block: list[OddsSnapshot]) -> list[OddsSnapshot]:
    pairs = []
    for first in block:
        for second in block:
            if first.id >= second.id or first.selection == second.selection:
                continue
            first_line = first.market.line or Decimal("0")
            second_line = second.market.line or Decimal("0")
            if first_line + second_line == 0:
                pairs.append((first, second))
    if not pairs:
        latest_by_team: dict[str, OddsSnapshot] = {}
        for option in sorted(block, key=lambda row: row.id, reverse=True):
            latest_by_team.setdefault(option.selection, option)
        return list(latest_by_team.values())[:2]
    return list(max(pairs, key=lambda pair: min(pair[0].id, pair[1].id)))


def _three_balanced_market_keys(
    keys: list[tuple],
    blocks: dict[tuple, list[OddsSnapshot]],
) -> list[tuple]:
    if len(keys) <= 3:
        return sorted(keys, key=lambda key: key[1] or Decimal("0"))

    def balance(key: tuple) -> tuple[Decimal, Decimal]:
        prices = [option.decimal_odds for option in blocks[key]]
        difference = abs(prices[0] - prices[1]) if len(prices) >= 2 else Decimal("999")
        return difference, abs(key[1] or Decimal("0"))

    main_key = min(keys, key=balance)
    main_line = main_key[1] or Decimal("0")
    selected = sorted(
        keys,
        key=lambda key: (
            abs((key[1] or Decimal("0")) - main_line),
            balance(key),
        ),
    )[:3]
    return sorted(selected, key=lambda key: key[1] or Decimal("0"))


def _dedupe_matches(matches: list[Match]) -> list[Match]:
    selected: list[Match] = []
    for match in sorted(
        matches,
        key=lambda row: (
            not str(row.api_id).startswith("odds_api_io:"),
            row.id or 0,
        ),
    ):
        kickoff = _aware_utc(match.kickoff_at)
        duplicate = any(
            canonical_team_name(existing.home_team) == canonical_team_name(match.home_team)
            and canonical_team_name(existing.away_team) == canonical_team_name(match.away_team)
            and abs((_aware_utc(existing.kickoff_at) - kickoff).total_seconds()) <= 900
            for existing in selected
        )
        if not duplicate:
            selected.append(match)
    return sorted(selected, key=lambda row: (_aware_utc(row.kickoff_at), row.id or 0))


async def _single_stake_view(
    session_factory: async_sessionmaker[AsyncSession],
    telegram_id: int,
    odds_id: int,
) -> tuple[str, InlineKeyboardMarkup]:
    async with session_factory() as session:
        odds = await session.scalar(
            select(OddsSnapshot)
            .where(OddsSnapshot.id == odds_id)
            .options(selectinload(OddsSnapshot.market).selectinload(Market.match))
        )
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    if not odds:
        raise BettingError("Коефіцієнт не знайдено.")
    if not user:
        raise BettingError("Спочатку натисни /start.")
    text = (
        "Одиночна ставка:\n"
        f"{match_title(odds.market.match)}\n"
        f"{odds_line(odds)}\n\n"
        f"💵 Доступний баланс: {format_money(user.balance_cents)}\n\n"
        "Обери суму кнопкою або напиши свою суму повідомленням, наприклад 4 або 4.50:"
    )
    return text, stake_keyboard(odds.id, odds.market.match_id)


async def _bet_confirmation_view(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    telegram_id: int,
    odds_id: int,
    stake_cents: int,
) -> tuple[str, InlineKeyboardMarkup]:
    if stake_cents < settings.min_stake_cents:
        raise BettingError(f"Мінімальна ставка: {format_cents(settings.min_stake_cents)}.")
    async with session_factory() as session:
        odds = await session.scalar(
            select(OddsSnapshot)
            .where(OddsSnapshot.id == odds_id)
            .options(selectinload(OddsSnapshot.market).selectinload(Market.match))
        )
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    if not odds:
        raise BettingError("Такий варіант ставки не знайдено.")
    if not user:
        raise BettingError("Спочатку натисни /start.")
    if user.balance_cents < stake_cents:
        raise BettingError("Недостатньо коштів на балансі.")

    match = odds.market.match
    close_at = _aware_utc(match.kickoff_at) - timedelta(minutes=settings.bet_close_minutes)
    if odds.market.status != MarketStatus.open or match.status != MatchStatus.scheduled:
        raise BettingError("Цей ринок уже закритий.")
    if datetime.now(timezone.utc) >= close_at:
        raise BettingError("Прийом ставок на цей матч уже закрито.")
    potential_payout = int(stake_cents * odds.decimal_odds)
    text = (
        "Підтверди ставку:\n\n"
        f"{match_title(match)}\n"
        f"{_market_name(odds.market)} · {odds.selection} @ {format_decimal(odds.decimal_odds)}\n\n"
        f"Сума: {format_cents(stake_cents)}\n"
        f"Можливий виграш: {format_cents(potential_payout)}\n"
        f"Баланс до ставки: {format_cents(user.balance_cents)}\n"
        f"Після ставки: {format_cents(user.balance_cents - stake_cents)}"
    )
    return text, confirm_bet_keyboard(odds.id, stake_cents, odds.market.match_id)


async def _place_bet_by_id(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    telegram_user,
    odds_id: int,
    stake_cents: int,
) -> BetPlacementResult:
    async with session_factory() as session:
        await get_or_create_user(
            session,
            telegram_user.id,
            telegram_user.username,
            telegram_user.first_name,
            settings,
        )
        placed = await place_bet(session, telegram_user.id, odds_id, stake_cents, settings)
        user = await session.scalar(select(User).where(User.telegram_id == telegram_user.id))
        odds = await session.scalar(
            select(OddsSnapshot)
            .where(OddsSnapshot.id == odds_id)
            .options(selectinload(OddsSnapshot.market).selectinload(Market.match))
        )
        await session.commit()

    match = odds.market.match
    player = user_label(user)
    potential_payout = int(placed.stake_cents * placed.locked_decimal_odds)
    user_text = (
        "✅ Ставку прийнято\n\n"
        f"#{placed.id} · {match_title(match)}\n"
        f"{_market_name(odds.market)} · {placed.selection} @ {format_decimal(placed.locked_decimal_odds)}\n"
        f"Сума: {format_cents(placed.stake_cents)}\n"
        f"Можливий виграш: {format_cents(potential_payout)}"
    )
    group_text = (
        "🎟 Нова ставка\n\n"
        f"{player}\n"
        f"{match_title(match)}\n"
        f"{_market_name(odds.market)} · {placed.selection} @ {format_decimal(placed.locked_decimal_odds)}\n"
        f"{format_cents(placed.stake_cents)} → {format_cents(potential_payout)}"
    )
    return BetPlacementResult(user_text=user_text, group_text=group_text)

async def _bet_slip_view(
    session_factory: async_sessionmaker[AsyncSession],
    telegram_id: int,
) -> tuple[str, InlineKeyboardMarkup]:
    async with session_factory() as session:
        slip = await get_bet_slip(session, telegram_id)
    has_items = bool(slip and slip.items)
    can_place = bool(slip and len(slip.items) >= 2)
    logger.debug(
        "Opened express slip: telegram_id=%s slip_id=%s item_count=%s",
        telegram_id,
        getattr(slip, "id", None),
        len(slip.items) if slip else 0,
    )
    return _bet_slip_text(slip), express_coupon_keyboard(can_place, has_items, _bet_slip_remove_buttons(slip))


def _bet_slip_added_text(slip) -> str:
    if not slip or not slip.items:
        return "✅ Додано в експрес\n\nПоточний купон порожній."

    lines = ["✅ Додано в експрес", "", "Поточний купон:"]
    for index, item in enumerate(slip.items, start=1):
        lines.append(f"{index}) {format_match_pair(item.match)}")
        lines.append(f"   📌 {format_market_selection(item.market, item.selection)}")
        lines.append(f"   📈 Кеф: {format_odds(item.locked_decimal_odds)}")
        lines.append("")
    lines.append("Додай ще мінімум одну подію або відкрий “🧾 Мій купон”.")
    return "\n".join(lines).strip()


def _bet_slip_text(slip) -> str:
    if not slip or not slip.items:
        return "🧾 Мій купон\n\nКупон порожній. Відкрий матч і додай мінімум 2 вибори в експрес."

    odds_values = [Decimal(item.locked_decimal_odds) for item in slip.items]
    total_odds = calculate_express_total_odds(odds_values)
    lines = [
        "🧾 Мій купон",
        f"📈 Загальний кеф: {format_odds(total_odds)}",
        "💵 Суму обереш після натискання “Поставити експрес”",
        "",
    ]
    for index, item in enumerate(slip.items, start=1):
        lines.append(f"{index}. {format_match_pair(item.match)}")
        lines.append(f"   📌 {format_market_selection(item.market, item.selection)}")
        lines.append(f"   📈 Кеф: {format_odds(item.locked_decimal_odds)}")
        lines.append("")
    if len(slip.items) < 2:
        lines.append("Для експресу потрібно мінімум 2 події.")
    return "\n".join(lines).strip()


def _bet_slip_remove_buttons(slip) -> list[tuple[int, str]]:
    if not slip or not slip.items:
        return []
    return [(item.id, str(index)) for index, item in enumerate(slip.items, start=1)]


async def _express_stake_view(
    session_factory: async_sessionmaker[AsyncSession],
    telegram_id: int,
) -> tuple[str, InlineKeyboardMarkup]:
    async with session_factory() as session:
        slip = await get_bet_slip(session, telegram_id)
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    if not slip or len(slip.items) < 2:
        raise BettingError("Для експресу потрібно мінімум 2 події.")
    if not user:
        raise BettingError("Спочатку натисни /start.")
    return (
        _bet_slip_text(slip)
        + f"\n\n💵 Доступний баланс: {format_money(user.balance_cents)}"
        + "\nОбери суму експресу або введи свою.",
        express_stake_keyboard(),
    )


async def _express_confirmation_view(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    telegram_id: int,
    stake_cents: int,
) -> tuple[str, InlineKeyboardMarkup]:
    if stake_cents < settings.min_stake_cents:
        raise BettingError(f"Мінімальна ставка: {format_cents(settings.min_stake_cents)}.")
    async with session_factory() as session:
        slip = await get_bet_slip(session, telegram_id)
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    if not slip or len(slip.items) < 2:
        raise BettingError("Для експресу потрібно мінімум 2 події.")
    if not user:
        raise BettingError("Спочатку натисни /start.")
    if user.balance_cents < stake_cents:
        raise BettingError("Недостатньо коштів на балансі.")

    total_odds = calculate_express_total_odds([Decimal(item.locked_decimal_odds) for item in slip.items])
    potential = calculate_express_payout(stake_cents, total_odds)
    text = (
        _bet_slip_text(slip)
        + "\n\n✅ Підтверди експрес"
        + f"\n💵 Сума: {format_money(stake_cents)}"
        + f"\n🏆 Можливий виграш: {format_money(potential)}"
        + f"\nБаланс до ставки: {format_money(user.balance_cents)}"
        + f"\nПісля ставки: {format_money(user.balance_cents - stake_cents)}"
    )
    return text, confirm_express_keyboard(stake_cents)


async def _place_express_by_user(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    telegram_user,
    stake_cents: int,
) -> BetPlacementResult:
    async with session_factory() as session:
        await get_or_create_user(
            session,
            telegram_user.id,
            telegram_user.username,
            telegram_user.first_name,
            settings,
        )
        placed = await place_express_bet(session, telegram_user.id, stake_cents, settings)
        express = await session.scalar(
            select(ExpressBet)
            .where(ExpressBet.id == placed.id)
            .options(
                selectinload(ExpressBet.user),
                selectinload(ExpressBet.items).selectinload(ExpressBetItem.match),
                selectinload(ExpressBet.items).selectinload(ExpressBetItem.market),
            )
        )
        await session.commit()

    user_text = "✅ Експрес прийнято\n\n" + format_express_bet_card(express)
    group_text = "🧾 Новий експрес\n\n" + format_express_bet_card(express, show_user=True)
    return BetPlacementResult(user_text=user_text, group_text=group_text)

async def _announce_to_group(
    session_factory: async_sessionmaker[AsyncSession],
    bot: Bot,
    text: str,
    source_chat_id: int,
    settlements_only: bool = False,
) -> None:
    async with session_factory() as session:
        group = await get_primary_group_chat(session)
    if not group:
        return
    if group.chat_id == source_chat_id:
        return
    if settlements_only and not group.announce_settlements:
        return
    if not settlements_only and not group.announce_bets:
        return
    await bot.send_message(group.chat_id, text, reply_markup=group_menu_keyboard())


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


async def _settlement_results_for_targets(
    session: AsyncSession,
    match: Match | None,
    single_bet_ids: list[int],
    express_bet_ids: list[int],
) -> str:
    if not match:
        return ""
    single_bets = []
    if single_bet_ids:
        single_bets = (
            await session.scalars(
                select(Bet)
                .where(Bet.id.in_(single_bet_ids), Bet.status != BetStatus.open)
                .options(
                    selectinload(Bet.user),
                    selectinload(Bet.market).selectinload(Market.match),
                )
                .order_by(Bet.id)
            )
        ).all()

    express_bets = []
    if express_bet_ids:
        express_bets = (
            await session.scalars(
                select(ExpressBet)
                .where(ExpressBet.id.in_(express_bet_ids), ExpressBet.status != BetStatus.open)
                .options(
                    selectinload(ExpressBet.user),
                    selectinload(ExpressBet.items),
                )
                .order_by(ExpressBet.id)
            )
        ).all()
    return _settlement_results_text(match, list(single_bets), list(express_bets))


def _settlement_results_text(
    match: Match,
    single_bets: list[Bet],
    express_bets: list[ExpressBet],
) -> str:
    cards = [_settled_single_result_card(bet, match) for bet in single_bets]
    cards.extend(_settled_express_result_card(express) for express in express_bets)
    cards = [card for card in cards if card]
    if not cards:
        return ""
    return "🎯 Результати ставок\n\n" + "\n\n━━━━━━━━━━━━\n\n".join(cards)


def _settled_single_result_card(bet: Bet, match: Match) -> str:
    if bet.status == BetStatus.won:
        title = "✅ Ставка зайшла"
    elif bet.status == BetStatus.lost:
        title = "❌ Ставка не зайшла"
    else:
        title = "↩️ Ставку повернено"

    lines = [
        title,
        "",
        f"👤 {user_label(bet.user)}",
        format_match_pair(match),
        f"📌 {format_market_selection(bet.market, bet.selection)}",
        f"📈 Кеф: {format_odds(bet.locked_decimal_odds)}",
    ]
    if bet.status == BetStatus.won:
        profit = bet.payout_cents - bet.stake_cents
        lines.append(f"💵 {format_money(bet.stake_cents)} → {format_money(bet.payout_cents)}")
        lines.append(f"📊 Профіт: {format_profit(profit)}")
    elif bet.status == BetStatus.lost:
        lines.append(f"💸 Програш: {format_profit(-bet.stake_cents)}")
    else:
        lines.append(f"↩️ Повернено: {format_money(bet.payout_cents or bet.stake_cents)}")
    return "\n".join(lines)


def _settled_express_result_card(express: ExpressBet) -> str:
    if express.status == BetStatus.open:
        return ""
    if express.status == BetStatus.won:
        title = "✅ Експрес зайшов"
    elif express.status == BetStatus.lost:
        title = "❌ Експрес не зайшов"
    else:
        title = "↩️ Експрес повернено"

    items = list(express.items or [])
    lines = [
        title,
        "",
        f"👤 {user_label(express.user)}",
        f"🧾 Експрес #{express.id}",
        f"📈 Загальний кеф: {format_odds(express.total_odds)}",
        f"💵 Сума: {format_money(express.stake_cents)}",
        f"Подій: {len(items)}",
    ]
    if express.status == BetStatus.won:
        profit = express.payout_cents - express.stake_cents
        lines.append(f"🏆 Виграш: {format_money(express.payout_cents)}")
        lines.append(f"📊 Профіт: {format_profit(profit)}")
    elif express.status == BetStatus.lost:
        lines.append(f"💸 Програш: {format_profit(-express.stake_cents)}")
    else:
        lines.append(f"↩️ Повернено: {format_money(express.payout_cents or express.stake_cents)}")
    return "\n".join(lines)


async def _mybets_text(session_factory: async_sessionmaker[AsyncSession], telegram_id: int) -> str:
    text, _ = await _mybets_view(session_factory, telegram_id, "all")
    return text


async def _mybets_view(
    session_factory: async_sessionmaker[AsyncSession],
    telegram_id: int,
    status_filter: str,
    page: int = 0,
) -> tuple[str, InlineKeyboardMarkup]:
    status_filter = status_filter if status_filter in {"open", "won", "lost", "void", "all"} else "open"
    page = max(page, 0)
    offset = page * MY_BETS_PER_PAGE
    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        if not user:
            return "Спочатку натисни /start.", main_menu_keyboard()
        statement = (
            select(Bet)
            .where(Bet.user_id == user.id)
            .options(selectinload(Bet.market).selectinload(Market.match))
        )
        express_statement = (
            select(ExpressBet)
            .where(ExpressBet.user_id == user.id)
            .options(
                selectinload(ExpressBet.items).selectinload(ExpressBetItem.match),
                selectinload(ExpressBet.items).selectinload(ExpressBetItem.market),
            )
        )
        if status_filter == "void":
            statement = statement.where(Bet.status.in_([BetStatus.void, BetStatus.push]))
            express_statement = express_statement.where(ExpressBet.status.in_([BetStatus.void, BetStatus.push]))
        elif status_filter != "all":
            statement = statement.where(Bet.status == BetStatus(status_filter))
            express_statement = express_statement.where(ExpressBet.status == BetStatus(status_filter))
        bets = (await session.scalars(statement)).all()
        express_bets = (await session.scalars(express_statement)).all()

    entries = [("single", bet) for bet in bets] + [("express", express) for express in express_bets]
    entries.sort(key=lambda entry: entry[1].created_at, reverse=True)
    page_entries = entries[offset : offset + MY_BETS_PER_PAGE + 1]
    has_next = len(page_entries) > MY_BETS_PER_PAGE
    visible_entries = page_entries[:MY_BETS_PER_PAGE]
    empty = {
        "open": "Поки що відкритих ставок немає.",
        "won": "Поки що виграних ставок немає.",
        "lost": "Поки що програних ставок немає.",
        "void": "Поки що повернених ставок немає.",
        "all": "Поки що ставок немає.",
    }
    if not visible_entries:
        return (
            format_bets_list(
                f"🎟 Мої ставки · {_mybets_filter_title(status_filter)}",
                [],
                empty[status_filter],
            ),
            mybets_filter_keyboard(status_filter, page, page > 0, False),
        )

    title = f"🎟 Мої ставки · {_mybets_filter_title(status_filter)}"
    if page > 0 or has_next:
        title += f" · сторінка {page + 1}"
    return (
        format_bets_list(
            title,
            [
                format_single_bet_card(entry)
                if entry_type == "single"
                else format_express_bet_card(entry)
                for entry_type, entry in visible_entries
            ],
            "Ставок немає.",
        ),
        mybets_filter_keyboard(status_filter, page, page > 0, has_next),
    )


async def _openbets_text(session_factory: async_sessionmaker[AsyncSession]) -> str:
    text, _ = await _openbets_view(session_factory, page=0)
    return text


async def _admin_debug_settlement_text(
    session_factory: async_sessionmaker[AsyncSession],
) -> str:
    async with session_factory() as session:
        single_bets = (
            await session.scalars(
                select(Bet)
                .where(Bet.status == BetStatus.open)
                .options(
                    selectinload(Bet.user),
                    selectinload(Bet.market).selectinload(Market.match),
                )
                .order_by(Bet.id.desc())
                .limit(30)
            )
        ).all()
        express_bets = (
            await session.scalars(
                select(ExpressBet)
                .where(ExpressBet.status == BetStatus.open)
                .options(
                    selectinload(ExpressBet.user),
                    selectinload(ExpressBet.items).selectinload(ExpressBetItem.match),
                    selectinload(ExpressBet.items).selectinload(ExpressBetItem.market),
                )
                .order_by(ExpressBet.id.desc())
                .limit(20)
            )
        ).all()

    lines = [
        "🛠 Діагностика розрахунку",
        "",
        f"Відкриті одиночні ставки: {len(single_bets)}",
        f"Відкриті експреси: {len(express_bets)}",
    ]

    if single_bets:
        lines.extend(["", "🎟 Одиночні:"])
        for bet in single_bets[:10]:
            match = bet.market.match if bet.market else None
            if match:
                score = _match_score_text(match)
                lines.append(
                    f"#{bet.id} · match_id {bet.match_id} · {match.status.value} · {score}\n"
                    f"{format_match_pair(match)}\n"
                    f"👤 {user_label(bet.user)} · {format_cents(bet.stake_cents)} "
                    f"@ {format_decimal(bet.locked_decimal_odds)}"
                )
            else:
                lines.append(f"#{bet.id} · match_id {bet.match_id} · матч не завантажено")

    if express_bets:
        lines.extend(["", "🧾 Експреси:"])
        for express in express_bets[:10]:
            lines.append(
                f"Експрес #{express.id} · {user_label(express.user)} · "
                f"{format_cents(express.stake_cents)} @ {format_decimal(express.total_odds)}"
            )
            for item in express.items:
                match = item.match
                if match:
                    lines.append(
                        f"  • item #{item.id} · match_id {item.match_id} · "
                        f"{item.status.value} · {match.status.value} · {_match_score_text(match)}"
                    )
                else:
                    lines.append(
                        f"  • item #{item.id} · match_id {item.match_id} · {item.status.value}"
                    )

    if len(single_bets) > 10 or len(express_bets) > 10:
        lines.append("")
        lines.append("Показано перші 10 записів кожного типу.")
    return "\n".join(lines)


def _match_score_text(match: Match) -> str:
    if match.home_score is None or match.away_score is None:
        return "рахунок не задано"
    return f"{match.home_score}:{match.away_score}"


async def _openbets_view(
    session_factory: async_sessionmaker[AsyncSession],
    page: int,
) -> tuple[str, InlineKeyboardMarkup]:
    page = max(page, 0)
    async with session_factory() as session:
        bets = (
            await session.scalars(
                select(Bet)
                .where(Bet.status == BetStatus.open)
                .options(
                    selectinload(Bet.user),
                    selectinload(Bet.market).selectinload(Market.match),
                )
            )
        ).all()
        express_bets = (
            await session.scalars(
                select(ExpressBet)
                .where(ExpressBet.status == BetStatus.open)
                .options(
                    selectinload(ExpressBet.user),
                    selectinload(ExpressBet.items),
                )
            )
        ).all()

    entries = [("single", bet) for bet in bets] + [("express", express) for express in express_bets]
    entries.sort(key=lambda entry: entry[1].created_at, reverse=True)
    total_pages = max(1, (len(entries) + OPEN_BETS_PER_PAGE - 1) // OPEN_BETS_PER_PAGE)
    page = min(page, total_pages - 1)
    offset = page * OPEN_BETS_PER_PAGE
    page_entries = entries[offset : offset + OPEN_BETS_PER_PAGE]
    if not page_entries:
        return (
            "👀 Відкриті ставки\n\nПоки що відкритих ставок немає.",
            openbets_pagination_keyboard(page, page > 0, False),
        )

    cards = [
        _compact_open_single_bet_card(item) if kind == "single" else _compact_open_express_bet_card(item)
        for kind, item in page_entries
    ]
    text = format_bets_list("👀 Відкриті ставки", cards, "Поки що відкритих ставок немає.")
    text += f"\n\nСторінка {page + 1}/{total_pages}"
    return (
        text,
        openbets_pagination_keyboard(page, page > 0, page < total_pages - 1),
    )


def _compact_open_single_bet_card(bet: Bet) -> str:
    match = bet.market.match if bet.market else None
    potential = int(bet.stake_cents * bet.locked_decimal_odds)
    lines = [f"🎟 #{bet.id} · {user_label(bet.user)}"]
    if match:
        lines.append(format_match_pair(match))
    else:
        lines.append(f"Матч #{bet.match_id}")
    lines.append(f"📌 {_compact_open_selection(bet.market, bet.selection)} @ {format_odds(bet.locked_decimal_odds)}")
    lines.append(f"💵 {format_money(bet.stake_cents)} → {format_money(potential)}")
    return "\n".join(lines)


def _compact_open_express_bet_card(express: ExpressBet) -> str:
    return "\n".join(
        [
            f"🧾 Експрес #{express.id} · {user_label(express.user)}",
            f"📈 Кеф: {format_odds(express.total_odds)}",
            f"💵 {format_money(express.stake_cents)} → {format_money(express.potential_payout_cents)}",
            f"Подій: {len(express.items)}",
        ]
    )


def _compact_open_selection(market: Market | None, selection: str) -> str:
    if not market:
        return selection
    return format_market_selection(market, selection).split(": ", 1)[-1]


async def _balance_text(
    session_factory: async_sessionmaker[AsyncSession],
    telegram_id: int,
    settings: Settings,
) -> str:
    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        if not user:
            return "Спочатку натисни /start."
        open_single_stakes = sum(
            bet.stake_cents
            for bet in (
                await session.scalars(
                    select(Bet).where(Bet.user_id == user.id, Bet.status == BetStatus.open)
                )
            ).all()
        )
        open_express_stakes = sum(
            express.stake_cents
            for express in (
                await session.scalars(
                    select(ExpressBet).where(ExpressBet.user_id == user.id, ExpressBet.status == BetStatus.open)
                )
            ).all()
        )
        open_stakes = open_single_stakes + open_express_stakes
    bankroll = user.balance_cents + open_stakes
    profit = bankroll - _user_profit_baseline_cents(user, settings)
    return (
        "Твій баланс:\n\n"
        f"Доступно: {format_cents(user.balance_cents)}\n"
        f"У відкритих ставках: {format_cents(open_stakes)}\n"
        f"Банкрол: {format_cents(bankroll)}\n"
        f"Плюс/мінус: {format_cents(profit)}"
    )


async def _stats_text(
    session_factory: async_sessionmaker[AsyncSession],
    telegram_id: int,
    settings: Settings,
) -> str:
    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        if not user:
            return "Спочатку натисни /start."
        bets = (await session.scalars(select(Bet).where(Bet.user_id == user.id))).all()
        express_bets = (
            await session.scalars(select(ExpressBet).where(ExpressBet.user_id == user.id))
        ).all()

    open_bets = [bet for bet in bets if bet.status == BetStatus.open]
    open_express_bets = [express for express in express_bets if express.status == BetStatus.open]
    won = [bet for bet in bets if bet.status == BetStatus.won]
    won_express = [express for express in express_bets if express.status == BetStatus.won]
    lost = [bet for bet in bets if bet.status == BetStatus.lost]
    lost_express = [express for express in express_bets if express.status == BetStatus.lost]
    returned = [bet for bet in bets if bet.status in {BetStatus.push, BetStatus.void}]
    returned_express = [
        express for express in express_bets if express.status in {BetStatus.push, BetStatus.void}
    ]
    won_count = len(won) + len(won_express)
    lost_count = len(lost) + len(lost_express)
    returned_count = len(returned) + len(returned_express)
    settled_count = won_count + lost_count
    win_rate = int(round((won_count / settled_count) * 100)) if settled_count else 0
    open_stakes = sum(bet.stake_cents for bet in open_bets) + sum(express.stake_cents for express in open_express_bets)
    bankroll = user.balance_cents + open_stakes
    profit = bankroll - _user_profit_baseline_cents(user, settings)
    odds_values = [Decimal(bet.locked_decimal_odds) for bet in bets] + [
        Decimal(express.total_odds) for express in express_bets
    ]
    best_profits = [
        *(_settled_profit_cents(bet) for bet in won),
        *(_settled_profit_cents(express) for express in won_express),
    ]
    best_profit = max(best_profits, default=0)
    won_profits = [_settled_profit_cents(entry) for entry in [*won, *won_express]]
    lost_stakes = [entry.stake_cents for entry in [*lost, *lost_express]]
    average_odds = _average_decimal(odds_values)
    total_won = sum(won_profits)
    total_lost = sum(lost_stakes)
    average_win = _average_cents(won_profits)
    average_loss = _average_cents(lost_stakes)
    logger.debug(
        "Built stats: telegram_id=%s single_bets=%s express_bets=%s open_stakes=%s",
        telegram_id,
        len(bets),
        len(express_bets),
        open_stakes,
    )

    return (
        f"📊 Статистика {user_label(user)}\n\n"
        f"Банкрол: {format_cents(bankroll)} ({_profit_text(profit)})\n"
        f"Доступно: {format_cents(user.balance_cents)}\n"
        f"У відкритих: {format_cents(open_stakes)}\n\n"
        f"Ставок всього: {len(bets) + len(express_bets)}\n"
        f"Відкриті: {len(open_bets) + len(open_express_bets)} · виграні: {won_count} · "
        f"програні: {lost_count} · void/push: {returned_count}\n"
        f"Win rate: {win_rate}%\n"
        f"Найкращий чистий виграш: {_profit_text(best_profit)}\n\n"
        "📈 Деталі ставок\n"
        f"🎯 Середній кеф: {format_decimal(average_odds)}\n"
        f"💚 Середній виграш: {_profit_text(average_win)}\n"
        f"💔 Середній програш: {_profit_text(-average_loss)}\n"
        f"🏆 Виграно всього: {_profit_text(total_won)}\n"
        f"📉 Програно всього: {_profit_text(-total_lost)}"
    )


def _average_cents(values: list[int]) -> int:
    if not values:
        return 0
    return int(round(sum(values) / len(values)))


def _average_decimal(values: list[Decimal]) -> Decimal:
    if not values:
        return Decimal("0.00")
    return (sum(values) / Decimal(len(values))).quantize(Decimal("0.01"))


def _settled_profit_cents(entry) -> int:
    payout = getattr(entry, "payout_cents", None)
    if payout is None:
        payout = getattr(entry, "potential_payout_cents", None)
    if payout is None:
        locked_odds = getattr(entry, "locked_decimal_odds", None)
        payout = payout_cents(entry.stake_cents, Decimal(locked_odds)) if locked_odds is not None else 0
    return int(payout) - entry.stake_cents


async def _topwins_text(session_factory: async_sessionmaker[AsyncSession]) -> str:
    async with session_factory() as session:
        bets = (
            await session.scalars(
                select(Bet)
                .where(Bet.status == BetStatus.won)
                .options(
                    selectinload(Bet.user),
                    selectinload(Bet.market).selectinload(Market.match),
                )
                .order_by((Bet.payout_cents - Bet.stake_cents).desc())
                .limit(5)
            )
        ).all()
        express_bets = (
            await session.scalars(
                select(ExpressBet)
                .where(ExpressBet.status == BetStatus.won)
                .options(
                    selectinload(ExpressBet.user),
                    selectinload(ExpressBet.items),
                )
                .order_by((ExpressBet.payout_cents - ExpressBet.stake_cents).desc())
                .limit(5)
            )
        ).all()

    entries = list(bets) + list(express_bets)
    entries.sort(key=lambda entry: entry.payout_cents - entry.stake_cents, reverse=True)
    return format_top_wins(entries, limit=5)


async def _leaderboard_text(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> str:
    async with session_factory() as session:
        rows = await leaderboard(session)
    logger.debug("Built leaderboard: rows=%s", len(rows))
    return format_leaderboard(rows, settings.starting_balance_cents, limit=5)


def _user_profit_baseline_cents(user: User, settings: Settings) -> int:
    return settings.starting_balance_cents + (user.playoff_bonus_cents or 0)


def _profit_text(cents: int) -> str:
    return format_profit(cents)

def _help_text() -> str:
    return (
        "Як користуватись ботом:\n\n"
        "1. Відкрий приватний чат з ботом.\n"
        "2. Натисни Матчі.\n"
        "3. Обери матч зі списку.\n"
        "4. Стрілками гортай коефіцієнти.\n"
        "5. Натисни на потрібний варіант.\n"
        "6. Обери суму кнопкою або напиши свою.\n\n"
        "Якщо незрозуміло, що означає фора, тотал або 1X2, натисни Пояснення ставок або напиши /explain.\n\n"
        "Корисні команди: /stats, /topwins, /openbets, /leaderboard.\n\n"
        "Група працює як спільне табло: там видно лідерборд, правила й анонси ставок. "
        "Ставки робимо тільки в приваті, щоб кнопки не конфліктували між людьми."
    )


def _rules_text(settings: Settings) -> str:
    return (
        "Правила фан-ставок:\n\n"
        f"Стартовий баланс: {format_cents(settings.starting_balance_cents)}.\n"
        f"Мінімальна ставка: {format_cents(settings.min_stake_cents)}.\n"
        "Максимального ліміту немає: можна ставити будь-яку суму в межах доступного балансу.\n"
        f"Прийом ставок закривається за {settings.bet_close_minutes} хв до матчу.\n\n"
        "Коефіцієнт фіксується в момент ставки.\n"
        "Якщо ставка виграла: баланс += ставка × коефіцієнт.\n"
        "Якщо програла: ставка не повертається.\n"
        "Якщо push/void: ставка повертається."
    )

def _explain_text() -> str:
    return (
        "Пояснення ставок:\n\n"
        "Основний час\n"
        "1X2, подвійний шанс, тотали, фори й обидві заб’ють рахуються тільки за 90 хвилин + компенсований час.\n"
        "Овертайм і пенальті для цих ставок не враховуються.\n\n"
        "1X2\n"
        "Ставка на результат матчу в основний час.\n"
        "1 - виграє перша команда, X - нічия, 2 - виграє друга команда.\n\n"
        "Подвійний шанс\n"
        "П1 або нічия (1X) - ставка виграє, якщо перша команда переможе або буде нічия.\n"
        "П2 або нічия (X2) - ставка виграє, якщо друга команда переможе або буде нічия.\n\n"
        "Фора / handicap\n"
        "Це віртуальна перевага або мінус до рахунку команди.\n"
        "Австрія +1 означає: до голів Австрії додаємо 1. Якщо після цього Австрія не програла - ставка зіграла. "
        "Наприклад Аргентина 1:1 Австрія, з форою +1 буде 1:2 на користь Австрії.\n"
        "Аргентина -1 означає: Аргентина має виграти мінімум у 2 голи. Якщо виграла рівно в 1 гол - буде повернення для цілої фори.\n\n"
        "Тотал\n"
        "Ставка на кількість голів у матчі.\n"
        "Більше 2.5 - треба 3 або більше голів.\n"
        "Менше 2.5 - треба 0, 1 або 2 голи.\n"
        "Якщо лінія ціла, наприклад 3.0, і в матчі рівно 3 голи - ставка повертається.\n\n"
        "Обидві заб’ють\n"
        "Так - обидві команди мають забити хоча б по одному голу в основний час.\n"
        "Ні - хоча б одна команда не повинна забити.\n\n"
        "Прохід далі\n"
        "Ставка на команду, яка пройде в наступний раунд плейофу.\n"
        "Тут враховується все: основний час, овертайм і серія пенальті.\n\n"
        "Коефіцієнт\n"
        "Якщо поставив $4 на коефіцієнт 2.50 і ставка виграла, отримаєш $10.00. "
        "Чистий плюс буде $6.00, бо $4 вже були списані при ставці."
    )


def _market_name(market: Market) -> str:
    labels = {
        MarketType.h2h: "1X2",
        MarketType.double_chance: "Подвійний шанс",
        MarketType.totals: "Тотал",
        MarketType.spreads: "Фора",
        MarketType.btts: "Обидві заб’ють",
        MarketType.outrights: "Довгострокова",
        MarketType.correct_score: "Точний рахунок",
        MarketType.top_goalscorer: "Бомбардир",
        MarketType.to_qualify: "Прохід далі",
    }
    label = labels.get(market.type, market.type.value)
    if market.line is not None and market.type in {MarketType.totals, MarketType.spreads}:
        return f"{label} {format_decimal(market.line)}"
    return label


def _mybets_filter_title(status_filter: str) -> str:
    return {
        "open": "відкриті",
        "won": "виграні",
        "lost": "програні",
        "void": "void/push",
        "all": "усі",
    }.get(status_filter, "відкриті")


def _detailed_bet_line(bet: Bet) -> str:
    match = bet.market.match if bet.market else None
    potential_or_payout = bet.payout_cents if bet.status != BetStatus.open else int(
        bet.stake_cents * bet.locked_decimal_odds
    )
    match_text = match_title(match) if match else f"Матч #{bet.match_id}"
    status = {
        BetStatus.open: "відкрита",
        BetStatus.won: "виграла",
        BetStatus.lost: "програла",
        BetStatus.push: "повернення",
        BetStatus.void: "скасована",
    }.get(bet.status, bet.status.value)
    return (
        f"#{bet.id} · {match_text}\n"
        f"{_market_name(bet.market)} · {bet.selection} @ {format_decimal(bet.locked_decimal_odds)}\n"
        f"{format_cents(bet.stake_cents)} → {format_cents(potential_or_payout)} · {status}"
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _args(message: Message) -> list[str]:
    text = message.text or ""
    return text.split()[1:]


def _looks_like_amount(text: str | None) -> bool:
    if not text:
        return False
    normalized = _normalize_amount(text)
    if normalized.startswith("/"):
        return False
    parts = normalized.split(".")
    return (
        len(parts) in {1, 2}
        and all(part.isdigit() for part in parts)
        and bool(parts[0])
        and (len(parts) == 1 or len(parts[1]) <= 2)
    )


def _normalize_amount(text: str | None) -> str:
    return (text or "").strip().replace(",", ".")


def _is_admin(message: Message, settings: Settings) -> bool:
    return bool(message.from_user and message.from_user.id in settings.admin_ids)


def _is_group_message(message: Message) -> bool:
    return _is_group_chat(message.chat)


def _is_group_chat(chat) -> bool:
    return chat.type in {"group", "supergroup"}
