from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.models import BetStatus, MarketType


@dataclass(frozen=True)
class SettlementResult:
    status: BetStatus
    won: bool = False


def settle_selection(
    market_type: MarketType,
    selection: str,
    home_team: str,
    away_team: str,
    home_score: int,
    away_score: int,
    line: Decimal | None = None,
    selection_scope: str | None = None,
    outright_winner: str | None = None,
) -> SettlementResult:
    if market_type == MarketType.h2h:
        winner = _h2h_winner(home_team, away_team, home_score, away_score)
        return _status(selection == winner)

    if market_type == MarketType.double_chance:
        normalized = selection.upper()
        if normalized == "1X":
            return _status(home_score >= away_score)
        if normalized == "X2":
            return _status(away_score >= home_score)
        raise ValueError(f"Unsupported double chance selection: {selection}")

    if market_type == MarketType.totals:
        if line is None:
            raise ValueError("Totals settlement requires a line")
        total = Decimal(home_score + away_score)
        normalized = selection.lower()
        if total == line:
            return SettlementResult(BetStatus.push)
        if normalized.startswith("over"):
            return _status(total > line)
        if normalized.startswith("under"):
            return _status(total < line)
        raise ValueError(f"Unsupported totals selection: {selection}")

    if market_type == MarketType.spreads:
        if line is None:
            raise ValueError("Spread settlement requires a line")
        team = selection_scope or selection
        if team == home_team:
            adjusted = Decimal(home_score) + line
            opponent = Decimal(away_score)
        elif team == away_team:
            adjusted = Decimal(away_score) + line
            opponent = Decimal(home_score)
        else:
            raise ValueError(f"Spread selection is not a match team: {team}")
        if adjusted == opponent:
            return SettlementResult(BetStatus.push)
        return _status(adjusted > opponent)

    if market_type == MarketType.btts:
        both_scored = home_score > 0 and away_score > 0
        normalized = selection.casefold()
        if normalized in {"yes", "так"}:
            return _status(both_scored)
        if normalized in {"no", "ні"}:
            return _status(not both_scored)
        raise ValueError(f"Unsupported BTTS selection: {selection}")

    if market_type == MarketType.outrights:
        if outright_winner is None:
            raise ValueError("Outright settlement requires an outright winner")
        return _status(selection == outright_winner)

    raise ValueError(f"Manual settlement required for market type {market_type.value}")


def _status(won: bool) -> SettlementResult:
    return SettlementResult(BetStatus.won if won else BetStatus.lost, won=won)


def _h2h_winner(home_team: str, away_team: str, home_score: int, away_score: int) -> str:
    if home_score > away_score:
        return home_team
    if away_score > home_score:
        return away_team
    return "Draw"
