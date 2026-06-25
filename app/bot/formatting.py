from app.models import Bet, BetStatus, MarketType, Match, MatchStatus, OddsSnapshot, User
from app.money import format_cents
from app.team_names import canonical_team_name


MATCH_STATUS_UA = {
    MatchStatus.scheduled: "заплановано",
    MatchStatus.live: "триває",
    MatchStatus.finished: "завершено",
    MatchStatus.postponed: "перенесено",
    MatchStatus.canceled: "скасовано",
}

BET_STATUS_UA = {
    BetStatus.open: "відкрита",
    BetStatus.won: "виграла",
    BetStatus.lost: "програла",
    BetStatus.push: "повернення",
    BetStatus.void: "скасована",
}

MARKET_TYPE_UA = {
    MarketType.h2h: "1X2",
    MarketType.double_chance: "Подвійний шанс",
    MarketType.totals: "Тотал",
    MarketType.spreads: "Фора",
    MarketType.btts: "Обидві заб’ють",
    MarketType.outrights: "Довгостроковий",
    MarketType.correct_score: "Точний рахунок",
    MarketType.top_goalscorer: "Бомбардир",
    MarketType.to_qualify: "Прохід далі",
}

COUNTRY_FLAGS = {
    "algeria": "🇩🇿",
    "argentina": "🇦🇷",
    "australia": "🇦🇺",
    "austria": "🇦🇹",
    "belgium": "🇧🇪",
    "bosnia & herzegovina": "🇧🇦",
    "brazil": "🇧🇷",
    "canada": "🇨🇦",
    "cape verde": "🇨🇻",
    "chile": "🇨🇱",
    "china": "🇨🇳",
    "colombia": "🇨🇴",
    "croatia": "🇭🇷",
    "curaçao": "🇨🇼",
    "curacao": "🇨🇼",
    "czech republic": "🇨🇿",
    "denmark": "🇩🇰",
    "dr congo": "🇨🇩",
    "ecuador": "🇪🇨",
    "egypt": "🇪🇬",
    "england": "\U0001F3F4\U000E0067\U000E0062\U000E0065\U000E006E\U000E0067\U000E007F",
    "france": "🇫🇷",
    "germany": "🇩🇪",
    "ghana": "🇬🇭",
    "greece": "🇬🇷",
    "haiti": "🇭🇹",
    "iran": "🇮🇷",
    "iraq": "🇮🇶",
    "italy": "🇮🇹",
    "ivory coast": "🇨🇮",
    "japan": "🇯🇵",
    "jordan": "🇯🇴",
    "mexico": "🇲🇽",
    "morocco": "🇲🇦",
    "netherlands": "🇳🇱",
    "new zealand": "🇳🇿",
    "norway": "🇳🇴",
    "panama": "🇵🇦",
    "paraguay": "🇵🇾",
    "peru": "🇵🇪",
    "poland": "🇵🇱",
    "portugal": "🇵🇹",
    "qatar": "🇶🇦",
    "saudi arabia": "🇸🇦",
    "scotland": "\U0001F3F4\U000E0067\U000E0062\U000E0073\U000E0063\U000E0074\U000E007F",
    "senegal": "🇸🇳",
    "serbia": "🇷🇸",
    "south africa": "🇿🇦",
    "south korea": "🇰🇷",
    "korea republic": "🇰🇷",
    "spain": "🇪🇸",
    "sweden": "🇸🇪",
    "switzerland": "🇨🇭",
    "turkey": "🇹🇷",
    "ukraine": "🇺🇦",
    "united states": "🇺🇸",
    "usa": "🇺🇸",
    "uruguay": "🇺🇾",
    "uzbekistan": "🇺🇿",
    "wales": "\U0001F3F4\U000E0067\U000E0062\U000E0077\U000E006C\U000E0073\U000E007F",
}

