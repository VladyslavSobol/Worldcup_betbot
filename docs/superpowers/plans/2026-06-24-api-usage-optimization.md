# API Usage Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce Odds API usage while preserving automatic settlement.

**Architecture:** Keep the existing scheduler and settlement service. Increase default polling intervals and add a database guard in the score job so the external scores endpoint is called only when a scheduled match started at least two hours ago.

**Tech Stack:** Python 3.12, APScheduler, SQLAlchemy asyncio, pytest, Docker Compose.

---

### Task 1: Configuration Defaults

**Files:**
- Modify: `app/config.py`
- Test: `tests/test_main.py`

- [ ] **Step 1: Write the failing defaults test**

```python
from app.config import Settings


def test_api_polling_defaults_are_credit_efficient():
    settings = Settings(_env_file=None)
    assert settings.odds_poll_seconds == 86400
    assert settings.scores_poll_seconds == 900
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
python -m pytest -q tests/test_main.py::test_api_polling_defaults_are_credit_efficient
```

Expected: failure because the current defaults are 900 and 300.

- [ ] **Step 3: Change the defaults**

```python
odds_poll_seconds: int = Field(default=86400)
scores_poll_seconds: int = Field(default=900)
```

- [ ] **Step 4: Run the test and verify it passes**

Run the same targeted pytest command. Expected: one passing test.

### Task 2: Score API Guard

**Files:**
- Modify: `app/main.py`
- Test: `tests/test_main.py`

- [ ] **Step 1: Write failing async tests**

Add one test with only future scheduled matches and assert that
`client.fetch_scores` is never called. Add a second test with a scheduled match
whose kickoff was more than two hours ago and assert that it is called once.

- [ ] **Step 2: Run both tests and verify the future-match case fails**

Run:

```bash
python -m pytest -q tests/test_main.py -k scores_job
```

Expected: the API is called even without an overdue match.

- [ ] **Step 3: Add the overdue-match query**

In `_sync_scores_job`, query for one `Match` where:

```python
Match.status == MatchStatus.scheduled
Match.kickoff_at <= datetime.now(timezone.utc) - timedelta(hours=2)
```

If none exists, log the skip and return before calling
`sync_scores_with_results`.

- [ ] **Step 4: Run the focused tests**

Expected: both score-job tests pass.

### Task 3: Verification and Publication

**Files:**
- Verify: `app/`
- Verify: `tests/test_main.py`

- [ ] **Step 1: Run focused tests**

```bash
python -m pytest -q tests/test_main.py tests/test_betting.py -k "polling or scores_job or sync_scores"
```

- [ ] **Step 2: Compile the application**

```bash
python -m compileall app
```

- [ ] **Step 3: Confirm the staged scope**

Stage only:

```text
app/config.py
app/main.py
tests/test_main.py
docs/superpowers/plans/2026-06-24-api-usage-optimization.md
```

Do not stage `.env`.

- [ ] **Step 4: Commit and push**

```bash
git commit -m "Optimize Odds API polling"
git push origin main
```
