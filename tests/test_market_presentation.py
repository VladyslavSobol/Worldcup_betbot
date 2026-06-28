from datetime import datetime, timezone
from decimal import Decimal

from app.bot.formatting import market_block_title, odds_button_label
from app.bot.handlers import _explain_text, _odds_blocks
from app.bot.keyboards import ODDS_BLOCKS_PER_PAGE
from app.models import Market, MarketType, Match, OddsSnapshot


def _option(
    match: Match,
    market_type: MarketType,
    selection: str,
    odds: str,
    line: str | None = None,
) -> OddsSnapshot:
    decimal_line = Decimal(line) if line is not None else None
    market = Market(
        type=market_type,
        line=decimal_line,
        selection_scope=selection if market_type == MarketType.spreads else None,
        match=match,
    )
    return OddsSnapshot(
        id=hash((market_type.value, selection, line)) % 100000,
        market=market,
        selection=selection,
        decimal_odds=Decimal(odds),
    )


def test_odds_blocks_show_three_totals_and_three_spreads():
    match = Match(
        id=1,
        api_id="odds_api_io:1",
        home_team="South Africa",
        away_team="Korea Republic",
        kickoff_at=datetime.now(timezone.utc),
    )
    rows = [
        _option(match, MarketType.h2h, "South Africa", "6.25"),
        _option(match, MarketType.h2h, "Draw", "3.80"),
        _option(match, MarketType.h2h, "Korea Republic", "1.60"),
        _option(match, MarketType.double_chance, "1X", "2.20"),
        _option(match, MarketType.double_chance, "X2", "1.12"),
        _option(match, MarketType.to_qualify, "South Africa", "2.10"),
        _option(match, MarketType.to_qualify, "Korea Republic", "1.70"),
        _option(match, MarketType.btts, "Yes", "1.92"),
        _option(match, MarketType.btts, "No", "1.78"),
    ]
    for line in ("2.0", "2.5", "3.0"):
        rows.extend(
            [
                _option(match, MarketType.totals, "Over", "1.90", line),
                _option(match, MarketType.totals, "Under", "1.90", line),
            ]
        )
    for line in ("-1.0", "-1.5", "-2.0"):
        rows.extend(
            [
                _option(match, MarketType.spreads, "South Africa", "1.90", line),
                _option(
                    match,
                    MarketType.spreads,
                    "Korea Republic",
                    "1.90",
                    str(-Decimal(line)),
                ),
            ]
        )

    blocks = _odds_blocks(rows)

    assert [block[0].market.type for block in blocks] == [
        MarketType.h2h,
        MarketType.double_chance,
        MarketType.to_qualify,
        MarketType.totals,
        MarketType.totals,
        MarketType.totals,
        MarketType.spreads,
        MarketType.spreads,
        MarketType.spreads,
        MarketType.btts,
    ]
    assert ODDS_BLOCKS_PER_PAGE >= len(blocks)


def test_double_chance_and_spread_labels_are_clear():
    match = Match(
        id=1,
        api_id="odds_api_io:1",
        home_team="South Africa",
        away_team="Korea Republic",
        kickoff_at=datetime.now(timezone.utc),
    )
    home_or_draw = _option(match, MarketType.double_chance, "1X", "2.20")
    away_or_draw = _option(match, MarketType.double_chance, "X2", "1.12")
    spread = [
        _option(match, MarketType.spreads, "South Africa", "1.92", "1.5"),
        _option(match, MarketType.spreads, "Korea Republic", "1.88", "-1.5"),
    ]

    assert "П1 або нічия" in odds_button_label(home_or_draw)
    assert "П2 або нічия" in odds_button_label(away_or_draw)
    assert market_block_title(spread) == "📏 Фора +1.5 / -1.5 (90 хв)"


def test_betting_explanation_includes_new_markets():
    text = _explain_text()

    assert "Подвійний шанс" in text
    assert "Обидві заб’ють" in text
    assert "Основний час" in text
    assert "Прохід далі" in text


def test_spread_block_keeps_only_latest_complete_team_pair():
    match = Match(
        id=1,
        api_id="odds_api_io:1",
        home_team="South Africa",
        away_team="Korea Republic",
        kickoff_at=datetime.now(timezone.utc),
    )
    old_home = _option(match, MarketType.spreads, "South Africa", "5.10", "1.5")
    old_away = _option(match, MarketType.spreads, "Korea Republic", "1.16", "-1.5")
    new_home = _option(match, MarketType.spreads, "South Africa", "1.92", "-1.5")
    new_away = _option(match, MarketType.spreads, "Korea Republic", "1.88", "1.5")
    old_home.id, old_away.id, new_home.id, new_away.id = 10, 11, 20, 21

    blocks = _odds_blocks([new_away, new_home, old_away, old_home])

    assert len(blocks) == 1
    assert [(row.selection, row.market.line) for row in blocks[0]] == [
        ("South Africa", Decimal("-1.5")),
        ("Korea Republic", Decimal("1.5")),
    ]


def test_market_titles_explain_settlement_scope_for_playoff_markets():
    match = Match(
        id=1,
        api_id="odds_api_io:1",
        home_team="South Africa",
        away_team="Korea Republic",
        kickoff_at=datetime.now(timezone.utc),
    )

    assert market_block_title([_option(match, MarketType.h2h, "South Africa", "6.25")]) == (
        "🏆 Результат матчу (90 хв)"
    )
    assert market_block_title([_option(match, MarketType.double_chance, "1X", "2.20")]) == (
        "🛡 Подвійний шанс (90 хв)"
    )
    assert market_block_title([_option(match, MarketType.totals, "Over", "1.90", "2.5")]) == (
        "⚽ Тотал 2.5 (90 хв)"
    )
    assert market_block_title([_option(match, MarketType.btts, "Yes", "1.92")]) == (
        "🥅 Обидві заб’ють (90 хв)"
    )
    assert market_block_title([_option(match, MarketType.to_qualify, "South Africa", "2.10")]) == (
        "🏁 Прохід далі (з овертаймом/пенальті)"
    )


def test_betting_explanation_separates_regular_time_and_qualification():
    text = _explain_text()

    assert "Основний час" in text
    assert "Прохід далі" in text
    assert "овертайм" in text
    assert "пенальті" in text
