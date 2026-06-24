# Odds-API.io Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Odds-API.io with Unibet as the primary World Cup 2026 odds and score provider while preserving The Odds API as fallback.

**Architecture:** Introduce a provider-neutral protocol and normalized score event. Keep the current normalized odds models and sync service, add provider-aware match lookup by exact ID or teams and kickoff, and wrap primary/fallback selection in one client used by scheduler and admin sync.

**Tech Stack:** Python 3.12, aiohttp, SQLAlchemy asyncio, APScheduler, pytest, Docker Compose.

---

### Task 1: Configuration and Provider Contract

**Files:**
- Modify: `app/config.py`
- Modify: `.env.example`
- Create: `app/integrations/providers.py`
- Test: `tests/test_providers.py`

- [ ] Write failing tests for new settings defaults and fallback behavior.
- [ ] Run `python -m pytest -q tests/test_providers.py` and confirm missing imports fail.
- [ ] Add `OddsProvider` protocol, `ScoreEvent`, provider factory, and fallback wrapper.
- [ ] Add `odds_provider`, `odds_api_io_key`, base URL, and bookmaker settings.
- [ ] Re-run the focused tests.

### Task 2: Odds-API.io Client

**Files:**
- Create: `app/integrations/odds_api_io.py`
- Test: `tests/test_odds_api_io.py`

- [ ] Write failing parsing tests for World Cup filtering, Unibet `ML`, `Spread`, `Totals`, completed scores, and ten-event batching.
- [ ] Run the test file and confirm failures.
- [ ] Implement event fetching, multi-odds batching, normalized markets, score parsing, safe errors, and key redaction.
- [ ] Re-run the test file until green.

### Task 3: Provider-Neutral Sync and Match Reuse

**Files:**
- Modify: `app/services/sync.py`
- Test: `tests/test_betting.py`

- [ ] Write failing tests proving an Odds-API.io event reuses an existing match by teams and kickoff and its completed score settles that match.
- [ ] Run the targeted tests and confirm duplicate/lookup failures.
- [ ] Replace provider-specific sport-key calls with provider-neutral `fetch_odds()` and `fetch_scores()`.
- [ ] Add exact-ID then normalized-teams-plus-15-minute match lookup.
- [ ] Preserve existing `api_id` on reused rows and prefix new Odds-API.io IDs.
- [ ] Re-run targeted tests.

### Task 4: Scheduler and Admin Integration

**Files:**
- Modify: `app/main.py`
- Modify: `app/bot/handlers.py`
- Test: `tests/test_main.py`

- [ ] Write failing tests for provider factory use and fallback execution.
- [ ] Run focused tests and confirm direct `OddsApiClient` construction fails expectations.
- [ ] Build the provider once in `main()` and pass it to scheduler jobs.
- [ ] Make `/admin_sync_odds` use the same provider factory.
- [ ] Keep existing score guard and group announcements unchanged.
- [ ] Re-run focused tests.

### Task 5: Verification and Publication

**Files:**
- Verify: `app/`
- Verify: `tests/`

- [ ] Run provider, main, betting, and express tests.
- [ ] Run `python -m compileall app`.
- [ ] Confirm `.env` is not staged and generated egg-info files are restored.
- [ ] Commit with `Integrate Odds-API.io provider`.
- [ ] Push `main` to GitHub.
