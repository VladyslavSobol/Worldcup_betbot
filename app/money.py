from decimal import Decimal, ROUND_HALF_UP


def parse_cents(value: str) -> int:
    amount = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(amount * 100)


def format_cents(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100}.{cents % 100:02d}"


def payout_cents(stake_cents: int, decimal_odds: Decimal) -> int:
    payout = Decimal(stake_cents) * decimal_odds
    return int(payout.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