TEAM_CODES = {
    "algeria": "ALG",
    "argentina": "ARG",
    "australia": "AUS",
    "austria": "AUT",
    "belgium": "BEL",
    "bosnia & herzegovina": "BIH",
    "brazil": "BRA",
    "canada": "CAN",
    "cape verde": "CPV",
    "colombia": "COL",
    "croatia": "CRO",
    "curaçao": "CUW",
    "curacao": "CUW",
    "czech republic": "CZE",
    "dr congo": "COD",
    "ecuador": "ECU",
    "egypt": "EGY",
    "england": "ENG",
    "france": "FRA",
    "germany": "GER",
    "ghana": "GHA",
    "haiti": "HAI",
    "iran": "IRN",
    "iraq": "IRQ",
    "ivory coast": "CIV",
    "japan": "JPN",
    "jordan": "JOR",
    "mexico": "MEX",
    "morocco": "MAR",
    "netherlands": "NED",
    "new zealand": "NZL",
    "norway": "NOR",
    "panama": "PAN",
    "paraguay": "PAR",
    "portugal": "POR",
    "qatar": "QAT",
    "saudi arabia": "KSA",
    "scotland": "SCO",
    "senegal": "SEN",
    "south africa": "RSA",
    "south korea": "KOR",
    "spain": "ESP",
    "sweden": "SWE",
    "switzerland": "SUI",
    "tunisia": "TUN",
    "turkey": "TUR",
    "usa": "USA",
    "uruguay": "URU",
    "uzbekistan": "UZB",
}


def user_label(user: User) -> str:
    return user.username or user.first_name or str(user.telegram_id)


def _team_key(name: str | None) -> str:
    return canonical_team_name(name or "")


def country_flag(name: str | None) -> str:
    return COUNTRY_FLAGS.get(_team_key(name), "")


def format_decimal(value) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def team_code(name: str | None) -> str:
    key = _team_key(name)
    if key in TEAM_CODES:
        return TEAM_CODES[key]
    words = [part for part in key.replace("-", " ").split() if part]
    if not words:
        return ""
    if len(words) == 1:
        return words[0][:3].upper()
    return "".join(word[0] for word in words[:3]).upper()


def selection_icon(selection: str, match: Match | None = None) -> str:
    normalized = selection.lower().strip()
    if normalized in {"1x", "x2"}:
        return "🛡"
    if normalized == "draw":
        return "🤝"
    if normalized.startswith("over"):
        return "⬆️"
    if normalized.startswith("under"):
        return "⬇️"
    if normalized == "yes":
        return "✅"
    if normalized == "no":
        return "❌"
    if normalized == "none":
        return "🚫"
    if match and selection == match.home_team:
        return country_flag(match.home_team)
    if match and selection == match.away_team:
        return country_flag(match.away_team)
    return country_flag(selection)


def selection_label(selection: str) -> str:
    normalized = selection.lower().strip()
    if normalized == "1x":
        return "П1 або нічия"
    if normalized == "x2":
        return "П2 або нічия"
    if normalized == "draw":
        return "Нічия"
    if normalized.startswith("over"):
        return "Більше"
    if normalized.startswith("under"):
        return "Менше"
    if normalized == "yes":
        return "Так"
    if normalized == "no":
        return "Ні"
    if normalized == "none":
        return "Немає"
    return selection


def compact_selection_label(selection: str, match: Match | None = None) -> str:
    normalized = selection.lower().strip()
    if normalized == "1x":
        return "П1 або нічия"
    if normalized == "x2":
        return "П2 або нічия"
    if normalized == "draw":
        return "X"
    if normalized.startswith("over"):
        return "Більше"
    if normalized.startswith("under"):
        return "Менше"
    if normalized == "yes":
        return "Так"
    if normalized == "no":
        return "Ні"
    if match and selection in {match.home_team, match.away_team}:
        return team_code(selection)
    return team_code(selection) or selection[:10]


def match_title(match: Match) -> str:
    return (
        f"{country_flag(match.home_team)} {match.home_team} "
        f"проти {country_flag(match.away_team)} {match.away_team}"
    )


