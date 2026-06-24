# Expanded Match Markets Design

## Goal

Make the Telegram match screen easier to understand while adding useful betting
choices without returning to an oversized list of markets.

## Match Screen

The message uses this order:

1. Match teams, kickoff time, and open status.
2. A short instruction to tap the required odds.
3. Match result (1X2).
4. Double chance (1X and X2).
5. Three totals.
6. Three handicaps.
7. Both teams to score.
8. Back-to-matches and bet-slip controls.

All visible UI text remains Ukrainian.

## Market Selection

### Double Chance

Parse and store only:

- `1X`: home win or draw.
- `X2`: away win or draw.

The settlement result is based on the regulation-time score. A winning double
chance pays normally; otherwise it loses.

### Totals

Show at most three complete over/under lines. Select the main line whose two
prices are most balanced, then include its nearest available lower and higher
neighbors. Sort them by line.

### Handicaps

Show at most three complete two-team lines. Select the main line whose two
prices are most balanced, then include the nearest neighboring lines. Each
block must contain exactly one home option and one away option.

## Duplicate Protection

Extend team-name aliases for provider variants including Turkey/Turkiye,
South Korea/Korea Republic, and Bosnia & Herzegovina/Bosnia and Herzegovina.
The match list continues to prefer the current Odds-API.io row without deleting
legacy database rows or bets.

## Compatibility

- No database reset or schema redesign.
- Existing single and express bets remain valid.
- Existing settlement logic is unchanged except for adding double-chance
  evaluation.
- Old provider remains the fallback.

## Verification

Add parser, formatting, deduplication, single-bet settlement, and express
settlement tests. Run the relevant pytest suite and `python -m compileall app`
inside Docker before committing and pushing.
