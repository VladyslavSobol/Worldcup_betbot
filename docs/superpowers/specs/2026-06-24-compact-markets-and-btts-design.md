# Compact Markets, Match Deduplication, and BTTS

## Goal

Remove duplicate matches from the Telegram UI, show a compact betting line, and
add "Both Teams To Score" using full-time regulation scores.

## Design

- Canonicalize provider team aliases and Unicode before matching:
  `Czechia/Czech Republic`, `RSA/South Africa`, and `Congo DR/DR Congo`.
- Reuse canonical names in sync and hide already-created duplicate match rows
  in match lists. Display the current Odds-API.io row while settlement updates
  every matching duplicate row so older bets remain valid.
- Parse only one main totals line (closest to 2.5) and one main spread row
  (closest to zero), plus `ML` and `Both Teams To Score`.
- The odds UI also compacts historical rows already stored in PostgreSQL, so
  old alternative lines stop appearing without deleting data.
- Add `MarketType.btts`; settle `Yes` when both regulation scores are above
  zero and `No` otherwise.
- On PostgreSQL startup, add enum value `btts` with
  `ALTER TYPE markettype ADD VALUE IF NOT EXISTS`.
- Do not delete matches, markets, odds snapshots, or bets.

## Verification

- Alias matching and UI deduplication tests.
- Main-line selection tests.
- BTTS parser and settlement tests.
- Existing betting, express, provider, and settlement tests.
- `python -m compileall app`.