def match_button_title(match: Match) -> str:
    return (
        f"{country_flag(match.home_team)} {team_code(match.home_team)} "
        f"- {country_flag(match.away_team)} {team_code(match.away_team)}"
    )


def match_line(match: Match) -> str:
    kickoff = match.kickoff_at.strftime("%Y-%m-%d %H:%M UTC")
    status = MATCH_STATUS_UA.get(match.status, match.status.value)
    return f"#{match.id} {match_title(match)}\n{kickoff} · {status}"


def market_title(odds: OddsSnapshot) -> str:
    market = odds.market
    market_name = MARKET_TYPE_UA.get(market.type, market.type.value)
    if market.type in {MarketType.totals, MarketType.spreads} and market.line is not None:
        return f"{market_name} {format_decimal(market.line)}"
    return market_name


def market_block_title(block: list[OddsSnapshot]) -> str:
    if not block:
        return ""
    market_type = block[0].market.type
    if market_type == MarketType.h2h:
        return "🏆 Результат матчу"
    if market_type == MarketType.double_chance:
        return "🛡 Подвійний шанс"
    if market_type == MarketType.to_qualify:
        return "🏁 Прохід далі"
    if market_type == MarketType.totals:
        return f"⚽ {market_title(block[0])}"
    if market_type == MarketType.spreads:
        line = abs(block[0].market.line or 0)
        return f"📏 Фора +{format_decimal(line)} / -{format_decimal(line)}"
    if market_type == MarketType.btts:
        return "🥅 Обидві заб’ють"
    return market_title(block[0])


def odds_line(odds: OddsSnapshot) -> str:
    match = odds.market.match
    icon = selection_icon(odds.selection, match)
    label = selection_label(odds.selection)
    return f"{icon} {label} · {format_decimal(odds.decimal_odds)}"


def odds_button_label(odds: OddsSnapshot) -> str:
    match = odds.market.match
    icon = selection_icon(odds.selection, match)
    label = compact_selection_label(odds.selection, match)
    if odds.market.type == MarketType.spreads and odds.market.line is not None:
        label = f"{label} {format_decimal(odds.market.line)}"
    return f"{icon} {label} {format_decimal(odds.decimal_odds)}"


def bet_line(bet: Bet) -> str:
    status = BET_STATUS_UA.get(bet.status, bet.status.value)
    return (
        f"#{bet.id} {bet.selection} @ {bet.locked_decimal_odds} | "
        f"ставка {format_cents(bet.stake_cents)} | {status} | "
        f"виплата {format_cents(bet.payout_cents)}"
    )

STATUS_ICON = {
    BetStatus.open: "🎟",
    BetStatus.won: "✅",
    BetStatus.lost: "❌",
    BetStatus.push: "↩️",
    BetStatus.void: "↩️",
}

STATUS_TITLE_UA = {
    BetStatus.open: "Відкрита",
    BetStatus.won: "Виграна",
    BetStatus.lost: "Програна",
    BetStatus.push: "Повернення",
    BetStatus.void: "Повернення",
}

EXPRESS_STATUS_TITLE_UA = {
    BetStatus.open: "Відкритий",
    BetStatus.won: "Виграний",
    BetStatus.lost: "Програний",
    BetStatus.push: "Повернення",
    BetStatus.void: "Повернення",
}

CARD_SEPARATOR = "━━━━━━━━━━━━━━"


def format_money(cents: int) -> str:
    return format_cents(cents)


def format_profit(cents: int) -> str:
    if cents > 0:
        return f"+{format_money(cents)}"
    return format_money(cents)


def format_odds(value) -> str:
    return f"{float(value):.2f}"


def format_match_pair(match: Match) -> str:
    return f"{country_flag(match.home_team)} {match.home_team} — {country_flag(match.away_team)} {match.away_team}"


def format_market_selection(market, selection: str) -> str:
    return f"{_market_label(market)}: {selection_label(selection)}"


