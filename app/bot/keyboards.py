from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.formatting import match_button_title, market_title, odds_button_label
from app.models import Match, OddsSnapshot
from app.money import format_cents


BOT_PRIVATE_URL = "https://t.me/StavkiPoFanu_bot"
MATCHES_PER_PAGE = 6
ODDS_BLOCKS_PER_PAGE = 5
STAKE_OPTIONS_CENTS = [100, 500, 1000, 2500]


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏟 Матчі", callback_data="m:p:0")],
            [InlineKeyboardButton(text="📅 Ставки на сьогодні", callback_data="m:today:0")],
            [
                InlineKeyboardButton(text="🎟 Мої ставки", callback_data="u:bets"),
                InlineKeyboardButton(text="🏆 Лідерборд", callback_data="u:board"),
            ],
            [InlineKeyboardButton(text="👀 Відкриті ставки", callback_data="u:openbets")],
            [
                InlineKeyboardButton(text="📊 Статистика", callback_data="u:stats"),
                InlineKeyboardButton(text="💎 Топ виграшів", callback_data="u:topwins"),
            ],
            [
                InlineKeyboardButton(text="💰 Баланс", callback_data="u:balance"),
                InlineKeyboardButton(text="📜 Правила", callback_data="u:rules"),
            ],
            [InlineKeyboardButton(text="📘 Пояснення ставок", callback_data="u:explain")],
            [InlineKeyboardButton(text="ℹ️ Допомога", callback_data="u:help")],
        ]
    )


def group_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎯 Ставити в приваті", url=BOT_PRIVATE_URL)],
            [InlineKeyboardButton(text="📅 Ставки на сьогодні", url=BOT_PRIVATE_URL)],
            [
                InlineKeyboardButton(text="🏆 Лідерборд", callback_data="u:board"),
                InlineKeyboardButton(text="📜 Правила", callback_data="u:rules"),
            ],
            [InlineKeyboardButton(text="👀 Відкриті ставки", callback_data="u:openbets")],
            [InlineKeyboardButton(text="💎 Топ виграшів", callback_data="u:topwins")],
            [InlineKeyboardButton(text="📘 Пояснення ставок", callback_data="u:explain")],
            [InlineKeyboardButton(text="ℹ️ Як граємо?", callback_data="u:help")],
        ]
    )


def group_private_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎯 Відкрити бота для ставки", url=BOT_PRIVATE_URL)],
            [InlineKeyboardButton(text="📅 Ставки на сьогодні", url=BOT_PRIVATE_URL)],
            [
                InlineKeyboardButton(text="🏆 Лідерборд", callback_data="u:board"),
                InlineKeyboardButton(text="📜 Правила", callback_data="u:rules"),
            ],
            [InlineKeyboardButton(text="👀 Відкриті ставки", callback_data="u:openbets")],
            [InlineKeyboardButton(text="💎 Топ виграшів", callback_data="u:topwins")],
            [InlineKeyboardButton(text="📘 Пояснення ставок", callback_data="u:explain")],
        ]
    )


def matches_keyboard(
    matches: list[Match],
    page: int,
    has_next: bool,
    page_callback: str = "m:p",
) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=match_button_title(match), callback_data=f"m:o:{match.id}:0")]
        for match in matches
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"{page_callback}:{page - 1}"))
    if has_next:
        nav.append(InlineKeyboardButton(text="Далі ➡️", callback_data=f"{page_callback}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🏠 Головне меню", callback_data="u:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def odds_keyboard(
    match_id: int,
    odds_blocks: list[list[OddsSnapshot]],
    page: int,
    has_next: bool,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for block in odds_blocks:
        if not block:
            continue
        rows.append([InlineKeyboardButton(text=f"▾ {market_title(block[0])}", callback_data="noop")])
        buttons = [
            InlineKeyboardButton(text=odds_button_label(option), callback_data=f"o:s:{option.id}")
            for option in block
        ]
        for index in range(0, len(buttons), 2):
            rows.append(
                buttons[index : index + 2]
            )

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"m:o:{match_id}:{page - 1}"))
    if has_next:
        nav.append(InlineKeyboardButton(text="Далі ➡️", callback_data=f"m:o:{match_id}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="⬅️ До матчів", callback_data="m:p:0")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def stake_keyboard(odds_id: int, match_id: int) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=format_cents(cents),
                callback_data=f"b:c:{odds_id}:{cents}",
            )
            for cents in STAKE_OPTIONS_CENTS[:2]
        ],
        [
            InlineKeyboardButton(
                text=format_cents(cents),
                callback_data=f"b:c:{odds_id}:{cents}",
            )
            for cents in STAKE_OPTIONS_CENTS[2:]
        ],
        [InlineKeyboardButton(text="✍️ Інша сума", callback_data=f"b:custom:{odds_id}")],
        [InlineKeyboardButton(text="⬅️ До коефіцієнтів", callback_data=f"m:o:{match_id}:0")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_bet_keyboard(odds_id: int, stake_cents: int, match_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Підтвердити",
                    callback_data=f"b:final:{odds_id}:{stake_cents}",
                ),
                InlineKeyboardButton(text="❌ Скасувати", callback_data=f"m:o:{match_id}:0"),
            ],
            [InlineKeyboardButton(text="⬅️ Змінити суму", callback_data=f"o:s:{odds_id}")],
        ]
    )


