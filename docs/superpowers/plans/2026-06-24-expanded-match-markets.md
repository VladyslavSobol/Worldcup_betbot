# Expanded Match Markets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add double chance, three useful totals, three useful handicaps, clearer match-screen formatting, and remaining team-name deduplication.

**Architecture:** Keep provider normalization in `odds_api_io.py`, persist the new market through the existing market/snapshot pipeline, and keep presentation selection in the bot handlers. Add only one enum value and one settlement branch; no database reset or changes to existing bets.

**Tech Stack:** Python 3.12, SQLAlchemy, aiogram, PostgreSQL, pytest, Docker Compose.

---

### Task 1: Double Chance Domain Support

**Files:**
- Modify: `app/models.py`
- Modify: `app/database.py`
- Modify: `app/services/sync.py`
- Modify: `app/services/settlement.py`
- Test: `tests/test_settlement.py`

- [ ] Add failing settlement tests for `1X` and `X2`.
- [ ] Run `pytest tests/test_settlement.py -k double_chance -v` and verify failure.
- [ ] Add `double_chance` to `MarketType`, PostgreSQL enum initialization, sync mapping, and regulation-time settlement.
- [ ] Re-run the focused tests and verify success.

### Task 2: Provider Parsing and Balanced Lines

**Files:**
- Modify: `app/integrations/odds_api_io.py`
- Test: `tests/test_odds_api_io.py`

- [ ] Add failing parser tests expecting `1X`, `X2`, three totals, and three two-sided spreads.
- [ ] Run the focused parser test and verify failure.
- [ ] Parse the provider double-chance market and select a balanced main line plus nearest neighbors for totals and spreads.
- [ ] Re-run parser tests and verify success.

### Task 3: Match Screen Presentation

**Files:**
- Modify: `app/bot/formatting.py`
- Modify: `app/bot/handlers.py`
- Modify: `app/bot/keyboards.py`
- Test: `tests/test_formatting.py`
- Test: `tests/test_betting.py`

- [ ] Add failing tests for Ukrainian double-chance labels and three total/spread blocks.
- [ ] Run focused tests and verify failure.
- [ ] Format the header, status, instruction, market names, and compact two-column options according to the approved mockup.
- [ ] Re-run focused tests and verify success.

### Task 4: Remaining Duplicate Team Names

**Files:**
- Modify: `app/team_names.py`
- Test: `tests/test_team_names.py`

- [ ] Add failing alias tests for Turkiye/Turkey, Korea Republic/South Korea, and Bosnia name variants.
- [ ] Run alias tests and verify failure.
- [ ] Add the minimal canonical aliases.
- [ ] Re-run alias and deduplication tests.

### Task 5: Full Verification and Publication

**Files:**
- Verify all changed files.

- [ ] Run the relevant pytest suite in Docker.
- [ ] Run `python -m compileall app`.
- [ ] Stop local Docker containers.
- [ ] Confirm `.env` is ignored and unstaged.
- [ ] Commit implementation separately from the design commit.
- [ ] Push `main` to GitHub.
