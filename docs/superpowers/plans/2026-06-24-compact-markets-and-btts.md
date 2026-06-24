# Compact Markets and BTTS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deduplicate match presentation, reduce each match to four useful market groups, and support BTTS settlement.

**Architecture:** Centralize team canonicalization, filter main lines in the provider and UI, and extend the existing market enum and settlement function without modifying bet storage.

**Tech Stack:** Python, SQLAlchemy asyncio, PostgreSQL enum, aiogram, pytest.

---

### Task 1: Canonical Team Names and UI Deduplication

- [ ] Add failing alias and duplicate-list tests.
- [ ] Add a shared canonicalization helper.
- [ ] Use it in provider match lookup and match-list deduplication.
- [ ] Verify no database rows are deleted.

### Task 2: Compact Main Markets

- [ ] Add failing parser tests with alternative totals and spread rows.
- [ ] Select totals nearest 2.5 and spread nearest zero.
- [ ] Compact historical odds blocks in Telegram to the same main lines.
- [ ] Verify `1X2`, one totals group, and one spread group.

### Task 3: BTTS

- [ ] Add failing parser and settlement tests.
- [ ] Add `MarketType.btts`, Ukrainian labels, parsing, and settlement.
- [ ] Add idempotent PostgreSQL enum initialization.
- [ ] Verify single and express settlement use the existing flow.

### Task 4: Verification and Publication

- [ ] Run all relevant tests and compileall.
- [ ] Confirm `.env` and generated metadata are not staged.
- [ ] Commit and push to `main`.
