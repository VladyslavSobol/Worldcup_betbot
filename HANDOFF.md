# Handoff: World Cup 2026 Friendly Betting Bot

## Project

Private Telegram bot for friendly fake-money betting on World Cup 2026 matches.

Path:

```text
C:\Users\vlads\Documents\Codex\2026-06-22\new-chat\outputs\worldcup-betting-bot
```

Bot:

```text
@StavkiPoFanu_bot
```

Important: do not print, copy, or expose `.env`. It contains real secrets.

## Stack

- Python 3.12
- aiogram 3
- SQLAlchemy async
- PostgreSQL 16 via Docker
- APScheduler for odds sync
- The Odds API for odds data
- Docker Compose for local running

## Run Commands

From the project folder:

```powershell
docker compose up -d --build
docker compose logs --tail=40 bot
docker compose ps
```

Syntax check:

```powershell
docker compose run --rm bot python -m compileall app
```

Tests currently need dev dependencies. `pytest` is listed in `pyproject.toml` under `[project.optional-dependencies].dev`, but it is not installed in the current Docker image by default.

## Current Behavior

The bot is Ukrainian-language.

Private chat is for betting:

- `/start` creates user if needed and shows main menu.
- `🏟 Матчі` opens paginated matches.
- Match selection opens paginated odds blocks.
- User picks an odds button.
- User can choose preset stake or type custom amount like `4`, `4.50`, `12`.
- Balance is deducted immediately.
- Odds are locked on bet placement.

Group chat is for shared info, not betting:

- `/bind_group` binds the group for announcements.
- `/start` shows group menu.
- Bets are not made inside group messages because inline messages are shared between all users.
- Group buttons open private bot for betting.
- Group can show leaderboard, open bets, rules, explanations.
- New private bets are announced in the group.

## Main Commands

User commands:

- `/start`
- `/matches`
- `/mybets`
- `/openbets`
- `/leaderboard`
- `/balance`
- `/rules`
- `/explain`
- `/help`
- `/test_flags`

Admin commands:

- `/bind_group`
- `/admin_sync`
- `/admin_settle <match_id> <home_goals> <away_goals>`
- `/admin_void <match_id> [reason]`
- `/admin_close <match_id>`
- `/admin_reset`

Admin IDs are configured in `.env` as `ADMIN_TELEGRAM_IDS`.

## Menus

Private main menu includes:

- `🏟 Матчі`
- `🎟 Мої ставки`
- `🏆 Лідерборд`
- `👀 Відкриті ставки`
- `💰 Баланс`
- `📜 Правила`
- `📘 Пояснення ставок`
- `ℹ️ Допомога`

Group menu includes:

- `🎯 Ставити в приваті`
- `🏆 Лідерборд`
- `📜 Правила`
- `👀 Відкриті ставки`
- `📘 Пояснення ставок`
- `ℹ️ Як граємо?`

## Betting Rules

- Starting test balance: `$100.00`
- Minimum stake: `$1.00`
- Maximum stake: no separate max; users can bet up to their available balance.
- Bets close 5 minutes before kickoff.
- Decimal odds only.
- On bet placement, stake is deducted immediately.
- If win: `balance += stake * decimal_odds`
- If lose: no refund.
- If push/void: stake is returned.
- Leaderboard uses `balance + unsettled_stakes` as bankroll so open bets do not punish users.

## Supported Markets

Currently synced from The Odds API:

- `h2h`: 1X2 / winner / draw
- `totals`: over/under
- `spreads`: handicap / фора
- `outrights`: long-term winner markets, if API provides them

The UI has explanation text for:

- 1X2
- handicap / фора
- totals
- odds and payouts

Note: The Odds API currently rejects `btts` for `soccer_fifa_world_cup`, so do not include it in `ODDS_MARKETS`. Do not add fake fallback BTTS odds; users rejected fixed `1.90 / 1.90` as unrealistic for uneven teams.

## Important Files

```text
app/main.py
app/config.py
app/models.py
app/database.py
app/bot/handlers.py
app/bot/keyboards.py
app/bot/formatting.py
app/services/betting.py
app/services/sync.py
app/services/groups.py
app/integrations/odds_api.py
tests/
docker-compose.yml
pyproject.toml
.env.example
```

Do not expose:

```text
.env
```

## Recent State

On 2026-06-22:

- Test bets were reset.
- `DELETE FROM bets` removed 13 test bets.
- 5 users were reset to `balance_cents = 10000`.
- Database had `0` bets after reset.
- Bot was rebuilt and restarted successfully.
- Latest logs showed polling running and odds sync working.

Reset test state through the bot:

```text
/admin_reset
```

Fallback reset SQL:

```sql
DELETE FROM bets;
UPDATE users SET balance_cents = 10000;
SELECT COUNT(*) AS bets_left FROM bets;
SELECT telegram_id, username, first_name, balance_cents FROM users ORDER BY id;
```

Run via:

```powershell
docker compose exec -T db psql -U postgres -d worldcup_bot -c "<SQL>"
```

## UX Decisions Already Made

- Do not run betting flow in group chat. It causes conflicts because everyone clicks the same inline Telegram message.
- Keep group as scoreboard, announcements, rules, explanations.
- Keep betting in private chat.
- Keep odds buttons compact with team codes and flags where possible.
- Users can type custom stake amounts after selecting odds.
- Use Ukrainian text everywhere in the bot UI.

## Known Follow-ups

- Add real BTTS market if The Odds API supports it for the current World Cup sport key.
- Add cleaner bet confirmation screen before final placement.
- Add better open bet filtering by match/user.
- Add pagination to `/openbets` if many users start betting.
- Add pytest/dev dependencies to Docker test flow.
- Review all team flag mappings as new teams qualify.
- Consider explicit "private deep link" buttons for group onboarding.

## Suggested Prompt For A New Codex Chat

Use this in a fresh chat to save tokens:

```text
Продовжуємо Telegram betting bot.
Проєкт тут:
C:\Users\vlads\Documents\Codex\2026-06-22\new-chat\outputs\worldcup-betting-bot

Спочатку прочитай HANDOFF.md, потім працюй з кодом.
Не друкуй .env, там секрети.
Відповідай українською.
```
