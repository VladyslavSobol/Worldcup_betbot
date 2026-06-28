from __future__ import annotations

import enum
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class MatchStatus(str, enum.Enum):
    scheduled = "scheduled"
    live = "live"
    finished = "finished"
    postponed = "postponed"
    canceled = "canceled"


class MarketType(str, enum.Enum):
    h2h = "h2h"
    double_chance = "double_chance"
    totals = "totals"
    spreads = "spreads"
    btts = "btts"
    outrights = "outrights"
    correct_score = "correct_score"
    top_goalscorer = "top_goalscorer"
    to_qualify = "to_qualify"


class MarketStatus(str, enum.Enum):
    open = "open"
    closed = "closed"
    settled = "settled"
    void = "void"


class BetStatus(str, enum.Enum):
    open = "open"
    won = "won"
    lost = "lost"
    push = "push"
    void = "void"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    balance_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    playoff_bonus_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    bets: Mapped[list[Bet]] = relationship(back_populates="user")
    bet_slips: Mapped[list[BetSlip]] = relationship(back_populates="user")
    express_bets: Mapped[list[ExpressBet]] = relationship(back_populates="user")


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    api_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    sport_key: Mapped[str] = mapped_column(String(255), default="")
    home_team: Mapped[str] = mapped_column(String(255))
    away_team: Mapped[str] = mapped_column(String(255))
    kickoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[MatchStatus] = mapped_column(Enum(MatchStatus), default=MatchStatus.scheduled)
    home_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    markets: Mapped[list[Market]] = relationship(back_populates="match")


class Market(Base):
    __tablename__ = "markets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    type: Mapped[MarketType] = mapped_column(Enum(MarketType))
    line: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    selection_scope: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[MarketStatus] = mapped_column(Enum(MarketStatus), default=MarketStatus.open)
    source: Mapped[str] = mapped_column(String(255), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    match: Mapped[Match] = relationship(back_populates="markets")
    odds: Mapped[list[OddsSnapshot]] = relationship(back_populates="market")
    bets: Mapped[list[Bet]] = relationship(back_populates="market")

    __table_args__ = (
        UniqueConstraint("match_id", "type", "line", "selection_scope", name="uq_market_shape"),
    )


class OddsSnapshot(Base):
    __tablename__ = "odds_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), index=True)
    selection: Mapped[str] = mapped_column(String(255))
    decimal_odds: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    source: Mapped[str] = mapped_column(String(255))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    market: Mapped[Market] = relationship(back_populates="odds")
    bets: Mapped[list[Bet]] = relationship(back_populates="odds_snapshot")


class Bet(Base):
    __tablename__ = "bets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), index=True)
    odds_snapshot_id: Mapped[int] = mapped_column(ForeignKey("odds_snapshots.id"))
    selection: Mapped[str] = mapped_column(String(255))
    stake_cents: Mapped[int] = mapped_column(Integer)
    locked_decimal_odds: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    status: Mapped[BetStatus] = mapped_column(Enum(BetStatus), default=BetStatus.open)
    payout_cents: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="bets")
    market: Mapped[Market] = relationship(back_populates="bets")
    odds_snapshot: Mapped[OddsSnapshot] = relationship(back_populates="bets")

class BetSlip(Base):
    __tablename__ = "bet_slips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="bet_slips")
    items: Mapped[list[BetSlipItem]] = relationship(
        back_populates="bet_slip",
        cascade="all, delete-orphan",
    )


class BetSlipItem(Base):
    __tablename__ = "bet_slip_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bet_slip_id: Mapped[int] = mapped_column(ForeignKey("bet_slips.id"), index=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), index=True)
    odds_snapshot_id: Mapped[int] = mapped_column(ForeignKey("odds_snapshots.id"))
    selection: Mapped[str] = mapped_column(String(255))
    locked_decimal_odds: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    bet_slip: Mapped[BetSlip] = relationship(back_populates="items")
    match: Mapped[Match] = relationship()
    market: Mapped[Market] = relationship()
    odds_snapshot: Mapped[OddsSnapshot] = relationship()

    __table_args__ = (
        UniqueConstraint("bet_slip_id", "match_id", name="uq_bet_slip_one_item_per_match"),
    )


class ExpressBet(Base):
    __tablename__ = "express_bets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    stake_cents: Mapped[int] = mapped_column(Integer)
    total_odds: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    potential_payout_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[BetStatus] = mapped_column(Enum(BetStatus), default=BetStatus.open)
    payout_cents: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="express_bets")
    items: Mapped[list[ExpressBetItem]] = relationship(
        back_populates="express_bet",
        cascade="all, delete-orphan",
    )


class ExpressBetItem(Base):
    __tablename__ = "express_bet_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    express_bet_id: Mapped[int] = mapped_column(ForeignKey("express_bets.id"), index=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), index=True)
    odds_snapshot_id: Mapped[int] = mapped_column(ForeignKey("odds_snapshots.id"))
    selection: Mapped[str] = mapped_column(String(255))
    locked_decimal_odds: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    status: Mapped[BetStatus] = mapped_column(Enum(BetStatus), default=BetStatus.open)
    result_info: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    express_bet: Mapped[ExpressBet] = relationship(back_populates="items")
    match: Mapped[Match] = relationship()
    market: Mapped[Market] = relationship()
    odds_snapshot: Mapped[OddsSnapshot] = relationship()

class GroupChat(Base):
    __tablename__ = "group_chats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_primary: Mapped[bool] = mapped_column(default=True)
    announce_bets: Mapped[bool] = mapped_column(default=True)
    announce_settlements: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SettlementLog(Base):
    __tablename__ = "settlement_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    admin_telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    action: Mapped[str] = mapped_column(String(50))
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

