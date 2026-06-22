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
