# Betting Flow, Playoff Market, and Express Settlement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show balances during stake selection, simplify every group keyboard, add bookmaker-provided playoff qualification bets, and settle losing expresses immediately without duplicate announcements.

**Architecture:** Keep balance rendering in handler view helpers, group navigation in one keyboard factory, provider normalization in the Odds-API.io adapter, and settlement decisions in the existing betting service. Extend `ScoreEvent` with an optional advancing team while preserving regulation scores for all ordinary markets.

**Tech Stack:** Python 3.12, aiogram, SQLAlchemy, PostgreSQL, pytest, Docker Compose.

---

### Task 1: Balance-Aware Stake Views

**Files:**
- Modify: `app/bot/handlers.py`
- Test: `tests/test_betting_flow.py`

- [ ] Add failing tests that single and express stake-selection text includes the current balance.
- [ ] Add failing tests that confirmation text includes balance before and projected balance after placement.
- [ ] Run the focused tests and verify they fail because balance data is absent.
- [ ] Fetch the current user in each view helper and render the four balance lines without changing placement validation.
- [ ] Re-run the focused tests and verify success.

### Task 2: Compact Group Keyboard

**Files:**
- Modify: `app/bot/keyboards.py`
- Test: `tests/test_betting_flow.py`

- [ ] Add a failing test asserting every group keyboard factory returns exactly the three approved buttons.
- [ ] Run the test and verify the old seven-button keyboard fails.
- [ ] Make `group_menu_keyboard()` and `group_private_keyboard()` return the same three-button layout.
- [ ] Re-run the focused test and verify success.

### Task 3: Immediate Express Loss

**Files:**
- Modify: `app/services/betting.py`
- Modify: `app/services/sync.py`
- Modify: `app/bot/handlers.py`
- Test: `tests/test_express.py`

- [ ] Add a failing test where one leg loses while another remains open and assert the parent express immediately becomes lost.
- [ ] Add a failing test that later settlement of another leg does not identify the already-lost express for another announcement.
- [ ] Run the focused tests and verify current wait-for-all behavior fails.
- [ ] Settle a parent express as soon as any item is lost, before checking for open items.
- [ ] Filter settlement target IDs to parent expresses that are still open.
- [ ] Re-run express and announcement-target tests.

### Task 4: Playoff Qualification Odds and Settlement

**Files:**
- Modify: `app/integrations/providers.py`
- Modify: `app/integrations/odds_api_io.py`
- Modify: `app/services/sync.py`
- Modify: `app/services/settlement.py`
- Modify: `app/services/betting.py`
- Modify: `app/bot/handlers.py`
- Modify: `app/bot/formatting.py`
- Test: `tests/test_odds_api_io.py`
- Test: `tests/test_settlement.py`
- Test: `tests/test_betting.py`
- Test: `tests/test_market_presentation.py`

- [ ] Add failing parser tests for common qualification-market names and two home/away prices.
- [ ] Add failing score tests for extra-time and penalty winners while retaining the regulation score.
- [ ] Add failing settlement tests for `MarketType.to_qualify`.
- [ ] Add a failing sync test proving qualification remains open when no advancing team is known.
- [ ] Add a failing UI test proving the qualification block is displayed only when provider odds exist.
- [ ] Run focused tests and verify failure.
- [ ] Normalize qualification markets to `to_qualify`, map selections to stored team names, and expose the block in the match screen.
- [ ] Extend `ScoreEvent` with `advancing_team` and derive it from top-level or penalty scores.
- [ ] Pass the advancing team into single and express settlement, skipping only qualification bets when it is unavailable.
- [ ] Keep qualification markets open for a later score sync when no winner is known.
- [ ] Re-run all focused tests.

### Task 5: Verification and Publication

**Files:**
- Verify all changed files.

- [ ] Run all relevant pytest modules in Docker.
- [ ] Run `python -m compileall app`.
- [ ] Stop local containers.
- [ ] Verify `.env` is ignored and no secrets are staged.
- [ ] Commit the implementation separately from the design commit.
- [ ] Push `main` to GitHub.