def openbets_pagination_keyboard(page: int, has_prev: bool, has_next: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    nav = []
    if has_prev:
        nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"u:openbets:p:{page - 1}"))
    if has_next:
        nav.append(InlineKeyboardButton(text="➡️ Далі", callback_data=f"u:openbets:p:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🏠 Головне меню", callback_data="u:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def mybets_filter_keyboard(
    active_status: str,
    page: int = 0,
    has_prev: bool = False,
    has_next: bool = False,
) -> InlineKeyboardMarkup:
    labels = [
        ("open", "Відкриті"),
        ("won", "Виграні"),
        ("lost", "Програні"),
        ("void", "Повернення"),
        ("all", "Усі"),
    ]
    rows: list[list[InlineKeyboardButton]] = []
    for index in range(0, len(labels), 2):
        row = []
        for status, label in labels[index : index + 2]:
            prefix = "• " if status == active_status else ""
            row.append(InlineKeyboardButton(text=f"{prefix}{label}", callback_data=f"u:bets:{status}"))
        rows.append(row)
    nav = []
    if has_prev:
        nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"u:bets:{active_status}:p:{page - 1}"))
    if has_next:
        nav.append(InlineKeyboardButton(text="Далі ➡️", callback_data=f"u:bets:{active_status}:p:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🏠 Головне меню", callback_data="u:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def selected_odds_keyboard(odds_id: int, match_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎟 Одиночна ставка", callback_data=f"o:single:{odds_id}")],
            [InlineKeyboardButton(text="➕ Додати в експрес", callback_data=f"x:add:{odds_id}")],
            [InlineKeyboardButton(text="🧾 Мій купон", callback_data="u:slip")],
            [InlineKeyboardButton(text="⬅️ До коефіцієнтів", callback_data=f"m:o:{match_id}:0")],
        ]
    )


def express_coupon_keyboard(can_place: bool, has_items: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if can_place:
        rows.append(
            [
                InlineKeyboardButton(text="✅ Поставити експрес", callback_data="x:stake"),
                InlineKeyboardButton(text="🗑 Очистити купон", callback_data="x:clear"),
            ]
        )
    elif has_items:
        rows.append([InlineKeyboardButton(text="🗑 Очистити купон", callback_data="x:clear")])
    rows.append([InlineKeyboardButton(text="⬅️ До матчів", callback_data="m:p:0")])
    rows.append([InlineKeyboardButton(text="🏠 Головне меню", callback_data="u:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def express_stake_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text=format_cents(cents), callback_data=f"x:c:{cents}")
            for cents in STAKE_OPTIONS_CENTS[:2]
        ],
        [
            InlineKeyboardButton(text=format_cents(cents), callback_data=f"x:c:{cents}")
            for cents in STAKE_OPTIONS_CENTS[2:]
        ],
        [InlineKeyboardButton(text="✍️ Інша сума", callback_data="x:custom")],
        [InlineKeyboardButton(text="🧾 Мій купон", callback_data="u:slip")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_express_keyboard(stake_cents: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Підтвердити експрес", callback_data=f"x:final:{stake_cents}"),
                InlineKeyboardButton(text="❌ Скасувати", callback_data="u:slip"),
            ],
            [InlineKeyboardButton(text="⬅️ Змінити суму", callback_data="x:stake")],
        ]
    )