def format_single_bet_card(bet: Bet, show_user: bool = False) -> str:
    match = bet.market.match if bet.market else None
    icon = STATUS_ICON.get(bet.status, "🎟")
    status = STATUS_TITLE_UA.get(bet.status, bet.status.value)
    stake = format_money(bet.stake_cents)
    odds = format_odds(bet.locked_decimal_odds)
    result_cents = bet.payout_cents if bet.status != BetStatus.open else int(
        bet.stake_cents * bet.locked_decimal_odds
    )

    lines = [f"{icon} #{bet.id} · {status}"]
    if show_user and getattr(bet, "user", None):
        lines.append(f"👤 {user_label(bet.user)}")
    if match:
        lines.append(format_match_pair(match))
    else:
        lines.append(f"Матч #{bet.match_id}")
    lines.append(f"📌 {format_market_selection(bet.market, bet.selection)}")
    lines.append(f"📈 Кеф: {odds}")
    lines.append(f"💵 Сума: {stake}")
    if bet.status == BetStatus.open:
        lines.append(f"🏆 Можливий виграш: {format_money(result_cents)}")
    elif bet.status == BetStatus.won:
        lines.append(f"🏆 Виграш: {format_money(result_cents)}")
    elif bet.status == BetStatus.lost:
        lines.append(f"💸 Програш: {stake}")
    else:
        lines.append(f"↩️ Повернено: {format_money(result_cents or bet.stake_cents)}")
    return "\n".join(lines)


def format_express_bet_card(express_bet, show_user: bool = False) -> str:
    status = getattr(express_bet, "status", BetStatus.open)
    icon = STATUS_ICON.get(status, "🧾")
    status_text = EXPRESS_STATUS_TITLE_UA.get(status, getattr(status, "value", str(status)))
    stake_cents = getattr(express_bet, "stake_cents", 0)
    payout_cents = getattr(express_bet, "payout_cents", 0)
    potential = getattr(express_bet, "potential_payout_cents", payout_cents)
    total_odds = getattr(express_bet, "total_odds", 1)
    items = list(getattr(express_bet, "items", []) or [])

    lines = [f"🧾 Експрес #{express_bet.id} · {status_text}"]
    if show_user and getattr(express_bet, "user", None):
        lines.append(f"👤 {user_label(express_bet.user)}")
    lines.extend(
        [
            f"📈 Загальний кеф: {format_odds(total_odds)}",
            f"💵 Сума: {format_money(stake_cents)}",
        ]
    )
    if status == BetStatus.open:
        lines.append(f"🏆 Можливий виграш: {format_money(potential)}")
    elif status == BetStatus.won:
        lines.append(f"🏆 Виграш: {format_money(payout_cents)}")
    elif status == BetStatus.lost:
        lines.append(f"💸 Програш: {format_money(stake_cents)}")
    else:
        lines.append(f"↩️ Повернено: {format_money(payout_cents or stake_cents)}")

    for index, item in enumerate(items, start=1):
        match = getattr(item, "match", None)
        if match is None and getattr(item, "market", None):
            match = item.market.match
        market = getattr(item, "market", None)
        selection = getattr(item, "selection", "")
        locked_odds = getattr(item, "locked_decimal_odds", 1)
        lines.append("")
        lines.append(f"{index}. {format_match_pair(match) if match else f'Матч #{item.match_id}'}")
        lines.append(f"   📌 {format_market_selection(market, selection)}")
        lines.append(f"   📈 Кеф: {format_odds(locked_odds)}")
    return "\n".join(lines)


def format_bets_list(title: str, cards: list[str], empty_text: str) -> str:
    if not cards:
        return f"{title}\n\n{empty_text}"
    return f"{title}\n\n" + f"\n\n{CARD_SEPARATOR}\n\n".join(cards)


