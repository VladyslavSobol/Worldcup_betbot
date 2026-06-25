# Betting Flow, Playoff Market, and Express Settlement Design

## Goal

Improve the betting flow and group-message ergonomics, add a real bookmaker
market for playoff qualification, and settle a losing express immediately
after its first losing leg.

## Stake Selection

### Single Bet

When a user chooses a market and opens the stake selector, the message shows:

- the match;
- the market and selection;
- the locked decimal odds;
- the user's currently available balance;
- the existing preset stake buttons and custom amount button.

The confirmation message also shows:

- stake amount;
- potential payout;
- available balance before placement;
- projected available balance after placement.

The balance is fetched from the database when the view is opened. Existing
placement validation remains authoritative if the balance changes before
confirmation.

### Express Bet

When a user chooses the express stake, the message shows:

- current express total odds;
- available balance;
- preset stake buttons and custom amount button.

The final express confirmation shows the projected balance after placement.

## Group Keyboards

Every bot message sent or edited in a Telegram group uses one compact keyboard:

1. `🎯 Ставити в приваті`
2. `📅 Ставки на сьогодні`
3. `👀 Відкриті ставки`

The private-betting and today buttons open the bot's private chat. Open bets
continues to work in the group through its existing callback.

Private-chat keyboards are unchanged.

## Playoff Qualification Market

### Availability

Show `🏁 Прохід далі` only when the configured Odds-API.io bookmaker actually
returns a two-way qualification market for the event. Do not derive or invent
qualification odds from `1X2`.

The parser accepts known provider naming variants for this market and normalizes
the two selections to the stored home and away team names.

### Display

The playoff match screen shows one qualification block with two buttons:

- home team to qualify;
- away team to qualify.

The market remains available to both single bets and express bets through the
existing betting pipeline.

### Settlement

All ordinary markets continue to settle from the regulation-time `ft` score.

`Прохід далі` settles from the actual advancing team:

1. Use the top-level event score when it contains the extra-time or
   penalty-inclusive winner.
2. If the top-level score is tied, use the penalty-shootout (`ap`) score.
3. If no advancing team can be determined safely, leave the qualification
   market open and log the reason instead of guessing.

The score provider result therefore carries both the regulation score and an
optional advancing-team value. Existing match rows and ordinary settlements
are not reinterpreted.

## Early Express Loss

When an express item settles as lost:

- the parent express immediately changes from `open` to `lost`;
- `payout_cents` becomes `0`;
- `settled_at` is recorded;
- no balance is credited;
- the group settlement announcement is emitted immediately.

Other still-open items remain stored for history and may later receive their
own item statuses, but they cannot settle or announce the already-lost parent
express a second time.

Winning and void express behavior is unchanged: the bot still waits until no
items remain open before calculating a win, reduced odds, or full refund.

## Safety and Compatibility

- Do not reset or delete users, bets, express bets, matches, or balances.
- Do not modify `.env`.
- Do not invent bookmaker odds.
- Do not change ordinary 90-minute settlement semantics.
- No database schema change is required because `MarketType.to_qualify`
  already exists.

## Verification

Add regression tests for:

- balance visibility during single and express stake selection;
- the three-button group keyboard;
- provider qualification-market parsing;
- qualification settlement after extra time and penalties;
- safe non-settlement when an advancing team is unavailable;
- immediate express loss with other legs still open;
- no duplicate parent-express settlement or announcement;
- unchanged single-bet, express-win, express-void, and ordinary-market behavior.

Run the relevant pytest suite and `python -m compileall app` in Docker before
committing and pushing.
