# API Usage Optimization

## Goal

Reduce The Odds API credit usage enough for the 500-credit free plan while
preserving automatic match settlement.

## Scope

- Keep settlement calculations unchanged.
- Keep single bets and express bets unchanged.
- Keep the database schema unchanged.
- Do not read, print, or commit `.env`.
- Change only API polling intervals and the condition that permits score polling.

## Polling Design

### Odds

The default odds polling interval becomes 24 hours.

The bot still performs one odds synchronization when it starts so upcoming
matches and prices are available after a deployment or restart.

### Scores

The score scheduler runs every 15 minutes, but it calls The Odds API only when
the database contains at least one match that:

- has status `scheduled`; and
- started at least two hours ago.

When no such match exists, the job exits without making an API request.

The existing score endpoint and automatic settlement flow remain unchanged.
Once a match is settled and marked `finished`, it no longer causes score polling.

## Data Flow

1. APScheduler starts the score job every 15 minutes.
2. The job queries PostgreSQL for an overdue scheduled match.
3. If none exists, it logs that score synchronization was skipped.
4. If one exists, it calls the current `sync_scores_with_results` service.
5. Existing settlement updates single bets, express items, completed express
   bets, balances, statistics, and match status.
6. Existing Telegram group announcements are sent for settled results.

## Error Handling

Existing exception logging remains in place. API quota or network failures do
not change bets, balances, or match statuses because the database transaction
is not committed after a failed score request.

## Configuration

Default values:

- `ODDS_POLL_SECONDS=86400`
- `SCORES_POLL_SECONDS=900`

Values remain configurable through `.env`.

## Tests

Add regression coverage proving that:

- the new default polling intervals are used;
- score synchronization does not call the API without an overdue match;
- score synchronization calls the existing service when an overdue match
  exists.

Run the focused tests and `python -m compileall app` before committing and
pushing the implementation.
