# Odds-API.io Provider Design

## Goal

Use Odds-API.io with Unibet as the primary World Cup 2026 data provider while
keeping The Odds API as a fallback.

## Scope

- Preserve current settlement calculations.
- Preserve existing single bets, express bets, balances, and locked odds.
- Do not change the database schema.
- Do not add BTTS or other betting markets.
- Do not read, print, or commit `.env`.
- Support only the existing `h2h`, `spreads`, and `totals` markets.

## Configuration

Add these settings:

```text
ODDS_PROVIDER=odds_api_io
ODDS_API_IO_KEY=
ODDS_API_IO_BASE_URL=https://api.odds-api.io/v3
ODDS_API_IO_BOOKMAKERS=Unibet
```

The existing `ODDS_API_KEY` remains configured for fallback access to The Odds
API. If `ODDS_PROVIDER` is not set, the current provider remains the default so
existing deployments do not break before `.env` is updated.

## Provider Interface

Both providers expose the same internal operations:

- fetch normalized World Cup events and odds;
- fetch normalized completed scores.

The existing `OddsEvent`, `OddsMarket`, and `OddsOutcome` models remain the
normalized format consumed by the sync service.

Odds-API.io mappings:

| Odds-API.io | Internal |
|---|---|
| `ML` | `h2h` |
| `Spread` | `spreads` |
| `Totals` | `totals` |

Only the configured bookmaker is parsed. Missing bookmakers or markets are
ignored without failing the entire synchronization.

## Odds Requests

1. Fetch football events from `/events`.
2. Keep events whose league name identifies the FIFA World Cup.
3. Keep relevant scheduled or live events.
4. Fetch odds through `/odds/multi` in batches of up to ten event IDs.
5. Request only the configured bookmaker, initially Unibet.
6. Convert the response into the existing normalized event structures.

The multi endpoint counts each batch as one API request.

## Match Identity and Duplicate Prevention

Provider event IDs differ, while the database has one `api_id` column.

For every normalized event, the sync service finds a match in this order:

1. Exact `api_id` match.
2. Existing match with the same normalized home and away team names and kickoff
   time within 15 minutes.

New Odds-API.io matches use:

```text
odds_api_io:<event_id>
```

When a pre-existing match is found by teams and time, its row is reused. Its
`api_id` is not replaced if it already has bets or express items, preventing
identity changes from affecting historical records. No duplicate match row is
created.

Team comparison is case-insensitive and whitespace-normalized. Home and away
order must match.

## Score and Settlement Flow

Odds-API.io `/events` includes `status` and `scores`.

An event is treated as completed only when:

- its status is settled/completed; and
- full-time home and away scores are present.

The score sync finds matches using the same identity rules as odds sync, then
passes the database match ID and score to the existing `settle_match` function.
All current single-bet, express-item, express-bet, balance, statistics, and
Telegram announcement behavior remains unchanged.

Already finished, canceled, or postponed matches are skipped. This prevents
double settlement if both providers return the same result.

## Fallback

The provider selected by `ODDS_PROVIDER` is primary.

For each scheduled job:

1. Try the primary provider.
2. On authentication, rate-limit, timeout, network, or server error, log the
   provider failure without logging its key.
3. Try The Odds API once as fallback if its key is configured.
4. If both fail, leave the transaction uncommitted and log the final failure.

An empty valid response is not considered a provider failure and does not
trigger fallback.

Fallback is applied independently to odds synchronization and score
synchronization.

## Manual Admin Sync

`/admin_sync_odds` uses the same primary-provider and fallback path as the
scheduler. It does not instantiate The Odds API directly.

## Error Handling

- API keys are redacted from logged URLs and exceptions.
- Invalid numeric odds are skipped.
- Missing markets, bookmakers, score objects, or team names are skipped.
- One malformed event does not discard other valid events in the response.
- No database commit occurs after both providers fail.

## Tests

Add tests for:

- Odds-API.io event parsing and World Cup filtering.
- Unibet `ML`, `Spread`, and `Totals` normalization.
- `/odds/multi` batching at ten events.
- Matching a new provider event to an existing database match without creating
  a duplicate.
- Completed score normalization.
- Existing settlement flow using an Odds-API.io result.
- Primary success without fallback.
- Primary provider error followed by fallback success.
- Both providers failing without database changes.
- `/admin_sync_odds` using the configured provider path.

Run focused tests, the existing betting and express suites, and
`python -m compileall app` before pushing.