def format_leaderboard(
    rows,
    starting_balance_cents: int,
    limit: int = 5,
) -> str:
    page_rows = list(rows)[:limit]
    if not page_rows:
        return "🏆 Лідерборд\n\nПоки що немає гравців для лідерборду."

    blocks = [
        format_leaderboard_entry(index, user, open_stakes, bankroll, starting_balance_cents)
        for index, (user, open_stakes, bankroll) in enumerate(page_rows, start=1)
    ]
    return "🏆 Лідерборд\n\nБанкрол = баланс + відкриті ставки\n\n" + "\n\n".join(blocks)


def format_leaderboard_entry(
    rank: int,
    user: User,
    open_stakes_cents: int,
    bankroll_cents: int,
    starting_balance_cents: int,
) -> str:
    place = _rank_label(rank)
    indent = "" if rank <= 3 else "   "
    profit = bankroll_cents - starting_balance_cents
    return "\n".join(
        [
            f"{place} {user_label(user)}",
            f"{indent}💰 Банкрол: {format_money(bankroll_cents)}",
            f"{indent}💵 Баланс: {format_money(user.balance_cents)}",
            f"{indent}🎟 Відкрито: {format_money(open_stakes_cents)}",
            f"{indent}📊 Профіт: {format_profit(profit)}",
        ]
    )


def format_top_wins(entries, limit: int = 5) -> str:
    page_entries = list(entries)[:limit]
    if not page_entries:
        return "💎 Топ виграшів\n\nПоки що виграних ставок немає."

    blocks = [
        format_top_win_entry(index, entry)
        for index, entry in enumerate(page_entries, start=1)
    ]
    return "💎 Топ виграшів\n\n" + "\n\n━━━━━━━━━━━━\n\n".join(blocks)


def format_top_win_entry(rank: int, entry) -> str:
    if hasattr(entry, "items") and not hasattr(entry, "match_id"):
        return _format_top_express_win_entry(rank, entry)
    return _format_top_single_win_entry(rank, entry)


def _format_top_single_win_entry(rank: int, bet: Bet) -> str:
    match = bet.market.match if bet.market else None
    profit = bet.payout_cents - bet.stake_cents
    lines = [
        f"{_rank_label(rank)} {user_label(bet.user)}",
        f"💸 Чистий виграш: {format_profit(profit)}",
    ]
    if match:
        lines.append(format_match_pair(match))
    else:
        lines.append(f"Матч #{bet.match_id}")
    lines.extend(
        [
            f"📌 {format_market_selection(bet.market, bet.selection)}",
            f"📈 Кеф: {format_odds(bet.locked_decimal_odds)}",
            f"💵 {format_money(bet.stake_cents)} → {format_money(bet.payout_cents)}",
        ]
    )
    return "\n".join(lines)


def _format_top_express_win_entry(rank: int, express_bet) -> str:
    profit = express_bet.payout_cents - express_bet.stake_cents
    items = list(getattr(express_bet, "items", []) or [])
    lines = []
    if getattr(express_bet, "user", None):
        lines.append(f"{_rank_label(rank)} {user_label(express_bet.user)}")
    lines.extend(
        [
            f"🧾 Експрес #{express_bet.id}",
            f"💸 Чистий виграш: {format_profit(profit)}",
            f"📈 Загальний кеф: {format_odds(express_bet.total_odds)}",
            f"💵 {format_money(express_bet.stake_cents)} → {format_money(express_bet.payout_cents)}",
            f"Подій: {len(items)}",
        ]
    )
    return "\n".join(lines)


def _rank_label(rank: int) -> str:
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"{rank}.")


def _market_label(market) -> str:
    if not market:
        return "Ринок"
    label = MARKET_TYPE_UA.get(market.type, market.type.value)
    if market.line is not None and market.type in {MarketType.totals, MarketType.spreads}:
        return f"{label} {format_decimal(market.line)}"
    return label

def flags_test_text() -> str:
    teams = sorted(COUNTRY_FLAGS)
    lines = ["Тест прапорів:"]
    for name in teams:
        lines.append(f"{COUNTRY_FLAGS[name]} {team_code(name)} — {name.title()}")
    return "\n".join(lines)
