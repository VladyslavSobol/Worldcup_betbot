from decimal import Decimal

import pytest

from app.models import BetStatus, MarketType
from app.services.settlement import settle_selection


def test_h2h_home_win():
    result = settle_selection(MarketType.h2h, "Brazil", "Brazil", "Japan", 2, 1)
    assert result.status == BetStatus.won


def test_h2h_draw_loss_for_home():
    result = settle_selection(MarketType.h2h, "Brazil", "Brazil", "Japan", 1, 1)
    assert result.status == BetStatus.lost


def test_totals_over_half_line_win():
    result = settle_selection(
        MarketType.totals,
        "Over",
        "Brazil",
        "Japan",
        2,
        1,
        line=Decimal("2.5"),
    )
    assert result.status == BetStatus.won


def test_totals_under_half_line_loss():
    result = settle_selection(
        MarketType.totals,
        "Under",
        "Brazil",
        "Japan",
        2,
        1,
        line=Decimal("2.5"),
    )
    assert result.status == BetStatus.lost


def test_totals_integer_line_push():
    result = settle_selection(
        MarketType.totals,
        "Over",
        "Brazil",
        "Japan",
        1,
        1,
        line=Decimal("2.0"),
    )
    assert result.status == BetStatus.push


def test_spread_win():
    result = settle_selection(
        MarketType.spreads,
        "Brazil",
        "Brazil",
        "Japan",
        1,
        1,
        line=Decimal("-0.5"),
        selection_scope="Brazil",
    )
    assert result.status == BetStatus.lost


def test_spread_push():
    result = settle_selection(
        MarketType.spreads,
        "Brazil",
        "Brazil",
        "Japan",
        2,
        1,
        line=Decimal("-1.0"),
        selection_scope="Brazil",
    )
    assert result.status == BetStatus.push


def test_outright_requires_winner():
    with pytest.raises(ValueError):
        settle_selection(MarketType.outrights, "Brazil", "Brazil", "Japan", 0, 0)


def test_outright_win():
    result = settle_selection(
        MarketType.outrights,
        "Brazil",
        "Brazil",
        "Japan",
        0,
        0,
        outright_winner="Brazil",
    )
    assert result.status == BetStatus.won


def test_btts_yes_wins_when_both_teams_score():
    result = settle_selection(MarketType.btts, "Yes", "Brazil", "Japan", 2, 1)
    assert result.status == BetStatus.won


def test_btts_no_wins_when_one_team_does_not_score():
    result = settle_selection(MarketType.btts, "No", "Brazil", "Japan", 3, 0)
    assert result.status == BetStatus.won


@pytest.mark.parametrize(
    ("selection", "home_score", "away_score", "expected"),
    [
        ("1X", 2, 0, BetStatus.won),
        ("1X", 1, 1, BetStatus.won),
        ("1X", 0, 1, BetStatus.lost),
        ("X2", 0, 2, BetStatus.won),
        ("X2", 1, 1, BetStatus.won),
        ("X2", 2, 1, BetStatus.lost),
    ],
)
def test_double_chance_settlement(selection, home_score, away_score, expected):
    result = settle_selection(
        MarketType.double_chance,
        selection,
        "Brazil",
        "Japan",
        home_score,
        away_score,
    )
    assert result.status == expected


def test_to_qualify_uses_actual_advancing_team():
    result = settle_selection(
        MarketType.to_qualify,
        "Japan",
        "Brazil",
        "Japan",
        1,
        1,
        outright_winner="Japan",
    )

    assert result.status == BetStatus.won
