# Orders at a price, smart prices, order programs, and cancelling a pending close: the build spec

Design only. Written 2026-10-31 against the read-only checkout `/home/user/Sauron_Vision/.claude/worktrees/invest`, main `dbfe0a9`, and **revised the same day after the critics' review**. §13 lists every finding, where it landed, and what was changed from the proposed fix. Nothing in that tree was edited and nothing was sent to any venue. Every `file:line` is at `dbfe0a9`. Inputs: `map_path.md` (the order path), `map_venue.md` (what eToro can hold), `map_levels.md` (the levels the code computes), and the code they cite, re-read for this spec.

**Mockups.** There are four pages, each rendered at 1280 and 390 wide (`mockups/*_1280.png`, `mockups/*_390.png`) by `render.js`, with Playwright and Chromium. At 390, all four pass with no sideways scroll.
* `mockups/ticket.html`: the ticket with MARKET, with LIMIT on real money, and armed in shadow.
* `mockups/working_orders.html`: the positions page's WORKING ORDERS card, the pending-close rows, and the dialogs from P1 and P2.
* `mockups/orders_page.html`: the `/orders/` page, with its Shadow and Recent tabs.
* `mockups/program_builder.html`: the program list first, then the builder (beside it at 1280, under it at 390).

How the mockups are built:
* They link copies of the platform's own sheets: `mockups/css/sauron.css`, `sv-overlay.css` and `sv-responsive.css`.
* The only new rules are in `mockups/css/orders.css`, which is the CSS this build would add.
* `mockups/css/mock-frame.css` (the page chrome and the dialogs drawn in place) and `mockups/css/fonts.css` (a local copy of base.html's Google fonts, for the headless render) are for the mockups only.
* The mockups are set on Saturday 31 Oct 2026, today. Forex, stocks and gold are shut and crypto trades, so the shut markets appear as HELD or as queued.

---

## 0. The request, and how it is read

**Verbatim (2026-10-31):** "add order placing at special price too please options and make it smart on certain assets or programmable, by me and the bots please, this can be huge... Also, cancel the closing order possibility please."

**How each part is read:**

| Words | Read as | Phase |
|---|---|---|
| "order placing at special price ... options" | Order types on the TAKE TRADE ticket and the deal ticket: Market, Limit, Stop entry, with a price, an expiry, a stop and a target | P2 |
| "smart on certain assets" | Per asset class, one-tap prices built from levels the platform already computes, each shown with its source and its age | P3 |
| "or programmable" | An order program: conditions, then an order, saved and listed, run by one scheduled task | P4 |
| "by me and the bots" | The operator places and programs orders. Bots run the same programs (P4) and get their own entry at a level (P5) | P2, P4, P5 |
| "cancel the closing order possibility" | **Cancel a close that is pending:** one eToro has accepted and not confirmed (for example queued while the market is shut), or one the platform keeps retrying. The close button stays | P1 |

**The other reading, in one line:** "remove the possibility of closing" (take the close button, or the automatic closes, away). This spec does not build that. The operator must confirm the reading (§11, decision D1).

"Options" is read as "order options". The options asset class gets no orders at a price and no smart prices: a premium has no crowd levels (`smart_money.lock_adjuster` :951), and the options lane has its own send path (`options_bot.py:134`).

---

## 1. Rules every phase keeps

### 1.1 The safety rules, and where each one bites a new order

| Rule (existing code) | P1 cancel a close | P2 operator's order at a price | P4 program / P5 bot level |
|---|---|---|---|
| Proof gate per class, size by proof (`base.py:4608`, `_proof_gate` :4982; manual `_etoro_entry_refusal` `manual_trade.py:2642`) | n/a | Re-run at fire. A class unticked, or a proof withdrawn, while the order rests cancels it | Bot path: `propose_entry` is re-run at fire with `at_fire=order` (§8.3). A bot-run program's rule name `program:<id>` has no `RuleControl` row, so `rule_actuator` forces it to paper (`signals/rule_actuator.py:106-112`) until the operator promotes it on the existing ladder. Code never creates that row |
| Pool and pledge (`_leverage_headroom` :7441, `pledged_ceiling` :403; manual headroom `manual_trade.py:2689`) | n/a (no new size) | Re-run at fire, and an unread pool or pledge is a HOLD. Venue-held and IN_DOUBT orders reserve their margin (`price_orders.reserved_risk`) | same |
| Open-risk cap (`portfolio/risk_gate.py:848`) | The row counts as exposure in both states (OPEN and CLOSE_PENDING), so the cap does not move | Re-run at fire as a refusal, and an unread state is a HOLD. Venue-held and IN_DOUBT orders reserve their risk | same |
| Daily stop (book advisory on the manual lane; hard for bots) | n/a | **Always a refusal at fire**, even if the operator accepted it at placement. An unreadable book (`risk_gate.preflight` `failed_open`, :1979-2016) is a HOLD, never a pass (§5.4). A venue-held order is withdrawn when the daily stop is reached (§5.15) | hard; same withdrawal |
| Venue minimum and fraction (`_venue_size_floor` :7632, `_venue_fractional_units` :7739) | n/a | Re-run at fire (a money floor moves with the price) | same |
| Entry timing (`entry_timing.verdict` :508, `SHUT_CLASSES` :119, `OPEN_SETTLE_MINUTES` :93) | An eToro row retrying while its market is shut cannot be cancelled (§3.2) | At fire, **fail-closed**: an unreadable clock or calendar is a HOLD. SHUT, the rollover, the opening quarter hour and an event window HOLD. eToro's own quote older than 30 s, or the first eToro print after a gap of more than 15 minutes, HOLDs **whatever the class, index included**. A WaitingForMarket answer is withdrawn at once (§5.6) | same |
| Quote sanity and the pre-send re-read (`_entry_quote_gate` :5030, `_last_look(..., fail_closed=True)` :5077) | The cancel re-reads the venue's own word on the position before it changes anything | `fail_closed=True` (its first caller), anchored on the ORDER price. A non-positive bid or ask from eToro is unreadable (`etoro_client.py:1515-1542`) | same |
| In doubt: a POST that times out is never re-sent blind (`EtoroOrderInDoubt` `etoro_client.py:740-771`; `_remember_in_doubt` `base.py:1668`) | `close_in_doubt` rows can never be cancelled. P1a makes eToro's `close_position` mark an after-send timeout as in doubt (§3.3a). A retrying row whose last error was a transport failure counts as in doubt | IN_DOUBT is resolved only by the operator's hand act, or by a measured read of eToro's open orders (M12). Until then it reserves its risk and keeps the symbol's note. Code never re-arms it or cancels it (§5.6a) | same |
| Venue-health circuit (`venue_health.refusal` :273) | n/a | HOLD while sick. A 429 on `orders:lookup` is now counted on the venue's health (§9) | same |
| Anti-hunt stops (`smart_money.stop_beyond_the_crowd` :221) | A hold never suppresses a stop | Operator lane untouched, as today; a preset carries the level's own stop, already beyond the crowd (`orcs/menu._stop_for` :111) | Bots: `entry_read` re-run at fire when `smart_money` is ON |
| Care of open positions (`position_care.care` :647; `manage_positions` walks OPEN only, `base.py:1084`) | **A cancel is refused unless something will manage the row afterwards**: its config is enabled or a brake keeps it managed (`disarm.keeps_managing`, `disarm.py:123`), and the tick runs (`manual_trade._tick_manages` :363). A cancelled close returns the row to OPEN; an exit hold stops the same rule re-closing it | A filled order is an ordinary row, with the same care as TAKE TRADE | same |
| The claim (`manual_close.CLAIM_KEY` :63, TTL 120 s :68) | Taken by the cancel. It is the same claim the drain, the CLOSE button, the reconcile and the kill switch honour | n/a | n/a |
| World and mode (`EtoroAccount.demo` alone picks the segment, `base.py:7500-7506`; the manual lane is `paper` or `live`, `manual_trade.py:344-350`) | n/a | Derived again at fire from the routed client and the config's current mode. A mismatch with the order's stored world cancels it and sends nothing. The demo-to-real flip and the lane's paper-to-live arm are refused while orders rest (§5.8) | same |
| The eToro request budget (new, §9) | Closes, close proofs and the kill switch spend from a reserve that entries cannot touch | Every entry sender shares one bucket per eToro key. Over budget is a HOLD | same |

### 1.2 One path to money

Nothing new sends an entry by itself.
* An operator order fires through `manual_trade._execute` (:1995), the same function the TAKE TRADE button runs, with a new `at_fire=` argument.
* A bot order fires through `AssetBot.propose_entry` (:4196) and `execute_entry` (:5543), re-run at fire with `at_fire=order`.
* A program does not send. It creates a `PriceOrder`, which then goes through one of the two paths above.
* **A shadow order never reaches `_execute` or any client.** Its gates are judged by the same pure function the fire uses (`price_orders.judge`, §5.4), which reads and never writes.

### 1.3 Shadow before power

Every new automated power arrives in shadow, graded, behind a component switch that is OFF on arrival (`core/platform_control.py`; `seed_components` never touches `is_enabled`, :547-549).
* Every switch whose name ends in `_live` goes into `LIVE_MONEY_SWITCHES` (:97-110). `tests/test_ops_cockpit.py` fails otherwise, and "all on" never arms it (`BULK_ENABLE_EXEMPT` :126).
* Descriptions stay under 300 characters (`tests/test_component_registry.py`).
* **Turning a `_live` switch OFF** cancels or pauses what it allowed, in every world it covered, with words (§5.11, §7.6, §8.5).
* **Turning one ON promotes nothing already armed in shadow.** An order's mode is read only from its stored field.

### 1.4 The PIN door of every new act

`core/trading_pin.py:12-27`: STOP is for an act that only reduces risk; ACT is for anything that opens, arms, moves or withdraws money.

| Act | Money direction | Door |
|---|---|---|
| Cancel a pending close | Keeps a position the platform was closing: risk stays on, or comes back | **ACT** |
| "I cancelled it at eToro" (records the operator's claim) | Leads to more risk | ACT |
| Withdraw a working entry (exists) | Removes an order that would add risk | STOP (as today, `views_close.py:124`) |
| Place an order at a price | Arms risk for later | ACT |
| Move an order's price | A cancel, then a new order | ACT |
| Cancel an order, cancel selected, cancel all | Removes armed risk | STOP |
| Resolve an in-doubt order by hand ("nothing from it is at eToro") | Releases the reserved risk and lets a new order be placed | ACT |
| Let a venue-held order rest through a shut (P2b, after M6b) | Keeps risk armed across a gap | ACT |
| Save a program in shadow; edit or copy one (it lands paused, in shadow) | Nothing can send | no PIN |
| Turn a program LIVE, or resume a live one | Arms risk | ACT |
| Pause or cancel a program (and its armed orders) | Removes armed risk | STOP when live |
| Turn a bot config's level entry LIVE | Arms risk | ACT |
| Release an exit hold | Adds no risk | none |

* A paper row never asks for the PIN, as today (`manual_close.requires_pin` :272). A DEMO row asks for it, as every non-paper row does today.
* **Only the door's name and the time the PIN was checked are stored**, on any row. The PIN is never stored, and neither is a hash of it. A test pins this (§5.13).

### 1.5 The words

All platform text is English. Each refusal says what it was, what did not happen, and what to do (`trading_pin.sentence` :623 is the model). A message never states as a fact what the reads cannot establish. Two examples: the moment eToro will execute a queued close, and whether an order sent into a timeout exists.

---

## 2. The phases at a glance

| Phase | What ships | Switch on arrival | Migration | Needs first |
|---|---|---|---|---|
| **P1a** | eToro's close in-doubt split (§3.3a). Cancel a close the platform is retrying after a venue refusal with the market open, or one accepted at Alpaca, Saxo or IBKR. The manager check, the kill-switch marker, the exit hold, honest words for eToro's accepted close, "I cancelled it at eToro" recorded as a claim only, the withdraw labels, the two-view dialog | none (an act per row, with the PIN) | none (metadata) | nothing |
| **P1b** | Cancel eToro's queued close from the platform, and return a hand-cancelled row to OPEN, both proven by eToro's close-order read | `etoro_close_cancel_live` OFF | none | M7 (extended, a-d), M8, the DELETE's own attestation |
| **P2a** | Limit and Stop entry on both tickets, held by the platform; expiry; the `/orders/` page and the WORKING ORDERS card with cancel, bulk cancel and MOVE. Paper and demo fire; real money stays in shadow | `price_orders` OFF, `price_orders_live` OFF | `0046_price_orders` | the in-doubt fix (§5.9), the shared eToro budget (§9), M9, M11, M12, M13, M14 |
| **P2b** | Limit held by eToro (MIT) where the instrument allows it | `etoro_mit_live` OFF | none | M1-M6, M4b, M6b, M10 |
| **P3** | Smart prices on the ticket, per class, with source and age | none (fills a field) | none | P2a |
| **P4** | Order programs: list, builder, edit, copy, pause, cancel; one evaluator; shadow grading; bots may run them | `order_programs` OFF, `order_programs_live` OFF | `0047_order_programs` | P2a, P3 |
| **P5** | Bot entry at a named level: a would-order in shadow, graded against the market entry; live per config with the PIN and a grant | `bot_entry_levels` OFF, `bot_entry_levels_live` OFF | `0048_entry_level_grants` | P2a, P3, P4's grader |

**P0: the demo measurements.** Each one is the venue's answer to a question the design relies on. The P2a set comes before P2a, because P2a already fires orders automatically.

| Step | On DEMO (real only where said) | Gates |
|---|---|---|
| M1 | The eligibility row: does it carry `allowMitOrders`? | P2b |
| M2 | An MIT order far from the market: its status, and the raw `/portfolio` `orders[]` | P2b |
| M3 | Cancel it with DELETE v3: does v3 cancel a status-12 order? (`etoro-go` uses a v2 DELETE for orders, `trading.go:170-179`; the platform measured v3 only on status 11) | P2b |
| M4 | An MIT on the wrong side | P2b |
| M4b | An MIT buy with the trigger between bid and ask: accepted, refused, or filled at once? This shows which side of eToro's quote the trigger is compared with | P2b |
| M5 | `limitIOC` | P2b |
| M6 | An MIT that triggers: do its legs attach? | P2b |
| M6b | An MIT placed on Friday before the close, trigger near the last price: its status over the weekend, the frozen cash, and the fill against the trigger at the open | P2b (until it is pinned, a venue-held order is withdrawn before every shut) |
| M7 | The close-order read in four states (§3.5): (a) a close queued on a held position while shut, read by `close-orders/{id}` and the raw `/portfolio` `ordersForClose`; (b) the same after a hand cancel in eToro's web app; (c) another one cancelled by the API's DELETE; (d) one left to execute at the open | P1b |
| M8 | The DELETE of a queued close: demo, then real at minimal size. Record the status code; it becomes the DELETE's attestation entry | P1b |
| M9 | The same `x-request-id` UUID sent twice, on an order far from the market: what does the second POST answer? | P2a |
| M10 | Status 8 | P2b |
| M11 | The 429's body and headers; and whether order POSTs, close POSTs and lookups share one quota group | P2a |
| M12 | One market order off hours (1 unit GLDM, as D2b did), then the raw `/portfolio`: does `clientPortfolio.ordersForOpen[]` list it, with which keys (`orderId`, `instrumentId`, `isBuy`, `units`), and what does the frozen cash show? | P2a |
| M13 | `GET /api/v1/market-data/instruments/rates?instrumentIds=<3-5 ids>`: the HTTP status, how many rows, the row keys (`bid`, `ask`, `lastExecution`, the date field `etoro-go` maps), and whether it counts as one request. If the comma form fails: the `wire_reads` the fleet spends per minute, to learn whether N one-symbol reads fit inside the shared 60 a minute | P2a |
| M14 | The eligibility row and the rates row for an index and a US stock outside cash hours: is there any market-open field? | P1a words, P2a |

* They go through a new management command, `manage.py etoro_order_probe <step> --demo --yes`, beside `etoro_smoke.py`.
* Each step runs the world check first (`ETORO_DEPARTURE.md:376-388`) and prints values, never a key.
* Each answer is written into `etoro_client.py` as a dated measured comment and pinned in `tests/test_etoro_client.py`, which is the platform's existing practice.

---

## 3. P1: cancel a pending close (and a pending entry)

### 3.1 What the operator gets

* **On every CLOSE_PENDING row** (positions page, the Eye, forensics), RETRY CLOSE gets a second button beside it:
  * **CANCEL CLOSE** for a close the platform is retrying, or one working at Alpaca, Saxo or IBKR;
  * **CANCEL AT ETORO…** for a close eToro accepted and has not confirmed, while P1b is off.
* **The pending-close dialog has two views (§3.6).**
  * The first view has RETRY CLOSE and KEEP TRYING in the foot. Its body has a link: "Keep the position instead…".
  * That link opens the cancel view. It holds the warning, the hold choice, its own PIN box, and BACK and CANCEL CLOSE.
  * The row's CANCEL CLOSE opens the dialog straight in the cancel view. See `mockups/working_orders_1280.png`.
* **A working entry reads as an order everywhere:** WITHDRAW on the row, and "Withdraw this order?" in the dialog.
* **Telegram:** the pending-close alert's button is relabelled "Retry or cancel close". It is the same URL to the same dialog (`/positions/<id>/close-dialog/`, `alerts/links.close_path` :77). Nothing acts from Telegram.

### 3.2 The sub-states, and what a cancel does in each

The verb re-reads the row under the claim and decides on what it finds there, never on the preview.

| Sub-state (status + metadata) | What is live at the venue | CANCEL CLOSE does | Ends as |
|---|---|---|---|
| **Retrying after a refusal**: CLOSE_PENDING with none of `close_order_working`, `close_in_doubt`, `close_fills`; the last error (`close_retry_last_error`, or the CLOSE_PENDING reason) is an answer the venue gave (an HTTP 4xx or 5xx body), not a transport failure; and, on eToro, the instrument's market is open | Nothing, as far as the reads can tell: the venue refused the close (`base.py:3663-3693`) | Reads the venue's own word (`venue_position_state`, `pending_closes.py:1615`) and the book (`broker_exposure` :752) **outside the lag window** (`reconcile_asset.venue_lag_window`). On adapters that list working orders (Saxo `resting_order_ids`, Alpaca orders), the list must show no resting close for the symbol. Held: the drain stops. Flat: refused ("it already closed; the drain will book it"). Unreadable: refused | OPEN, or unchanged |
| **Retrying after a transport failure**: the last error is a timeout, a reset or a connection error | A close **may** have reached the venue. eToro closes by position id and may hold it queued; on a netting venue (Alpaca, IBKR) it may rest, and the next close would stack on it. `close_position` posts and calls `raise_for_status` (`etoro_client.py:2802-2806`), so a read timeout surfaces as a plain error and `close_in_doubt` is never written (`base.py:3586-3600`, :3663-3670) | Refused, as in doubt: "The last close attempt timed out after it was sent, so eToro may hold it. Nothing changed. Check eToro's app" | unchanged |
| **Retrying at eToro while the market is shut** (the exchange's clock, `core.exchange_status`; eToro may open earlier, which only makes this refusal more careful) | eToro may have queued an earlier close | Refused | unchanged |
| **Working at Alpaca, Saxo or IBKR**: `close_order_working` on an adapter that can cancel and prove | An accepted close that has not printed | `_cancel_working_close` (:1024), then `_reconcile_filled_against_broker` (:1071). OPEN only if 0 filled, the book still holds the full size, and no resting close is listed | OPEN, or unchanged |
| **Accepted at eToro, not confirmed**: `close_order_working` on an eToro row | eToro accepted the close and the platform could not prove it executed. If the market is shut, it executes at eToro's next open (`map_venue` §7). This flag is also set for an in-session close behind 500s or a 429, whenever the proof ran out (§3.5) | **P1a:** refused, saying what is known, with I CANCELLED IT AT ETORO, which records a claim only (§3.5). **P1b**, with the switch ON: the DELETE, proven by the close-order read | unchanged; or `close_cancel_requested`; OPEN only through §3.5's rule |
| **Partial**: `close_fills` not empty | Part of the position is closed | Refused: the row's qty would have to become the residual and its fills booked, and that is not a cancel | unchanged |
| **In doubt**: `close_in_doubt` on an OPEN or CLOSE_PENDING row | A close that MAY be live | Refused, always | unchanged |
| **Abandoned**: ERROR with `close-abandoned` | The platform stopped trying after 12 attempts (`_give_up` :1475) | Not offered: the words stay "close it at the broker" | unchanged |
| Paper row | n/a: a paper row never reaches CLOSE_PENDING (the drain is live only, `pending_closes.py:1912`) | Not offered | n/a |

**More refusals, whatever the sub-state**, checked under the claim, in this order:
* **Nothing would manage the position after the cancel.** This applies in two cases:
  * The row's config is disabled and no brake keeps it managed: `row.config.enabled or disarm.keeps_managing(row.config)` is false. A real row on a config that the kill switch or a hand stopped is never walked by the runner (`runner.py:66-72`, and the `unmanaged_on_disable` docstring at :87: "they lose every exit the platform runs itself").
  * The tick is off: `manual_trade._tick_manages()` is false. That function is the gate the live ticket already demands (:2101-2108).

  The words are: "Nothing would manage this position after the cancel: crypto-1 is stopped (by the kill switch) / the 5-minute tick is off. Its time stop, trailing, care and the SL/TP check would not run. Nothing changed."
* **The kill switch asked the close.** The marker is `close_intent.family == "KILL"`, which `kill_switch._close_asset_trade` now stamps on every row it leaves CLOSE_PENDING (§3.4). The options expiry (`EXPIRY_CLOSE`, `options_bot.py`) is refused the same way. Undoing one leg of an emergency flatten, or keeping an option through its expiry, is a separate decision, and the words say so.
* **The stop is already crossed.** The mark is through the row's current stop, or through the care's soft stop (`metadata.care.soft_stop`). The bot-side SL (`base.py:1435-1450`), the care (`position_care.plan` :529) or the venue would close it again. The words are: "The stop is already crossed: move the stop first, then cancel."
* **The claim is held** by the drain, the CLOSE button, the reconcile or the kill switch: "A close for X is in flight right now; nothing changed."

### 3.3 The verb: `bot_program/close_cancel.py`

This is a new module, kept out of `pending_closes.py` (1961 lines). It imports the claim (`manual_close._claim` :417, `_release` :449) and the drain's readers. It is a verb beside RETRY, not a new close path.

```
preview_cancel(user, trade) -> dict          # no claim, no write
cancel_pending_close(user, trade, *, pin_ok, hold_hours=None) -> dict
```

`cancel_pending_close`, in order:
1. If `requires_pin(trade)` and `pin_ok` is false, return the refusal; nothing is claimed. The view supplies `pin_ok` from `_pin_ok(request, body, door=ACT, act="cancel a pending close")`.
2. Take the claim with `manual_close._claim(user, trade.pk)`. The status must be CLOSE_PENDING, re-read under `select_for_update`. A held claim refuses.
3. Under the claim, read the sub-state from the locked row (§3.2). Refuse each case §3.2 refuses, the manager check (`_manager_refusal(trade)`) and the KILL marker included.
4. Get the client with `client_for_symbol`. A live row routed to PaperTrader (`_live_broker_missing`, `manual_close.py:83`) refuses, because nothing can be proven.
5. **Prove the position is still held**, with the drain's own readers, in the drain's order (`retry_trade_close` :1695-1778):
   * `venue_position_state` first;
   * then `broker_exposure`;
   * on adapters that list working orders, the list for the symbol, which must hold no resting close;
   * inside `venue_lag_window`, refuse ("the venue's book is settling; try again in a minute").
   * Only "open", or HELD outside the lag window, goes on.
6. For the **working at Alpaca, Saxo or IBKR** case, run `_cancel_working_close(trade, client)`; a result that is not True refuses. Then run `_reconcile_filled_against_broker`. Any filled qty refuses with "part of it closed while cancelling; the drain books the rest".
7. **Mark price check.** Read `bot._mark_price`. If the mark is through the current stop or the soft stop, refuse (§3.2).
8. **Write, under `select_for_update` on the pk.** It re-reads the row, never the in-memory one, for the same reason as `_release` (:449). It re-reads the config too, and runs `_manager_refusal` again: a config stopped during the cancel refuses here.
   * `status = "OPEN"`;
   * `metadata.close_cancelled` gets one record appended: `{at, by, sub_state, reason_was, attempts, last_error, venue_said, hold_until}`;
   * these keys are popped: `close_retry_attempts`, `close_retry_last_error`, `close_retry_last_at`, `close_blocked_since`, `close_blocked_at`, `close_blocked_why`, `close_blocked_passes`, `close_blocked_logged_at`, `close_blocked_alerted`, `close_session_busy_*`, `close_order_working` (set False), `close_working_order_id` (set ""), `close_sent_at`, `venue_miss`, `close_cancel_requested`, `close_intent`;
   * `metadata.close_hold` is written when the family is holdable (§3.4);
   * `reason` gets `| close cancelled by <user>` appended; the `close-failed:<R>` tag stays as history;
   * `protected` and `protection_stripped` are left exactly as they are. A stripped row stays `protected=False`, so the bot-side SL manages it, and the manager check guarantees something runs that SL. The dialog says "no stop rests at the venue for this position" in red, and the success message repeats it.
9. Release the claim in a `finally`, as `execute_close` does (:573).
10. **After the write**, each step fenced so that none can undo the write:
    * `audit.record_event("close_cancelled", {...}, user=)` (`bot_program/audit.py:36`);
    * `push_eye_event(user, "close_pending", {"trade_id", "cancelled": True})`, which retires the red banner (the shape is at `pending_closes.py:1484-1491`);
    * a Telegram note: "Close of SELL 0.5 GBPJPY cancelled by you. The position stays open; its stop at eToro is 191.20" (or "no stop rests at the venue");
    * the Orc journal fact `hand: close cancelled` (`bot_program/orcs/observe.py`), only while `orcs` is ON.

`preview_close` (`manual_close.py:318-334`) keeps its RETRY answer and adds a `cancel` block:
```
{"can": bool, "sub_state", "words", "reason_was", "managed_after": bool, "manager_words",
 "hold": {"default_h", "choices_h", "family", "words"},
 "stop_at_venue": price|None, "protected": bool, "requires_pin": True}
```
The dialog reads that one payload.

**New endpoints**, beside the close pair (`dashboard/urls.py:204-205`); both are POST and PIN-checked in the view:
* `positions/<int:trade_id>/close/cancel/preview/`: `views_close.close_cancel_preview`, no PIN.
* `positions/<int:trade_id>/close/cancel/`: `views_close.close_cancel_execute`, door ACT. The body carries `hold_hours`.

The STOP close endpoint (`views_close.py:107-136`) stays unchanged: the cancel needs its own endpoint because its door is a different class.

### 3.3a eToro's close that times out after the send is in doubt (P1a, first commit)

`EtoroTrader.close_position` (`etoro_client.py:2754`; the bare POST at :2802-2806) gets the NEVER_SENT / after-send split that `market_order` has (:2454-2462).
* An error before the request left (the name lookup, a refused connect, the local guard) stays a plain error, booked as today.
* A read timeout or a reset after the send raises `EtoroOrderInDoubt` (:740-757), with `in_doubt=True` and the position id as its reference.
* The close paths already record that flag as `close_in_doubt` (`base.py:3299-3311`, :3586-3600), and every reader already refuses that sub-state.

Tests: `test_close_position_read_timeout_raises_in_doubt`, `test_close_position_connect_error_is_never_sent`, `test_bot_close_timeout_books_close_in_doubt`. The "Retrying after a transport failure" refusal (§3.2) covers rows written before this commit, and stays.

### 3.4 The exit hold (`bot_program/close_hold.py`)

Without a hold, the same rule re-sends a cancelled TIME, care or TP close within five minutes (`map_path.md` §10.5).

**Shape:** `metadata.close_hold = {until, by, family, reason, why}`.

**The close's intent.** It is written where the close starts.
* `_close_trade` (`base.py:3463`) gets a keyword `intent=None` and does `metadata.setdefault("close_intent", {family, reason, exit, at})` before the first send (step 4, :3576).
* The care passes `intent=decision["care"].get("exit")` ("weekend cut", "event cut", "no progress", or the soft stop's why) at `position_care.py:753`.
* **The kill switch** does not close through `_close_trade`. `kill_switch._close_asset_trade` (:518) therefore writes `metadata["close_intent"] = {"family": "KILL", "at", "by", "was": <the previous intent or None>}` on every row it leaves CLOSE_PENDING, the queued write at :794-811 included. This is an overwrite, not a `setdefault`: the kill is the latest decision to close.
* An old row with no intent falls back to the `close-failed:<R>` tag (`base.py:3670`).

| Family | Comes from | Hold? | Hold length |
|---|---|---|---|
| MANUAL | the CLOSE button | none needed | n/a |
| TIME | `_time_stop_hit` (`base.py:1206`) | yes | the operator picks 4 h, 24 h (default) or 72 h; when the hold ends, the time stop applies again, and the dialog says so |
| TIME / no progress | care (`position_care.py:579`) | yes | same choices |
| TP | bot-side target (`base.py:1435-1450`) | yes | until the hold ends, or until the operator edits the target |
| SL / weekend cut | care (:551) | yes | **at least until the market reopens plus `OPEN_SETTLE_MINUTES`**. A 24 h hold from Friday evening would expire on Saturday and queue a close at eToro again |
| SL / event cut | care (:556) | yes | at least until the event window ends (`event_for`) |
| SL (stop crossed), SL / soft stop, trail, break-even | bot-side SL, care soft stop | **never** | refused while crossed (§3.2) |
| KILL, EXPIRY_CLOSE | the kill switch, the options expiry | not cancellable | n/a |

**Where it is read:** `close_hold.blocks(trade, family, now) -> bool`, checked in three places:
* in `manage_positions`, before the time stop (`base.py:1206`);
* around the care's close (`position_care.care` :753), only for the holdable care exits;
* before the TP close (`:1449`), for TP only.

**What a hold never suppresses:**
* the SL;
* the venue's own stop (it rests at eToro);
* `_manage_broker_stop`;
* the kill switch (`_close_asset_trade` never reads it);
* the reconcile.

**How a hold ends.** It expires by time; there is no beat for it. The operator can also lift it with "Release hold" on the forensics page, which needs no PIN because it adds no risk.

### 3.5 eToro's accepted close

**What is known, and the words.** `close_order_working` on an eToro row means that eToro accepted the close and the platform could not prove it executed within `close_position`'s budget (5 attempts of 2 s, `etoro_client.py:345-357`; `pending_closes.py:483-485`, with eToro's "PENDING" non-terminal at :154-157).
* That covers a market that is shut, and also an in-session close behind 500s or a 429 (the lookups answered 500 three times during one close, :348-357).
* The platform has no clock of eToro's own sessions. `core/exchange_status.py` keeps the exchanges' clocks, and `entry_timing.py:96-108` notes that a broker's index CFD "trades nearly round the clock".
* So the words say only what is known, and they give no eToro opening time until a measured eToro-session source exists (M14):
  * The dialog says: "eToro accepted this close and has not confirmed it. If TSLA's market is shut, eToro executes it at its next open. The exchange opens Mon 2 Nov 14:30 UTC (the exchange's clock; eToro may open earlier). The platform cannot cancel it, and it cannot yet read eToro's close orders."
  * `manual_close.py:588-593`: "rejected" becomes "eToro accepted the close and has not confirmed it; if the market is shut it executes at eToro's next open".
  * `base.py:3854-3890`: "filled only 0 of N" becomes "accepted at eToro, not confirmed".
  * `kill_switch.py:675-680`: "needs closing by hand" becomes "accepted at eToro, not confirmed; if the market is shut it executes at eToro's next open".

**Why the position read cannot return a row to OPEN.** `position_state` reads "open" in three cases: the close was cancelled, the close is still queued, and the close was accepted and never executed. The code says so: "'open' is a reading, not a proof" (`etoro_client.py:2320-2321`). A close carrying `UnitsToDeduct` was once "ACCEPTED ... and NEVER executed - the position stayed open" (`etoro_client.py:2788-2799`, `ETORO_DEPARTURE.md:641-649`). Booking OPEN on that read would show OPEN while a live close may still sit at eToro. That is the lie this codebase forbids.

**P1a: "I cancelled it at eToro" records a claim, and nothing else.**
* The row's button is **CANCEL AT ETORO…** while P1b is off. The dialog shows the words above, then: "To keep the position, cancel the close in eToro's app, then tell the platform here."
* Its buttons are KEEP THE CLOSE (dismiss) and **I CANCELLED IT AT ETORO** (ACT).
* It writes `metadata.close_cancel_requested = {at, by, via: "hand at eToro"}` and nothing else.
* The row stays CLOSE_PENDING and the drain keeps blocking: it never stacks a second close (`pending_closes.py:1705-1709`). Nothing returns the row to OPEN in P1a.
* The row's line reads: "you said you cancelled it at eToro (Sat 18:40 UTC) · the platform cannot read eToro's close orders yet, so the row stays CLOSE QUEUED".
* When a venue read says the position is closed, the row books CLOSED as today (`_finalise_flat`), with the note "eToro executed the close; the hand cancel did not happen or came too late".
* **After the exchange open plus 30 minutes**, on the exchange's clock and stated as such, if eToro still reads the position open, two things happen once per row:
  * the operator gets one Telegram note and one line on the row: "eToro still shows TSLA open. The platform cannot see whether the close order is gone. The row stays CLOSE QUEUED until eToro's close-order read is measured. Close it at eToro yourself if you no longer want it";
  * staff get one alert, the same one sent when no hand cancel was asked: "eToro's accepted close of X did not execute after the open; the position is still open there".

  Neither moves money, and neither stacks a second close.

**P1b: after M7 (extended) and M8, with `etoro_close_cancel_live` ON.**
* `EtoroTrader.close_order_state(close_order_id) -> "pending" | "cancelled" | "executed" | None` reads `GET /api/v1/trading/info/{demo|real}/close-orders/{id}` and the raw `/portfolio` `ordersForClose[]`. The spelling and the states are M7's. Its real path gets its own `_V1_INFO_REAL_SEG` entry.
* `EtoroTrader.cancel_close_order(close_order_id, open_order_id) -> True | False | None` sends `DELETE /api/v1/trading/execution/{demo/}market-close-orders/{id}`.
  * **It has its own attestation entry, keyed by method and tail.** `_seg` attests by the first path segment only (`etoro_client.py:1142-1188`), and `market-close-orders` was measured for the POST and a GET 405, never a DELETE.
  * Until M8's entry exists, the call raises on the real account, whatever the switch says.
* **The one rule for OPEN.** It applies to the platform's DELETE and to a hand cancel alike: the close-order read says cancelled (or `ordersForClose` no longer lists the position, if M7 shows that is the sign), **and** `position_state` says "open". The drain applies this rule on each pass, and no clock decides.
  * The DELETE answers True only when both reads agree; the verb then runs the §3.3 write. A 200 alone is never the proof.
  * False means nothing was cancelled: the verb refuses and nothing changes.
  * None means sent and unread: it sets `close_cancel_in_doubt`, and the dialog says "the cancel was sent and could not be proven; the close may still execute at the open". The drain keeps blocking and applies the one rule on each pass.
  * A hand-cancelled row (`close_cancel_requested`) is finished by the same rule through `finish_hand_cancel`, once P1b ships.
* **The race at the open.** A cancel sent in the seconds the market opens may arrive after the close executed. The close-order read decides, never the DELETE's answer (`map_venue` §7).
* **Support for these reads is thin.** `etoro-go` v0.1.1 has `CloseOrderInfo` (`trading.go:418-427`) and `OrderForClose` (:531-543). `etoropy` 0.1.7 types `ordersForClose` as `list[Any]` and has no close-order read. Neither client has met our key.

### 3.6 Withdrawing a working entry, and the pending-close dialog

**Withdraw: the label fixes.** The verb exists (`cancel_working_entry`, `base.py:155-298`) and its door is STOP. P1 only makes the surfaces say what it is:
* `templates/base.html` `closeFlow` (:3011-3109) reads `p.action === "withdraw"`, as `forensics_detail.html:516` does:
  * title "Withdraw this order?";
  * message "Nothing has filled at the broker; this cancels the order and its protective legs. No position opens and nothing is graded.";
  * facts without "Mark now", "Books at" or "Realises";
  * confirm label "WITHDRAW ORDER".
* `positions_list.html:390` and `_eye_body.html:130` show WITHDRAW for a row with `entry_working`.
* `notifications.fill_queued_message` (:1280-1311) gets a second button, "Withdraw order", with the same close-dialog URL. **`tests/test_telegram_links.py:419` pins its absence today and must be changed on purpose in the same commit.**
* The bot's own working entry gets the same queued message (today it only logs, `base.py:6668-6671`).

**The pending-close dialog is its own builder in `closeFlow`, as `sizeDialog` is.** It is not an `ask()` call, because `ask()` renders no choice control (`sv-overlay.js:480-540`). `ask()` is left unchanged; the earlier draft's `opts.alt` is dropped. The dialog has two views:
* **The RETRY view.**
  * The facts: what asked the close, the attempts and the last refusal, "At the broker: STILL OPEN (eToro's read, hh:mm UTC)", and the stop at the venue.
  * A PIN box.
  * The foot: KEEP TRYING and **RETRY CLOSE** (STOP door).
  * Under the facts, a link: "Keep the position instead…". It is present only when `cancel.can`; otherwise the cancel block's words stand in its place.
* **The CANCEL view**, reached by that link, or opened directly by the row's CANCEL CLOSE.
  * The warning CANCELLING KEEPS THE POSITION.
  * The hold choice: segments 40 px tall, with the moment the hold ends.
  * "No stop rests at the venue" in red when the row is stripped.
  * **Its own PIN box**, empty on entry: the RETRY view's PIN never carries over.
  * The foot: BACK and **CANCEL CLOSE** (ACT door).
  * Focus lands on BACK, never on CANCEL CLOSE. That is the platform's rule ("The dangerous button is never the one focus lands on", `sv-overlay.js:586-589`).
* The chosen hours are posted as `hold_hours`. A test pins that the value chosen in the dialog reaches `cancel_pending_close`.
* Two opposite money acts never share a foot or a PIN box, so a slip of a few pixels on a phone cannot send the opposite act.

### 3.7 Races

| Racer | How it is excluded |
|---|---|
| The 5-minute drain (`retry_all_pending_closes` :1926) | Same claim. `_claim_for_retry` (:1877) returns None while the cancel holds it. After the cancel the status is OPEN, and the drain filters CLOSE_PENDING (:1941-1943) |
| The CLOSE / RETRY button | Same claim (`_claim` :417) |
| The kill switch | It honours the claim (`kill_switch.py:571-578`). A kill switch that fires during a cancel names the row in `errors` and says "press again". It disables the configs first (:86-108), so the re-read manager check at step 8 refuses the cancel. Rows it leaves CLOSE_PENDING carry `close_intent` KILL and cannot be cancelled |
| The reconcile (`_claim_orphan` `reconcile_asset.py:501`) | Same claim |
| The tick (`manage_positions` walks OPEN, `base.py:1084`) | The row is CLOSE_PENDING until the write, so the tick never sees it in between. After the write, the hold decides what the tick may do |
| Claim TTL 120 s | The venue reads are at most three GETs. A cancel that runs past the TTL aborts before the write: the write re-checks that the claim stamp is its own |
| Two cancels (double click) | The second meets the held claim and refuses |

### 3.8 Files and functions (P1)

| File | Change |
|---|---|
| `bot_program/engine/etoro_client.py` | P1a: `close_position` raises `EtoroOrderInDoubt` after the send (§3.3a). P1b: `close_order_state`, `cancel_close_order`, the `_V1_INFO_REAL_SEG` entry, and the DELETE's own attestation entry keyed by method and tail |
| `bot_program/close_cancel.py` (new) | `preview_cancel`, `cancel_pending_close`, `request_hand_cancel`, `finish_hand_cancel` (P1b), `_sub_state(trade)`, `_manager_refusal(trade)` |
| `bot_program/close_hold.py` (new) | `FAMILIES`, `family_of(trade)`, `hold_until(family, choice_h, trade, now)`, `blocks(trade, family, now)`, `release(trade, by)` |
| `bot_program/asset_engine/base.py` | `_close_trade(..., intent=None)` writes `close_intent`; hold checks at :1206 and :1449; the queued message for a bot's working entry (:6668); words at :3854-3890 |
| `bot_program/position_care.py` | passes `intent=` at :753; the hold check for holdable care exits |
| `bot_program/pending_closes.py` | the hand-claim branch next to :1718 (P1a: books CLOSED on a flat read, sends the after-open note once; P1b: the one rule for OPEN) |
| `bot_program/manual_close.py` | `preview_close` adds the `cancel` block; words at :588-593 |
| `bot_program/engine/kill_switch.py` | `_close_asset_trade` stamps `close_intent` KILL (and at :794-811); words at :675-680 |
| `dashboard/views_close.py`, `dashboard/urls.py` | the two endpoints; the dialog payload; `hold_hours` |
| `templates/base.html` (`closeFlow`) | the two-view pending-close dialog; the withdraw words |
| `templates/dashboard/positions_list.html`, `_eye_body.html`, `forensics_detail.html` | CANCEL CLOSE, CANCEL AT ETORO…, WITHDRAW, the hold line on the row ("time stop held until 14:05 UTC"), the hand-claim line |
| `bot_program/notifications.py` | button labels; the cancelled note; the after-open note |
| `core/platform_control.py` (P1b) | `etoro_close_cancel_live` in `DEFAULT_COMPONENTS` and `LIVE_MONEY_SWITCHES` |

### 3.9 Data (P1)

No migration. Everything is in `AssetBotTrade.metadata`:
* `close_intent` (now with `family`, KILL included), `close_cancelled` (a list), `close_hold`, `close_cancel_requested`, `close_cancel_in_doubt`, `close_hand_note_sent`;
* `close_cancel_requested` and `close_cancel_in_doubt` are popped on any terminal outcome.

### 3.10 States and transitions (P1)

```
CLOSE_PENDING (retrying after a refusal, market open) --cancel, venue says held, no resting close,
        managed afterwards, PIN ACT--> OPEN (+close_hold if holdable)
CLOSE_PENDING (retrying after a transport failure | eToro and market shut) --cancel--> unchanged (in doubt)
CLOSE_PENDING (any) --cancel; nothing would manage it | KILL | expiry | stop crossed--> unchanged
CLOSE_PENDING (retrying) --cancel, venue flat/unreadable/lag--> unchanged (refusal)
CLOSE_PENDING (working, Alpaca/Saxo/IBKR) --cancel proven, 0 filled--> OPEN
CLOSE_PENDING (accepted at eToro) --"I cancelled it at eToro" (ACT)--> CLOSE_PENDING + close_cancel_requested
    --drain: position read closed--> CLOSED (as today)
    --P1a: nothing more; after the open + 30 min, still open: one note, one staff alert
    --P1b: close-order read cancelled AND position open--> OPEN
CLOSE_PENDING (accepted at eToro) --P1b DELETE, both reads agree--> OPEN
                                  --P1b DELETE unproven--> CLOSE_PENDING + close_cancel_in_doubt
                                        --drain, the one rule--> OPEN | CLOSED | unchanged
CLOSE_PENDING (partial | in doubt) --cancel--> unchanged (refusal)
OPEN + close_hold --until passes--> OPEN (hold expired, rules apply again)
OPEN (entry_working) --WITHDRAW, PIN STOP--> CANCELED (as today)
```

### 3.11 Switch (P1)

* P1a has no switch. It is a per-row act by the operator with the PIN, like the CLOSE button, and it automates nothing.
* P1b: `etoro_close_cancel_live`, OFF on arrival, in `LIVE_MONEY_SWITCHES`. Description (263 characters): "Off (default): a close eToro accepted and has not confirmed can only be cancelled in eToro's app. On: CANCEL CLOSE sends eToro's cancel; a row returns to OPEN only when eToro's close-order read says cancelled and its position read says open. Flip after M7 and M8."

### 3.12 Tests to write first (P1)

`tests/test_etoro_close_in_doubt.py` (first commit)
* `test_close_position_read_timeout_raises_in_doubt`
* `test_close_position_connect_error_is_never_sent`
* `test_bot_close_timeout_books_close_in_doubt`

`tests/test_cancel_pending_close.py`
* `test_retrying_row_held_at_venue_returns_open_and_archives_retry_keys`
* `test_retrying_row_flat_at_venue_is_refused_and_unchanged`
* `test_unreadable_venue_or_lag_window_refuses`
* `test_retrying_after_timeout_is_treated_as_in_doubt`
* `test_etoro_retrying_row_refused_while_market_shut`
* `test_resting_close_listed_at_alpaca_refuses`
* `test_working_close_at_alpaca_cancelled_and_zero_filled_returns_open`
* `test_working_close_cancel_unconfirmed_refuses`
* `test_partial_close_is_never_cancellable`
* `test_close_in_doubt_is_never_cancellable`
* `test_abandoned_error_row_offers_no_cancel`
* `test_mark_through_stop_refuses_move_the_stop_first`
* `test_cancel_refused_on_kill_switched_config`
* `test_cancel_refused_on_hand_stopped_config`, and `test_cancel_allowed_on_braked_config_that_keeps_managing`
* `test_cancel_refused_when_tick_off`
* `test_manager_rechecked_before_write`: the config is disabled between the venue read and the write, so nothing is written
* `test_kill_switch_pending_row_carries_kill_intent`, and `test_kill_intent_refuses_cancel`
* `test_expiry_close_refuses`
* `test_protection_stripped_row_returns_open_unprotected_with_words`
* `test_pin_door_is_act`: no PIN changes nothing; wrong PINs count on the ACT counter; the fifth ends the session; a spent counter refuses before any read
* `test_claim_held_by_drain_refuses`, and `test_drain_skips_row_while_cancel_holds_claim`
* `test_claim_expired_mid_cancel_aborts_before_write`
* `test_audit_eye_push_and_telegram_after_write_only`
* `test_dialog_hold_hours_reach_the_verb`

`tests/test_close_hold.py`
* `test_time_stop_held_until_until`, `test_tp_held`, `test_weekend_cut_hold_runs_past_the_reopen`
* `test_hold_never_suppresses_sl_or_venue_stop_or_kill_switch`
* `test_hold_expires_and_rule_applies_again`
* `test_close_intent_written_once_before_the_send`

`tests/test_etoro_queued_close.py`
* `test_accepted_close_cancel_refuses_with_known_words_while_switch_off` (no eToro opening time in the words)
* `test_hand_cancel_request_writes_only_the_marker`
* `test_hand_cancel_never_books_open_in_p1a`: the venue reads "open" after the open, and the row stays CLOSE_PENDING
* `test_drain_books_closed_when_venue_closed_despite_request`
* `test_after_open_note_and_alert_once_and_send_nothing`
* (P1b) `test_open_needs_close_order_cancelled_and_position_open`, `test_200_alone_is_not_proof`, `test_none_sets_in_doubt_and_drain_applies_the_rule`, `test_close_order_pending_keeps_row_pending`, `test_cancel_close_order_paths_per_world`, `test_delete_on_real_raises_without_attestation_whatever_the_switch`

`tests/test_working_entries.py` (extend)
* `test_close_dialog_reads_withdraw_action`
* `test_row_label_withdraw_for_entry_working`

`tests/test_telegram_links.py` (change on purpose)
* `test_fill_queued_message_carries_withdraw_button_url_only`
* `test_pending_close_button_label`

### 3.13 What a screenshot must show (P1)

1. A CLOSE_PENDING row with RETRY CLOSE and CANCEL CLOSE side by side.
2. The dialog's RETRY view: what asked the close, the attempts and the last refusal, "At the broker: STILL OPEN", the stop at the venue, one PIN box, KEEP TRYING and RETRY CLOSE, and the link "Keep the position instead…".
3. The CANCEL view: the warning, the hold choice (40 px segments), its own empty PIN box, BACK and CANCEL CLOSE.
4. The eToro accepted-close dialog with the known words (the exchange's clock, named as such), KEEP THE CLOSE and I CANCELLED IT AT ETORO.
5. The queued row after a hand claim, with its line, and the row's button reading CANCEL AT ETORO….
6. A working entry row reading WITHDRAW, and its dialog "Withdraw this order?" with no mark or P&L facts.
7. The row after a cancel: OPEN, with the line "time stop held until ...".

---

## 4. Why P2 is built in this order

The platform-held order comes first because it is the one shape that is fully under the platform's control. It works for both sides (limit and stop entry), and it can run in shadow on real money. eToro's MIT order is different on four counts:
* it covers only the better side;
* it has never met our key [U];
* it fills while nobody checks;
* it conflicts with the 26-hour withdrawal rule (`base.py:1629`).

It becomes an option (P2b) once measured.

P2a already fires orders automatically on paper and demo, so the measurements it relies on come before it, not with P2b: M9 (the request id), M11 (the quota), M12 (eToro's open orders) and M13 (eToro's rates).

---

## 5. P2: the operator's order at a price

### 5.1 What the operator sees

**The ticket's head follows the order.** Today every live ticket says "Take this trade with REAL funds?", "Executes immediately on the LIVE venue — REAL funds move at the broker..." and has the red `sv-dialog--danger` frame (`templates/base.html:2526-2551`). For a limit, a stop entry or a shadow order, those words say the opposite of what happens. This operator once took a forex position believing it was live (`deal_ticket.html:34-41`). So `_preview` builds the head on the server, as `head = {title, message, danger, success}`, and `sizeDialog` renders it. A Python test pins it:

| Order, lane | Frame | Title | Message | Success alert |
|---|---|---|---|---|
| Market, live lane | red, as today | "Take this trade with REAL funds?" (today) | today's | today's |
| Limit or stop, live lane, mode live | red | "Place a BUY LIMIT with REAL funds?" | "Nothing is sent now. When eToro's ask reaches 96,520, the platform sends a market order through your bots' gates, at worst 96,533. You can cancel it until then." | "Order placed: BUY LIMIT BTCUSD 96,520, armed. Nothing has been sent." |
| Limit or stop, live lane, mode shadow | **none** | "Arm in shadow (nothing will send)" | "Real-money orders at a price are off. This order is watched and graded against a market order. It will never send, even if the switch is turned on later." | "Armed in shadow; it will not send." |
| Limit or stop, eToro DEMO | red, as a live ticket is today | "Place a BUY LIMIT on eToro DEMO?" | "Nothing is sent now. When eToro's demo ask reaches 96,520, the platform sends a demo market order through your bots' gates." | "Demo order placed, armed." |
| Limit or stop, paper lane | none | "Place a BUY LIMIT (paper)?" | "Nothing is sent now. When the paper price touches 96,520, the paper venue fills it." | "Paper order placed." |

**The ORDER block**, a new first block on the TAKE TRADE ticket (`sizeDialog`, `templates/base.html:1931`), in the panel's own idiom (`.sz-block`, `sauron.css:6324`):
* **A segmented control: MARKET | LIMIT · ON TOUCH | STOP ENTRY.**
  * Every opening starts on MARKET, except the AT A PRICE links.
  * **With MARKET chosen, the block shows only the control.** It has no price, no expiry, no chips, no holder line and no "nobody is watching" block, and the rest of the ticket is today's. A market order takes zero extra taps; a screenshot at 390 proves it (§5.14).
* **The SHADOW line**, at the top of the block as soon as LIMIT or STOP ENTRY is chosen on a real-money lane with `price_orders_live` OFF: "SHADOW · real-money orders at a price are off: this order will be watched and graded, never sent." The head switches to the shadow row at the same moment.
* **Price.**
  * It is pre-filled with the nearest **tappable** smart price (P3) on the legal side for the chosen kind: below the ask for a buy limit, above it for a buy stop, mirrored for sells.
  * If there is none, the field is empty and required, and PLACE stays disabled.
  * Beside it: the distance from the quote in % and in 1h ATR, and which side it is on.
  * LIMIT is legal only on the better side (a buy below the ask, a sell above the bid). STOP ENTRY is legal only on the other side. A wrong side is refused with its arithmetic: "A BUY LIMIT above the ask fills at once: choose Market, or Stop entry for a breakout."
  * **Too close is refused, with its arithmetic.** That is a price nearer the quote than max(half the spread, 0.1 × 1h ATR): "96,820 is 0.02 ATR from the ask, so it would fire on the next read. Use Market."
* **Smart prices** (P3) sit directly under the price field, before everything else in the block (§6.1).
* **The kind line**, one sentence under the chips:
  * LIMIT: "Fills at the market once eToro's ask touches 96,520, at worst 96,533."
  * STOP ENTRY: "Fills at the market once eToro's ask reaches 99,350, at worst 99,450."
* **Expiry: END OF DAY | A DATE | GOOD TILL CANCELLED.** The segments are 40 px tall, and the resolved moment is shown in UTC:
  * End of day, placed while the class trades: a stock or ETF at its exchange close; forex, indices and commodities at the 17:00 New York rollover (`entry_timing.rollover` :152); crypto at 00:00 UTC.
  * **End of day, placed while the class is shut, is the end of the NEXT session**, shown with "(next session)". NVDA placed on Saturday ends Mon 2 Nov 21:00 UTC; EURUSD ends Mon 2 Nov 17:00 New York (22:00 UTC). Crypto is never shut.
  * A date: 23:59 UTC that day.
  * Good till cancelled: until cancelled, at most 30 days. The platform cancels at day 30 and says so.
* **More ▸**, a disclosure that is closed by default. Its closed line states the default: "worst price 96,533 (default)".
  * **Worst price you accept: 96,533.** The editable field is the price itself, with the offset and the R in its sub-line ("13 past your price · 0.02 R").
  * The default is 0.10 R past the price for a stop entry and 0.02 R for a limit. It is stored as `slip_cap = |worst − price|`. Past it, the order is refused and the operator is told.
* **Who holds it.** One line, always shown, naming the source the order actually watches and its real cadence (§5.5):
  * "HELD BY THE PLATFORM · it watches Binance's BTCUSD stream (seconds old) and reads eToro's own price when the stream comes near 96,520. eToro's ask decides the send. A wick shorter than a read can be missed."
  * "HELD BY THE PLATFORM · it reads eToro's own SPX500 price every 60 s. eToro's ask decides the send."
  * Or a refusal, where no source can be watched honestly: "Orders at a price on SPX500 need eToro's own price, and its read budget is full (5 symbols are already watched on it). Use Market, or cancel another order."
  * After P2b: "HELD BY ETORO: a market-if-touched order; eToro sends it at the market when touched."
* **The stop and target block** (exists, `judgeLevels` :2046) now judges the levels **against the order's price, not the mark**. The server side does the same: the wrong-side test at `manual_trade.py:1445` uses the order price when `order.kind != market`.
* **The size block** (exists). The units are fixed at placement, and the risk shown is at the order's price.
* **A warning block** (`.sz-warn`), always shown for a non-market order: "WHEN IT TRIGGERS, NOBODY IS WATCHING. At that moment it runs your bots' gates: the daily stop, the open-risk cap, the pool and pledge, the venue minimum, the entry timing, eToro's quote re-read and the venue's health. If one refuses, nothing is sent and you are told. If this lane is switched between paper, demo and real while it rests, the order is cancelled. The warnings you accept now (listed) stay accepted."
* **The button:** PLACE LIMIT ORDER, PLACE STOP ORDER or ARM IN SHADOW, with the PIN for a non-paper lane. See `mockups/ticket_1280.png`.

**On the deal ticket.** `templates/_partials/deal_ticket.html` is the same include in the instrument header and on the expanded chart's overlay (:10-11). Nothing new is crowded into the bar.
* The ticket's side is fixed when it opens (`deal_ticket.html:26-47`: each button calls `svTakeTradeAsset(symbol, 'BUY'|'SELL')`). So the bar gets two links under it: **BUY AT A PRICE** and **SELL AT A PRICE**. Each opens the dialog with that side and LIMIT selected.
* Then a one-line count, "2 working orders on BTCUSD", which links to `/orders/#sym-BTCUSD`.
* The chart-overlay copy shows the same two links and the count at the `sv-ticket--sm` size, and adds nothing else to the chart.

### 5.2 Who holds it

`price_orders.holder_for(client, inst, side, kind, world) -> "platform" | "venue"` answers "venue" only when ALL of the following hold, and "platform" otherwise:
* `kind == "limit"`;
* the adapter declares the new capability tier `price_orders: ("mit_order", "order_status", "cancel_order")` (`engine/capabilities.py:58`);
* the instrument's eligibility row says `allowMitOrders` is True (M1: whether the row carries the field is [U]);
* the trigger is on the better side of eToro's own quote at placement, on the side M4b pins;
* the world is demo, or the world is real and `etoro_mit_live` is ON.

**Before P2b, the answer is always "platform".** A platform-held order also needs a source it can watch (§5.5). Without one, the ticket refuses the order with words.

### 5.3 The data model (migration `bot_program/migrations/0046_price_orders.py`)

`bot_program/order_models.py` (new), imported in `bot_program/models.py` beside the others (:778-794):

```python
class PriceOrder(models.Model):
    SOURCES = ("operator", "bot", "program")
    KINDS = ("limit", "stop", "market")        # "market": a program's market action (P4)
    HOLDERS = ("platform", "venue")
    WORLDS = ("paper", "demo", "real")
    MODES = ("live", "shadow")
    STATES = ("ARMED", "FIRING", "WORKING", "FILLED", "REFUSED", "IN_DOUBT",
              "CANCELLED", "EXPIRED", "WOULD_FIRE")

    user          = FK(User)
    config        = FK(AssetBotConfig)          # the manual lane's config for the class, or the bot's
    source        = CharField(choices=SOURCES)
    program       = FK("OrderProgram", null=True)          # P4
    signal        = FK("signals.Signal", null=True)        # a ticket opened from a signal
    instrument    = FK(Instrument); symbol; asset_class
    side          = "BUY" | "SELL"
    kind, holder
    world         = CharField(choices=WORLDS)  # at placement; derived again at fire (§5.6) and compared
    mode          = CharField(choices=MODES)   # stored once; read only, never recomputed (§5.8)
    price         = Decimal                     # the trigger
    slip_cap      = Decimal                     # price units, adverse only: worst = price ± slip_cap
    qty           = Decimal                     # fixed at placement
    stop, target  = Decimal                     # absolute
    leverage      = PositiveSmallInteger(default=1)
    expiry_kind   = "eod" | "date" | "gtc";  expires_at = DateTimeField   # "eod" resolved, next session if shut
    watch         = JSONField(dict)             # {source, cadence_s, has_bid_ask, near_band}
    state, state_at, state_why (Text)
    history       = JSONField(list)             # [{at, from, to, why, by}]
    accepted      = JSONField(dict)             # the trade advisories the operator accepted, with their words
    placed_by, placed_at
    pin_door      = CharField                   # the door's NAME only ("act"); never the PIN, never a hash
    pin_checked_at= DateTimeField(null=True)    # when the view's _pin_ok said yes
    last_seen     = JSONField(dict)             # {price, source, age_s, at, side_of_price, etoro: {price, at}}
    holds         = JSONField(dict)             # {n, last_code, last_why, last_at}
    fire          = JSONField(dict)             # {at, quote, gates: [{gate, verdict, why}], anchor, world_now}
    fire_n        = PositiveSmallInteger(default=0)   # POSTs made for this order
    client_order_id                             # a UUID: uuid5(NS_PRICE_ORDERS, f"po{pk}:{fire_n}")
    venue_order_id
    flags         = JSONField(dict)             # {withdraw_unproven: {...}, rest_through_shut: {at, by}}
    reserved_risk = Decimal(null=True)          # risk held in the cap and the pool while IN_DOUBT or venue-held
    trade         = FK(AssetBotTrade, null=True)  # the row once sent (WORKING or a position)
    baseline      = JSONField(dict)             # the market entry it is graded against: {at, price, stop_r, target_r}
    grade         = JSONField(dict)             # {r_order, r_market, value_r, graded_at, note}
    created_at, updated_at
    class Meta: indexes on (state, holder), (user, state), (config, symbol, state), (user, world, state)
```

**What a PriceOrder is not.** Before it fires, it is not an `AssetBotTrade`. An ARMED platform-held order does not occupy `ALREADY_OPEN`, the open-risk budget or the concurrency count, because nothing is held anywhere (`map_path.md` §9c). Everything is judged at fire.

**Two exceptions reserve from the moment they exist:**
* **A venue-held order** is also booked at placement as the existing WORKING row: `OPEN` + `entry_working` + a new `entry_order{kind, price, good_till, price_order_id}`. Every reader that counts working rows then keeps working unchanged (`map_path.md` §9b), and eToro's frozen cash is counted.
* **An IN_DOUBT order** may exist at eToro, so its risk is held (`reserved_risk`, §5.6a).

`price_orders.reserved_risk(user, world)` returns the sum. It is read by `risk_gate`'s open-risk state and by both lanes' headroom.

### 5.4 Gates at fire: two groups, judged by one pure function

At placement, the ticket shows the manual lane's advisories exactly as today (`manual_trade.py:1034`, `:1061`, `:420`, `:1017`, `:1146`, `book_advisory`, `concentration`, `theme`). The operator may accept them with the PIN; `accepted` stores which ones and their words.

At fire, nobody is there to accept a new warning:

| Group | Gates | At fire |
|---|---|---|
| **About the trade**: may be accepted at placement | the rule's proof advisory, reward:risk / cost filter, no Sauron signal behind it, setup memory, concentration ceiling, currency theme | Allowed if accepted at placement and its verdict is not worse; **refused if new** |
| **About the book and the moment**: never carried over | the order's world and the lane's mode; the daily stop; the open-risk cap; the pool and pledge headroom; the venue minimum and fraction; the eToro class gate (`_etoro_entry_refusal`); leverage on the instrument's live list; the entry timing; quote sanity and the last look (`fail_closed=True`, anchored on the order price); venue health; an in-doubt note on the symbol; the duplicate check (`manual_trade.py:2050-2092`); the program's one-live-idea rule (§7.3) | Re-judged at fire. A refusal is a **HOLD** (transient; the order stays ARMED), a **BLOCK** (terminal; REFUSED, with words) or a **CANCEL** (the order's own premise is gone) |

**`price_orders.judge(order, ctx) -> [{gate, verdict: PASS|HOLD|BLOCK|CANCEL, why}]`** is a pure function. It reads the book, the clock, the quote and the notes, and never writes or calls a client. `fire()` calls it before `_execute`, and `_execute` still runs its own gates. The shadow path calls only `judge()`, records the verdicts on WOULD_FIRE, and never reaches `_execute` (§5.8).

**HOLD** (the order stays ARMED, `holds` counted, re-judged on the next pass on the then-current price):
* venue health sick, or the 429 pause;
* **an unreadable book**: `preflight` returned `failed_open` (`risk_gate.py:1979`, :2016), or the open-risk state, the pool, the pledge or the in-doubt note could not be read. A fail-open answer is a pass at the ticket, where the operator sees the warning; at fire, nobody sees it, so it is a HOLD;
* timing: SHUT, the rollover, the opening quarter hour, an event window;
* **an unreadable clock or calendar.** `entry_timing.verdict(..., fail_closed=True)` is a new keyword; it turns "an unreadable clock refuses nothing" (:312, :375, :508-530) into a HOLD with the code `clock_unread`;
* **eToro's own quote** too old (its row's time more than 30 s old), with a non-positive bid or ask, or the first eToro print after a gap of more than 15 minutes;
* eToro answered WaitingForMarket and the withdrawal was proven (§5.6);
* the shared eToro budget is spent (§9);
* NEVER_SENT: the request did not leave.

**BLOCK** (REFUSED, with words to the operator):
* the daily stop or the open-risk cap reached;
* the pool or pledge short;
* under the venue floor;
* the class unticked, or its proof withdrawn;
* past the worst price;
* an in-doubt note on the symbol;
* a duplicate within 60 s;
* a new trade advisory.

**CANCEL** (CANCELLED, with words, nothing sent):
* the world or the lane's mode changed since placement;
* the config stopped (a hand stop, the kill switch, a brake);
* a `_live` switch that allowed it is now OFF;
* a bot order's signal is gone (§8.3).

### 5.5 The watcher: one scheduled task

`bot_program.tasks.watch_price_orders`, beat entry `watch-price-orders` every 60 s (`config/celery.py`, beside `tick-asset-bots` :449), with `options {"expires": 55, "expire_seconds": 55}` and `@guarded_task("price_orders")` (`core/task_gate.py:88`).
* **One pass at a time.** A cache `add` lock with a 55 s TTL, as `tick_all_asset_bots` holds its pass lock.

Each pass, `price_orders.watch(now)`:
1. **Expiry.** ARMED orders past `expires_at` become EXPIRED (no venue act). Venue-held orders past `good_till` go through `cancel_working_entry` (`base.py:155`). An unproven cancel stays WORKING and is alerted daily; it is never booked as expired (`map_venue` §4).
2. **Standing gates** on every ARMED order. A failure CANCELs the order, with words:
   * the config is still enabled;
   * the manual lane is still armed for the class (live), or the bot is still armed;
   * the eToro class gate is still open;
   * **the world**, derived again (`price_orders.world_now(order)`, the same function the fire uses, §5.6 step 2), equals the order's world;
   * **the switches.** A mode-live order in the real world needs `price_orders_live` ON. A program's order needs `order_programs_live` ON in every world, and a bot's order needs `bot_entry_levels_live` ON in every world. A switch turned OFF while orders rest cancels them with words, such as "real-money orders at a price were turned off".
3. **The price source, per class** (`price_orders.watch_source(symbol, asset_class, world)`, stored on the order at placement and re-checked each pass). `LiveQuote` alone is not eToro's price, and for most classes it is not fresh:
   * the beat refreshes forex every 600 s, commodities every 300 s and indices every 300 s (`config/celery.py:216-226`);
   * the index quote is Yahoo's cash index, `^GSPC` (`market_data/public_feed.py:50,64`), described as "measurement" (`market_data/tasks.py:371-400`), and it is re-stamped fresh while any market is open;
   * the commodity quote is Yahoo's front future, `GC=F`, off eToro by a basis;
   * most writers store no bid or ask (`quotes.write_quote`; only `stream_oanda`, `stream_binance` and `ibkr` pass them).

   So the watcher picks a source per class:

   | Class | Watches | Fresh when | Who decides the send |
   |---|---|---|---|
   | crypto | the `binance_ws` stream (bid/ask) | ≤ 10 s | eToro's re-read (§5.6) |
   | forex with OANDA streaming | the `oanda_stream` (bid/ask) | ≤ 10 s | eToro's re-read |
   | forex without OANDA, index, commodity | **eToro's own rates**, never Yahoo's | the eToro row's time ≤ 60 s | eToro's read itself |
   | stock, ETF in session | `finnhub_ws` trades (last only) | ≤ 15 s | eToro's re-read |
   | stock, ETF off session | nothing (the timing gate HOLDs) | n/a | n/a |

   * **The near band.** When a feed-watched order's feed price comes within max(2 spreads, 0.05 × 1h ATR) of the trigger, the watcher reads eToro's own price on that pass too, within the budget. A basis between the feed and eToro then cannot hide a touch that only eToro saw.
   * **eToro's reads.** If M13 shows that the comma form works and counts as one request, one GET per pass reads every eToro-watched symbol (up to the measured row cap). If not, the watcher makes one GET per symbol, and at most W symbols are eToro-watched at once. W comes from M13 and the fleet's `wire_reads`, inside the shared budget (§9). The two community clients disagree on the comma form (`etoro-go` `market.go:181-186` sends it; `etoropy` says it "causes 500"). Until M13 is pinned, W = 3, read one symbol per GET. A symbol past W is refused at placement with words (§5.1).
   * A source older than its freshness limit triggers nothing; the order's `last_seen` says "no fresh price since hh:mm (source)".
   * Shadow orders watch the same source a live one would, so the shadow is an honest rehearsal. When the budget is short, their eToro reads are skipped first.
4. **The trigger:**
   * buy limit: `ask <= price`;
   * buy stop: `ask >= price`;
   * mirrored for sells. With no bid or ask (a `finnhub_ws` trade), `last` only triggers a look, and eToro's re-read decides.
5. **Fire** (§5.6), one order at a time, each taking a token from the shared eToro budget (§9). Each send is one POST plus up to five lookups. Over the budget is a HOLD ("queued behind other orders"), re-judged on the next pass on the new price. Entry senders cannot spend the budget's reserve, which is kept for closes, close proofs and the kill switch. That keeps headroom for protective closes; it is not a guarantee, because whether eToro counts all of these in one quota group is M11's question.
6. **Paper orders** use a touch model: the stored bars since `last_seen.at` (the bar replay `bot_program/paper_exits.py` uses; `MODEL_BAR_REPLAY` :133):
   * a limit fills at its price, or at the bar's open if the bar gapped through it in the order's favour;
   * a stop fills at the worse of the trigger and the bar's open;
   * paper books synchronously (`manual_trade.py:2596`).

   The paper row says "filled on the touch (modelled)", because real platform-held orders fire on a read, and a wick can be missed.

### 5.6 The fire

`price_orders.fire(order_pk)`, in order:
1. **Claim.** Under `select_for_update`, the state must be ARMED and `expires_at > now`. Set FIRING and `fire.at`, then commit. A second process meets FIRING and stops. **Every later outcome is written by compare-and-set from FIRING** (`filter(pk=, state="FIRING").update(...)`). Zero rows updated means something else moved the order: that is logged and alerted, and never overwritten.
2. **The world and the mode, derived again.** `price_orders.world_now(order)` reads the client the router gives the config now (`AssetBot.rehearsal_client` :7580 and `venue_stamps` :6761: demo or real; PaperTrader: paper) and the config's current mode.
   * A mismatch with `order.world` means CANCELLED, with nothing sent: "This order was placed on eToro DEMO and the lane now routes to the REAL account: it was cancelled and nothing was sent."
   * Next, `config.enabled` and `disarm.record_of(config)` are re-read. A config the kill switch or a hand stopped means CANCELLED.
3. **`judge()`** (§5.4), fail-closed. HOLD returns the order to ARMED, BLOCK makes it REFUSED, and CANCEL makes it CANCELLED.
4. **eToro's own re-read**, through the trade client (`_last_look`'s read):
   * the condition must hold on eToro's quote, with a positive bid and ask (`ticker` returns "0.0" when the row carries only `lastExecution`, `etoro_client.py:1515-1542`);
   * the row's time must be ≤ 30 s old;
   * it must not be the first eToro print after a gap of more than 15 minutes. The watcher's stored eToro reads (`last_seen.etoro`) or the feed's last print show the gap. The rule holds whatever the class, so an index CFD's break, a venue holiday or eToro's own shut cannot be fired into;
   * the adverse distance past the price must be inside `slip_cap` (the worst price).

   The outcomes:
   * not touched at eToro: back to ARMED ("the feed touched, eToro did not");
   * stale, unreadable, or a gap: HOLD;
   * past the worst price: REFUSED ("the market ran past your worst price: ask 96,560, worst 96,533").
5. **Right before the POST.** `config.enabled` and the kill record are re-read once more; the kill switch disables configs first (`kill_switch.py:86-108`). A budget token is taken. Then `fire_n += 1` is saved and the order is sent through the one path, `manual_trade._execute(user, inst, side, ..., at_fire=order)`:
   * qty, stop, target and leverage come from the order, with `close_ids=[]`: a fired order never funds itself by closing anything;
   * every gate of §5.4 runs as described, with the advisories through `at_fire.accepted`;
   * the last look runs with `fail_closed=True` and `anchor=order.price` (the drift rule measured from the order's price, `base.py:5098`);
   * the cache claim `manual_open:{cfg}:{sym}:{side}` (:2612) works as today;
   * **`pin_ok` is passed only when `world_now` equals `order.world` and `order.pin_door == "act"`.** The door was checked at placement, and the PIN itself is not stored;
   * **the request id.** `client_order_id = str(uuid5(NS_PRICE_ORDERS, f"po{order.pk}:{order.fire_n}"))` is a UUID, so `EtoroTrader._rid` keeps it and sends it as `x-request-id` (`etoro_client.py:957-968`). `idempotency.make_client_order_id` returns "sv-<28 hex>" (`engine/idempotency.py:10-19`), which is not a UUID, so today it is discarded for a fresh `uuid4`. The id changes with `fire_n`, so a re-fire after a HOLD is never taken by eToro as a repeat of the earlier attempt. Whether eToro honours the id as an idempotency key is M9's question.
6. **Map the outcome**, each one written by compare-and-set from FIRING:
   * **filled**: FILLED, with `trade` set.
   * **eToro held it (WaitingForMarket, status 11).** This is not an accepted outcome. It would fill at the reopen price, past every gate nobody re-ran. The order is withdrawn at once through `cancel_working_entry` (`base.py:155`), which calls `EtoroTrader.cancel_order`, measured for this shape on demo and real (`etoro_client.py:2650-2662`, `_v3_exec_order` :1198-1204).
     * **Proven dead:** the trade row is CANCELED and the order goes back to ARMED as a HOLD ("eToro's market for X was shut: it would have filled at the open; withdrawn, still armed").
     * **Not proven:** the order is WORKING with `flags.withdraw_unproven`, red in the list. A staff alert and a Telegram line go out: "it may fill at the open; cancel it in eToro's app". The tick retries the proven withdrawal on every pass, and the risk counts as reserved. It is never treated as an accepted WORKING order.
   * **A refusal:** HOLD, BLOCK or CANCEL (§5.4).
   * **An exception after the send** (`getattr(e, "in_doubt", False)`): IN_DOUBT (§5.6a). The note is written (§5.9), a staff alert is sent, and the risk is reserved.
   * **An exception before the send** (NEVER_SENT, the adapter's "NOT SENT"): back to ARMED with a hold counted, "not sent: <why>".
7. **Tell the operator.** A Telegram line in the platform's voice, with a button to the order's own row (`/orders/#po-<pk>`):
   * "BUY LIMIT EURUSD 1.08120 triggered: filled 12,000 at 1.08118";
   * or "triggered and refused: the daily stop is reached; nothing was sent";
   * or "expired at 21:00 UTC; nothing was sent".

**A FIRING order older than 5 minutes** (a worker died mid-fire) becomes IN_DOUBT, never ARMED or CANCELLED. Morgul alerts on it (§9).

### 5.6a IN_DOUBT: how it ends

* **Code never re-sends it and never re-arms it. Before M12 is pinned, no code moves it anywhere.**
* **Why position reads cannot clear it.**
  * An order eToro holds (status 11, with frozen cash) has no position: its `positionExecutions` is empty (the `order_status` docstring, `etoro_client.py:2231-2233`).
  * `_settle_in_doubt` reads positions only (`base.py:1811`) and adopts nothing: "a position the venue holds is NEVER adopted here" (:1790-1793).
  * A lookup by `referenceId` answers 404 (:2168-2172), and the `orderId` was in the answer that was lost.
  * Two flat reads would therefore clear an order eToro still holds, and the operator would be invited to send a second one, which fills beside the first at the open.
* **While IN_DOUBT:**
  * its risk (qty × the stop distance at its price) and its margin are reserved in the open-risk cap and the pool (`reserved_risk`);
  * the symbol's in-doubt note stays;
  * a new order, a program firing or a TAKE TRADE on that symbol is refused with: "an order for X may already be at eToro: check eToro's pending orders and positions, then resolve it".
* **The hand resolution (ACT).** RESOLVE on the row opens a dialog: "Check eToro's app: your pending orders, then your open positions. If anything from this order is there, close or cancel it there first: the platform cannot adopt it."
  * It has one checkbox, "I checked eToro's pending orders and positions: nothing from this order is there", the PIN, and one button, RESOLVE: NOTHING AT ETORO.
  * It ends as CANCELLED ("resolved by hand"): the note is cleared and the reservation released.
  * There is no "it is at eToro" act, because the platform cannot adopt a position.
* **After M12 pins `ordersForOpen`**, the settle reads `clientPortfolio.ordersForOpen[]` (and `orders[]`) beside the positions:
  * an order found is withdrawn through `cancel_order`, and once proven it is CANCELLED;
  * a position found stays IN_DOUBT, with an alert: "a position from this order is at eToro: close it there, then resolve";
  * nothing found in either, on two reads past the lag: CANCELLED ("nothing from it is in eToro's orders or positions").
* Morgul alerts on an IN_DOUBT order older than an hour (§9).

### 5.7 The working orders: the `/orders/` page, the card, cancel, MOVE

**The `/orders/` page** (new, `dashboard/views_orders.py`, `templates/dashboard/orders.html`). It has three tabs, **Working (n)**, **Shadow (n)** and **Recent 48 h (n)**, and a link to Programs. See `mockups/orders_page_1280.png`.
* **Working** lists every order that can send: ARMED, FIRING, WORKING (`withdraw_unproven` included) and IN_DOUBT, in paper, demo and real.
  * Each row carries a world chip: PAPER, DEMO or REAL.
  * The tab also lists every legacy WORKING row (`entry_working`) with no PriceOrder, so the market order eToro queued for the open appears too.
* **Shadow** lists the operator's and the programs' shadow orders, with the shadow record line ("real money in shadow: graded 14, mean +0.18 R against a market entry"). **The bots' would-orders are not here.** They are on the bot config page, with their record (§8.2).
* **Recent 48 h** lists:
  * FILLED, with a link to the position;
  * REFUSED, with the gate's words;
  * EXPIRED;
  * CANCELLED, with by whom;
  * WOULD_FIRE, with its grade once graded.
* Every row has the anchor `#po-<pk>`, and every Telegram line about an order links to it. The shape goes into `DEEP_LINK_PATHS` (`alerts/links.py:89`), with its test.

**The positions page card:** **WORKING ORDERS · n**, above Current Positions, with the anchor `#working-orders`. It is shown only when something can send.
* At most 3 rows, then "show all n on /orders/", and the links "shadow 4 · recent 48 h 5".
* The Eye's and the headband's "orders" count counts only orders that can send, and links to `#working-orders`.

**The table** is `sv-perf-table sv-stack sv-stack--pairs` (two fields a line, as `positions_list.html:220-221`).
* Columns: select, symbol, order (side, kind, world), price (now and distance), size, stop · target, expires (with the time left), held by (the source), state (with the hold's reason), by (You, a bot config, a program), and action.
* **The stop and target cell is labelled "Stop · Target"** in its `data-label` too.
* **On a phone, each order is a three-line summary**, in a `po-sum` cell that is `sv-cell-wide` and hidden above 768 px:
  * line 1: symbol, side, kind, price;
  * line 2: state and time left;
  * line 3: the action.
* The detail cells sit behind a tap on the summary (`aria-expanded` on the row; `.po-detail` cells hidden on the phone until it is open). Six orders take six summary heights, not six cards of ten lines.

**Cancel** (STOP door; paper and shadow orders need no PIN):
* per row;
* **checkboxes and CANCEL SELECTED (n)**;
* **CANCEL ALL ORDERS (n)**: one dialog lists them, with one PIN.

What each state does:
* ARMED: CANCELLED, under `select_for_update`.
* A venue-held WORKING order goes through `cancel_working_entry`, which must prove it dead. Unproven stays WORKING, with "it may still fill; cancel it in eToro's app".
* FIRING is refused: "it is being sent right now; it will show as a position or a refusal within a minute".
* IN_DOUBT is not cancellable here; the row offers RESOLVE (§5.6a).
* Telegram `/stop` leaves the operator's own orders alone, as it leaves the manual lane alone (`base.py:1041-1042`).

**A cancel of a bot's or a program's order sticks.**
* **A bot's order.** The cancel writes `config.extras.order_cancel_blocks["SYMBOL:SIDE"] = {until: now + 12 h, signal_id, by}`. The bot places no order and no would-order for that symbol and side until the signal behind it changes (a new signal id) or 12 h pass. The dialog says: "crypto-1 will not place this again until its signal changes or 12 h pass (Sun 06:34 UTC)."
* **A program's order.** The cancel consumes the program's firing for the day, counted against `per_day`. The dialog has a checkbox, "also pause the program", and says: "Gold: fade the Asian high will not place another order today."

**MOVE** (ACT), on a platform-held ARMED row.
* It opens the ticket pre-filled from the order: kind, price, worst price, expiry, stop, target and size.
* On confirm, under the order's lock, the new order is judged and placed, and the old one is CANCELLED, in one transaction.
* If the new one is refused, the old one stays ARMED and the refusal is shown.
* A venue-held order has no MOVE, because eToro cannot swap it atomically: WITHDRAW it (proven), then place a new one.

**Who else cancels:**
* the kill switch: ARMED orders, while FIRING ones are left to finish (§9);
* the config disabled or the lane disarmed;
* the world or the mode changed;
* a `_live` switch turned OFF, for what it allowed;
* expiry;
* a program paused or cancelled, for its ARMED orders.

**The instrument page** lists the symbol's own working orders under the deal ticket. The chart gets a dashed line per order price (`_partials/chart_widget.html`), labelled "BUY LIMIT 1.08120". **/treasury/** already lists working entries (`templates/dashboard/treasury.html:150`).

### 5.8 Paper, demo, real, and shadow

| World | `price_orders` ON | and `price_orders_live` ON |
|---|---|---|
| paper | placed ARMED; touch-model fills | same |
| demo (eToro demo key) | placed ARMED; fires at eToro demo | same |
| real | placed in **SHADOW**: armed, watched, graded, **never sent**. At the trigger, the state is WOULD_FIRE, with `judge()`'s verdicts recorded | placed ARMED (mode live); fires |

With `price_orders` OFF, nothing is watched, and the ticket shows LIMIT and STOP ENTRY disabled, with the line "orders at a price are off (price_orders)".

**The mode is stored once, and only read.** A shadow order stays shadow forever: turning `price_orders_live` ON arms nothing that was armed in shadow, because the ticket said "it will not send". `test_switch_on_does_not_promote_shadow_orders` pins this.

**The world is checked at placement (stored) and at fire (derived, §5.6 step 2).** Two flips would change a resting order's world, and both are now refused while orders rest:
* `dashboard/views_brokers.demo_untick_refusals` (:566) refuses the demo-to-live flip for enabled live configs and ticked class boxes. It gets a fourth check: the user holds ARMED, FIRING, WORKING or IN_DOUBT PriceOrders in the demo world, or ACTIVE live programs routed there. The words are: "3 orders at a price rest on eToro DEMO: cancel them first (/orders/), or they would fire on the real account."
* `manual_trade.arm_manual_lane` (:3040), from paper to live, gets the same check: "2 paper orders at a price rest on the forex lane: cancel them first; arming would make them real."
* **Standing down (live to paper) is never gated**; that is the function's own rule, "stopping must never be gated". It cancels the lane's live orders and pauses its live programs, with words.

**Grading** (shadow and live alike) is done by `price_orders.grade(order)`, run by the watcher hourly. It uses the platform's existing bracket walk:
* `capital_desk._decision_bars` (:1332) and `walk_bracket` (:1358);
* the council's touch helpers `_first_touch` / `_walk_from_fill` (`ai_agents/council_grading.py:390-410`), moved into a shared `bot_program/fill_walk.py` that both import, so the council's grade stays byte-for-byte the same.

The numbers:
* `r_market`: the same side, stop distance and target R, entered at market at `baseline.at` (placement);
* `r_order`: the walk from the trigger fill (the stop wins on the fill bar), with the cost;
* never fired: `r_order = 0`;
* `value_r = r_order - r_market`.

The Shadow tab shows the running record: "graded 14, mean +0.18 R against market".

### 5.9 Prerequisite fix: the TAKE TRADE lane's in-doubt note

Today, a timeout after `client.market_order` on the manual lane writes no note and no row (`manual_trade.py:2710-2717`). A second click after the 120 s claim sends again (`map_path.md` §4, fault 2). The watcher would make that automatic, so this fix ships first in P2, alone in its commit:
* **The note is written only for a real doubt.** That is when `getattr(e, "in_doubt", False)` is true (`EtoroOrderInDoubt`, `etoro_client.py:756-757`), with the reference taken from `e.reference`. The note is `config.extras.entry_in_doubt[SYMBOL] = {reference, at, flat_reads}`, written by the same writer as the bots' (`_remember_in_doubt`, `base.py:1668`, made a module-level helper both lanes call). The bare `except` at :2710 also catches the adapter's "eToro NOT SENT" ValueErrors (:818-836) and the NEVER_SENT RuntimeError (:2454-2462), where nothing left the box. Those keep their "not sent" words and write no note.
* `_execute` refuses the symbol while the note is live (read like `propose_entry` :4257-4268).
* The words are: "an order for X may already be at eToro: check its pending orders and positions, then resolve it here."
* **On eToro, the note never clears on position reads alone**, because a held order has no position. It clears by the hand RESOLVE (§5.6a, ACT), or, after M12, by the settle that also reads `ordersForOpen`. On the other venues it clears as the bots' note does today.
* The bots' own note (`_settle_in_doubt`) has the same blind spot. P2a does not change it, because that is today's behaviour. M12's read is added to `_settle_in_doubt` in the same commit that adds it to the orders.

### 5.10 States and transitions (P2)

```
place (ACT) --platform, mode live--> ARMED
place (ACT) --platform, real, price_orders_live OFF--> ARMED (mode shadow, forever)
place (ACT) --venue (P2b)--> WORKING (+ the WORKING AssetBotTrade row; risk reserved)

ARMED --watch: triggered on its source--> FIRING
FIRING --world/mode changed | config stopped | kill | switch OFF--> CANCELLED (nothing sent)
FIRING --judge HOLD (book or clock unread, stale or gap, budget, health, timing)--> ARMED (holds+1)
FIRING --judge BLOCK | past the worst price--> REFUSED                    (terminal)
FIRING --eToro did not touch--> ARMED
FIRING --NEVER_SENT--> ARMED (holds+1)
FIRING --filled--> FILLED (trade)                                          (terminal for the order)
FIRING --eToro held it (status 11)--> withdrawn: --proven--> ARMED (hold "shut at eToro")
                                                --unproven--> WORKING + withdraw_unproven (alert, retried each tick)
                                                      --proven later--> ARMED | --fill--> FILLED
FIRING --exception after the send--> IN_DOUBT (risk reserved, note kept)
IN_DOUBT --hand RESOLVE: nothing at eToro (ACT)--> CANCELLED
IN_DOUBT --(after M12) eToro order found, withdrawn, proven--> CANCELLED
IN_DOUBT --(after M12) nothing in orders or positions, twice--> CANCELLED
IN_DOUBT --(after M12) position found--> IN_DOUBT (alert)
FIRING --older than 5 min--> IN_DOUBT
ARMED --expires_at--> EXPIRED                                              (terminal)
ARMED --cancel | selected | all | standing gate | switch OFF | program paused--> CANCELLED (terminal)
ARMED --MOVE (ACT), new order placed--> CANCELLED (+ the new ARMED order)
ARMED (shadow) --triggered--> WOULD_FIRE (judge() recorded, nothing sent) (terminal, graded)
WORKING (venue-held) --good_till | daily stop | cap | shut ahead--> cancel_working_entry
      --proven--> EXPIRED | CANCELLED   --unproven--> WORKING (alerted)
```

### 5.11 Switches (P2)

* `price_orders` ("Orders at a price: the watcher"), category system, OFF, **not** a live-money switch: with it ON alone, real money is only shadowed.
  * Description: "Off (default). On: every 60 s the platform watches the limit and stop-entry orders placed on the ticket, fires paper and demo ones through the ticket's gates, and shadows real-money ones (graded, never sent). Real money also needs price_orders_live."
* `price_orders_live`, OFF, in `LIVE_MONEY_SWITCHES`. Turning it OFF cancels the mode-live orders in the real world, with words. Turning it ON promotes nothing.
  * Description: "Off (default) = real-money orders at a price are armed in SHADOW: watched and graded, never sent. On = new ones fire, each through the daily stop, the open-risk cap, the pool, the venue floor, the timing gate and eToro's quote re-read. Flip after the shadow record."
* `etoro_mit_live` (P2b), OFF, in `LIVE_MONEY_SWITCHES`.

### 5.12 Files and functions (P2)

| File | Change |
|---|---|
| `bot_program/order_models.py` (new), `bot_program/models.py` | `PriceOrder` |
| `bot_program/migrations/0046_price_orders.py` | the table |
| `bot_program/price_orders.py` (new) | `place`, `holder_for`, `watch_source`, `expiry_for` (next session when shut), `world_now`, `watch`, `judge`, `fire`, `cancel`, `cancel_many`, `move`, `resolve_in_doubt`, `reserved_risk`, `grade`, `standing_gates`, `paper_touch` |
| `bot_program/engine/etoro_budget.py` (new) | the shared per-key bucket and its reserve (§9) |
| `bot_program/fill_walk.py` (new) | `first_touch`, `walk_from_fill`, moved from `council_grading.py` and re-exported there |
| `bot_program/manual_trade.py` | `_preview(..., order=)`: levels judged at the order price, the `head` block, the presets' pre-fill; `_execute(..., at_fire=)`: the two gate groups, `fail_closed`, the anchor, the `pin_ok` rule; the in-doubt note (§5.9); `arm_manual_lane` refuses paper to live while paper orders rest, and standing down cancels |
| `bot_program/asset_engine/base.py` | `_last_look(..., anchor=None)`; `_remember_in_doubt` lifted to a helper; `_working_entry_age_hours` and the 26 h rule (:1629, :1988) read `entry_order.good_till` when present; `_settle_in_doubt` reads `ordersForOpen` once M12 is pinned |
| `bot_program/entry_timing.py` | `verdict(..., fail_closed=False)`: True turns an unreadable clock or calendar into the refusal `clock_unread` |
| `portfolio/risk_gate.py` | the open-risk state adds `price_orders.reserved_risk` |
| `bot_program/engine/etoro_client.py` | `_lookup_once` (:2162) records a 429 on the venue's health and takes the measured pause; every request takes its budget token; (P2b) `mit_order(symbol, side, units, trigger_rate, **legs)`, measured |
| `bot_program/tasks.py`, `config/celery.py` | `watch_price_orders`, `watch-price-orders` every 60 s |
| `bot_program/engine/kill_switch.py` | cancels ARMED orders in scope; leaves FIRING ones to finish, then sweeps their rows (§9) |
| `bot_program/notifications.py` | placed, triggered, filled, refused, expired, in doubt, withdraw unproven; each with the `/orders/#po-<pk>` button |
| `dashboard/views.py` | `_parse_trade_body` (:4913) parses `order: {kind, price, worst_price, expiry_kind, expires_on}`, strict on shape; `asset_trade_execute` (:5291) and `take_trade_execute` (:4851) route a non-market kind to `price_orders.place` (door ACT, as today) |
| `dashboard/views_orders.py` (new), `dashboard/urls.py` | the `/orders/` page and its three tabs; the card partial; cancel preview and cancel; cancel selected and cancel all; MOVE; RESOLVE |
| `dashboard/views_brokers.py` | `demo_untick_refusals` gets its fourth check |
| `templates/base.html` | `sizeDialog`: the head from `p.head`; the ORDER block; the SHADOW line; the chips under the price; the Set line; the More disclosure; `tradeFlow` sends `order`; the success alert from `p.head.success` |
| `templates/_partials/deal_ticket.html` | BUY AT A PRICE, SELL AT A PRICE, and the working-orders count |
| `templates/dashboard/orders.html` (new), `_partials/working_orders.html` (new), `templates/dashboard/positions_list.html` | the page; the card (3 rows, `#working-orders`); a `.sv-stack.sv-stack--pairs` table with a `data-label` on every cell. Each cell's content sits in one `.po-cell`, because a stacked cell is a two-column grid and a second child (the distance, a note) otherwise drops under the label (found on the 390 render). The `po-sum` cell and the `.po-detail` cells |
| `templates/dashboard/_eye_body.html`, the headband | the count of orders that can send, linked to `#working-orders` |
| `alerts/links.py` | `/orders/#po-<pk>` in `DEEP_LINK_PATHS` |
| `static/css/sauron.css` | the rules in `mockups/css/orders.css` (`.po-*`) |
| `core/platform_control.py` | the switch rows |
| `bot_program/engine/capabilities.py` (P2b) | the `price_orders` tier |

### 5.13 Tests to write first (P2)

* `tests/test_take_trade_in_doubt.py`:
  * the timeout writes the note, and a second click after 120 s is refused;
  * a "NOT SENT" ValueError or a NEVER_SENT RuntimeError writes no note;
  * on eToro, a WaitingForMarket-shaped doubt with two flat position reads keeps the note;
  * RESOLVE (ACT) clears it.
* `tests/test_price_orders_place.py`:
  * the ACT door;
  * a wrong-side limit or stop is refused with its arithmetic, and so is a price too close;
  * the pre-fill is the nearest tappable legal smart price, or empty and required;
  * levels are judged at the order price, not the mark;
  * real + `price_orders_live` OFF places SHADOW, with the words;
  * paper and demo place ARMED;
  * the accepted advisories are stored;
  * expiry per class: end of day at the rollover, the exchange close, 00:00 UTC for crypto; GTC capped at 30 days;
  * `test_eod_placed_on_saturday_is_next_session_per_class` (NVDA, EURUSD, XAUUSD, SPX500);
  * `test_head_follows_kind_and_mode` (title, message, frame and success alert per row of §5.1);
  * `test_pin_never_stored`: no field holds the PIN or a hash of it; only `pin_door` and `pin_checked_at`;
  * a symbol past the eToro watch cap W is refused with words;
  * a strict body: a bool price, a NaN or a negative is refused.
* `tests/test_price_orders_fire.py`:
  * every BLOCK gate refuses and sends nothing;
  * every HOLD gate keeps the order ARMED;
  * **a new trade advisory refuses while an accepted one passes**;
  * the daily stop refuses even when accepted at placement;
  * `test_preflight_raising_at_fire_holds_and_sends_nothing`, and the same for an unread open-risk state, pool, pledge or note;
  * `test_unreadable_clock_holds`, and `test_index_fire_sunday_2200_utc_holds`;
  * eToro's quote older than 30 s, or the first print after a 15-minute gap, HOLDs;
  * `test_non_positive_etoro_bid_or_ask_holds`;
  * eToro not touched goes back to ARMED;
  * past the worst price is REFUSED;
  * a decision is never made on the opening print;
  * `test_waiting_for_market_answer_is_withdrawn_never_working`: proven goes to ARMED; unproven goes to WORKING + `withdraw_unproven` + alert;
  * `test_demo_order_after_untick_is_cancelled`;
  * `test_paper_order_after_mode_flip_is_cancelled_and_never_calls_market_order`;
  * `test_pin_ok_passed_only_when_world_unchanged`;
  * `test_x_request_id_is_uuid5_of_order_and_fire_n` (it asserts the header sent, not only the platform-side id), and a re-fire after a HOLD sends a new id;
  * **two concurrent fires send once** (threads on the claim);
  * outcomes are written by compare-and-set: a CANCELLED order is never overwritten by FILLED;
  * `test_kill_during_fire_leaves_no_untracked_row`;
  * a POST timeout is IN_DOUBT, never re-armed, with the note written and the risk reserved;
  * `test_in_doubt_waiting_for_market_shape_stays_in_doubt_with_flat_positions_and_blocks_the_symbol`;
  * `test_firing_older_than_5_min_becomes_in_doubt`;
  * `test_shadow_never_calls_market_order` (the client factory is patched to raise);
  * `test_switch_on_does_not_promote_shadow_orders`.
* `tests/test_price_orders_watch.py`:
  * `watch_source` per class: index and commodity read eToro, never Yahoo; crypto reads Binance when fresh; forex without OANDA reads eToro;
  * the near band reads eToro;
  * a stale source triggers nothing;
  * one pass at a time;
  * expiry;
  * the standing gates cancel, the world check included;
  * the switches cancel in every world they cover;
  * `platform_master` OFF or `price_orders` OFF does nothing;
  * eToro's reads stay inside W and the budget.
* `tests/test_etoro_budget.py`:
  * the bucket is shared across processes;
  * the reserve is spent only by closes, close proofs and the kill switch;
  * an entry over the budget HOLDs, while a close is never refused;
  * a 429 on a lookup is recorded on the venue's health.
* `tests/test_price_orders_cancel.py`:
  * the STOP door;
  * ARMED is cancelled, and FIRING refused;
  * venue-held, proven or unproven;
  * cancel selected and cancel all;
  * the kill switch cancels ARMED orders, leaves FIRING ones, and sweeps their rows;
  * `/stop` leaves the operator's orders alone;
  * a bot order's cancel writes the block, and the bot does not re-place it;
  * a program order's cancel consumes the day.
* `tests/test_price_orders_move.py`: the MOVE is atomic, and a refused new order keeps the old one ARMED.
* `tests/test_price_orders_flips.py`:
  * `demo_untick_refusals` refuses while demo orders rest;
  * `arm_manual_lane` refuses paper to live while paper orders rest;
  * standing down cancels and is never refused.
* `tests/test_price_orders_paper.py`: the touch model (a limit at the price or a better gap, a stop at the worse of the trigger and the open).
* `tests/test_price_orders_grade.py`:
  * `value_r`;
  * the stop wins on the fill bar;
  * never fired means `-r_market`;
  * the council grade is unchanged after the move to `fill_walk.py`.
* `tests/test_working_entries.py` (extend): `good_till` overrides 26 h for `entry_order` rows, and a plain working entry keeps 26 h.
* `tests/test_component_registry.py`: the new keys exist, the `_live` keys are in `LIVE_MONEY_SWITCHES`, and the descriptions are under 300 characters.

### 5.14 What a screenshot must show (P2)

1. **The MARKET ticket at 390:** today's head (title, message, red frame) and an ORDER block holding only the segmented control. It is the proof of zero extra taps.
2. **The LIMIT ticket on real money, mode live:**
   * the red frame, "Place a BUY LIMIT with REAL funds?" and its message;
   * the price with its distance, the chips directly under it, and the Set line after a tap;
   * the kind line ("at worst 96,533"), the expiry with its resolved UTC time, and More (closed, its default shown);
   * the holder line naming the source and its cadence;
   * the levels judged at the order price, the "nobody is watching" block, the PIN, and PLACE LIMIT ORDER.
3. **The same ticket armed in shadow:** no red frame, the title "Arm in shadow (nothing will send)", the SHADOW line at the top of ORDER, an END OF DAY reading "(next session)", ARM IN SHADOW, and the success alert.
4. **The positions page card:** at most 3 rows, the Shadow and Recent links, CANCEL ALL ORDERS and the checkboxes. At 390, the three-line summaries, with one row opened and no sideways scroll.
5. **The `/orders/` page:** the Recent 48 h tab with FILLED, REFUSED, EXPIRED, CANCELLED and WOULD_FIRE rows, and the Shadow tab with its record.
6. The IN_DOUBT row with RESOLVE, and the WORKING row with "withdraw not proven".
7. The Telegram line for a fill, and the line for a refusal at fire.

### 5.15 P2b: eToro holds the limit (MIT)

Only after M1-M6, M4b, M6b and M10 are pinned:
* `EtoroTrader.mit_order` sends the documented body: `orderType "mit"`, `triggerRate`, no `settlementType` (`map_venue` §2).
* The holder chooser can then answer "venue", for the side M4b pins.
* Placement books the WORKING row with `entry_order` (§5.3), and its risk and frozen cash are reserved.
* **The tick's standing gates for a venue-held order.** eToro fills it while nobody checks, so the tick's `_poll_working_entry` (`base.py:1847`) re-runs these gates on every pass:
  * the config is enabled, the lane is armed, and the class gate is open;
  * the world, and the switches;
  * **the daily stop**: the book preflight on the manual lane, and the bot's daily loss on a bot;
  * **the open-risk cap**.

  If one fails, or if the book cannot be read, the order is **withdrawn**, proven, through `cancel_working_entry`. A resting order cannot be held, only withdrawn. `map_venue` §13 stated the choice ("count every resting order as filled, or cancel resting orders when the cap or the daily stop is reached"); this spec does both.
* **Before a shut.** The order is withdrawn, proven, inside `position_care.is_weekend_window` (:228) or `long_shut_ahead` (:239) for its class. A gap through both the trigger and the stop would fill a position that is already past its stop, and eToro rewrites stops at the fill in both directions (`map_venue` §10).
  * The one exception is `flags.rest_through_shut`, set by the operator with ACT. It is offered only after M6b pins what a resting MIT does over a shut.
  * Until then, no venue-held order rests through a shut.
* The stop eToro rewrites at the fill (`base.py:6390-6422`) is read back by `_finish_working_entry` (:2055) as today.
* M3 must prove that the measured v3 DELETE (`etoro_client.py:1150-1159`) cancels a status-12 order. `etoro-go` uses a v2 DELETE for orders (`trading.go:170-179`).
* A resting MIT that is in doubt cannot be found in the positions list. It needs the `/portfolio` `orders[]` read (M2, M12). Until then, a timed-out MIT POST is IN_DOUBT with "check eToro's pending orders", resolved as in §5.6a.
* **The [C] support is `etoro-go` alone.** `etoropy` 0.1.7 knows neither `orderType "mit"` (only the deprecated v1 limit-orders route) nor the close-order read.

---

## 6. P3: smart prices on the ticket

### 6.1 What the operator sees

The chips sit **directly under the price field**, before the kind line, the expiry and More. They are ordered nearest first, with at most three per side of the mark.

Each chip names what a tap sets, in three lines:
* the kind and the level: "BUY LIMIT · below · 4h pool, 2 touches", or "BUY STOP ENTRY · above · 4h swing high";
* the prices: "trigger 96,520 · exit stop 95,880". A stop entry carries two different prices, its trigger and its exit stop, and the chip names both;
* the source and the age: "eToro 4h bars · 11 min".

**What a tap does:**
* It fills the price.
* It selects the kind the chip names; the kind never switches silently.
* If the level carries its own stop, it offers "use its stop: 95,880 (beyond the crowd)" as a pre-ticked checkbox. While that box is ticked, the stop follows the chip.
* The size follows the stop while the operator has not typed units (`autoQty`, `base.html:2034-2038`).

**After a tap, one line under the chips** says everything that changed: "Set: STOP ENTRY 99,350 · stop 98,610 (was 95,880) · units 0.0412 (was 0.03125)". Each changed field flashes once (`.po-changed`, 1.2 s), because on a phone the stop and size blocks are below the visible part of the sheet.

**A level the platform cannot stand behind** is greyed and untappable. Its reason is a plain sentence with a time: "1d swing low 93,400: eToro's daily bars stop at Thu 29 Oct, too old to stand behind."

Under the row, one line: "Prices the platform computes from bars it can name. Tapping one fills the ticket; nothing is sent." The ticket's pre-fill (§5.1) is the nearest tappable chip on the legal side.

### 6.2 Where the prices come from: only what the code computes and can name

`bot_program/order_presets.py` (new):
```
presets_for(symbol, asset_class, side, mark, *, now, signal=None) -> {"presets": [...], "why": [...]}
preset = {id, family, label, price, side_of_mark, kind_for_side, stop|None,
          source, tf, as_of, age_s, fresh, tappable, why_not, graded_words}
```

| Family | Function | Source label | Fresh when |
|---|---|---|---|
| Swings, pools, the recent extreme, round numbers, with a stop per level | `orcs.menu.symbol_levels` (:228); ids such as `S4h-L1`, `P1h-H2`, `RN-k` | "eToro 1h/4h bars", or "platform bars (basis-shifted)" | the menu's own `fresh[tf]` (`orcs/bars.py`: the newest bar within 2 bar lengths of open market time) |
| The Asian range | `power_of_three.asian_range` (:114) on 1h | "1h bars, today's Asian range" | dropped 30 h after its close (`map_levels` §2) |
| The hunt and the draw | `positioning.positioning_map` (:282), `compact` (:479) | "positioning map (information)" | the map's own ages (COT ≤ 21 d, funding ≤ 12 h) |
| An SMC card's entry | `SmcSignal` ACTIVE for the symbol | "SMC card <setup>, <tf>, expires hh:mm" | while ACTIVE (TTL 48/168/720 h) |
| The signal's suggested entry | the ticket's signal (`signals/rule_adapter.py:120`) | "signal #id" | while the signal is live |

The menu does not need the `orcs` switch: it reads stored bars and moves nothing (`orcs/bars.py` header, "Reads only"). Results are memoised for 60 s per symbol, as the chart's levels are (`dashboard/views.py:4510-4547`).

### 6.3 Per class: "smart on certain assets"

`PRESET_POLICY` in `order_presets.py` decides which families each class gets, from what the code supports (`map_levels.md` §4). The order classes arrive in is the operator's choice (D9); this spec assumes crypto and forex first.

| Class | Families offered | Not offered, and why |
|---|---|---|
| forex | Asian high/low (PO3, 1h); menu pools and swings shown as **bands** (pools are loose on forex: 0.1% ≈ 0.7 ATR); round numbers (big figure and half) | none extra |
| index | menu pools and swings 1h/4h; round numbers | PO3 only when the stored 1h bars cover 20:00-00:00 New York; "session high/low" is computed nowhere |
| crypto | menu pools (tight), swings, round numbers | none |
| stock, etf | menu pools and swings; an overnight-gap note on any order resting past the close | PO3 (no Asian bars on a US share) |
| commodity | **only menu levels with source "eToro"**. A basis-shifted frame is shown only when `basis_stable` (:129) holds, and its structure levels are dropped otherwise | `living_levels`: the platform's XAUUSD bars are Yahoo's GC=F future, off eToro's price by the basis |
| options | none | no crowd levels (`lock_adjuster` :951) |

**Never a preset, by test:**
* the Big Money board (`tests/test_big_money_board.py:971`);
* the council's levels (council.py, "THE LAW: SHADOW").

`order_presets.py`, `price_orders.py` and `order_programs.py` join the list that `test_no_money_path_imports_the_board` and the council's law test walk.

**The grade words on each chip:** "the claim 'a sweep of this pool reverses' is PROVEN on forex 4h longs (pool_sweep)", or "unjudged". Always followed by: "**as an order resting at this price: not graded**". This is the honest line from `map_levels.md` §0 point 2, until P2's grading builds a record per family.

### 6.4 Files, data, switch, tests, screenshot (P3)

* **Files:**
  * `bot_program/order_presets.py` (new);
  * `manual_trade._preview` adds `presets` to the payload, computed after the levels and fenced: a preset that cannot be read is a `why`, never an error;
  * `templates/base.html` `sizeDialog` renders the chips under the price, the Set line and the flash;
  * the `.po-preset`, `.po-set` and `.po-changed` CSS.
* **Data:** none.
* **Switch:** none. It fills a field, and the operator's click and PIN still decide.
* **Tests first:** `tests/test_order_presets.py`:
  * the per-class policy;
  * commodity takes venue-grid levels only and drops structure on an unstable basis;
  * a stale frame is untappable, with a plain why that carries a time;
  * a swept level is gone on the next read;
  * every preset carries a source, an age and `kind_for_side`;
  * the pre-fill picks the nearest tappable legal preset, or none;
  * no Big Money or council import;
  * a menu that fails gives `why`, never an exception.
* **Screenshot:**
  * the chips row under the price, with one tapped, its stop offered, and the Set line;
  * one chip greyed, with its why;
  * at 390, the chips wrap with no sideways scroll.

---

## 7. P4: order programs

### 7.1 What a program is

A program is a small, typed rule: "**when** these conditions hold, **then** place this order". It is saved, listed, edited, paused and cancelled. Nothing in it is code, and no free text executes. It is written on a page by the operator, and it may be run as the operator's lane or as a bot config.

**The conditions** (all must hold; at most four rows):

| Condition | Fields | How it is read |
|---|---|---|
| Price crosses | `op`: crosses above, crosses below; `level`: a LevelRef; `on`: quote, 1h close, 4h close | "crosses" compares the side at this read with the side stored at the last evaluation. On a close, it uses **final** bars only (`orcs/bars.final_bar`). **Memory older than two evaluation periods (120 s), or memory that spans a shut of the instrument's market, only re-records and never fires**: "below on Friday, above on the Monday gap" is not a cross (`map_venue` §10, "replay after a restart") |
| Price touches | `level`: a LevelRef; `band`: 0 to 0.5 ATR | the quote, or a bar's high/low since the last pass |
| Price is above / below | `level` | the quote |
| Time window | a session (Asia, London, NY AM, NY PM: `power_of_three.session_now` :83 and `signals/smc/sessions.py`) or `from`/`to`/`tz`/`days` | the clock |
| While a signal is active | `rule` (a name, or any), `side` (BUY, SELL, or the program's own) | an ACTIVE `Signal` for the symbol |
| While a rule is at a stage | `rule`, `stage_at_least` (paper, live_small) | `RuleControl` |

**Firing is edge-triggered.** "Is above", a time window or an active signal stay true pass after pass. A program therefore fires on the pass where the whole set of conditions turns true. It re-arms only after the set has read false on a later pass (`memory.armed`). Held for ten passes, "is above" fires once.

**A LevelRef** is `{"price": 1.0812}` or `{"preset": "<id>"}`, where the id is any P3 preset (`menu:S4h-L1`, `po3:asia_low`, `round:next_below`, `card:<id>`).
* It is **re-resolved at every evaluation**, because levels move and disappear (`map_levels.md` §5.1).
* A gone level makes the condition false, with the note "level gone".
* A program whose level has been gone for three days goes BROKEN, and the operator is told.

**The order** (THEN):
* `side`; `kind`: market, limit at a LevelRef, or stop at a LevelRef;
* `stop`: a LevelRef, the level's own stop, or `{"atr": 1.5}`;
* `target`: `{"r": 2.0}` or a LevelRef;
* `size`: `{"risk_pct": 0.5}` of the lane's pool, or fixed units;
* `expiry`: hours after the program places the order, or end of day. The order stores the absolute moment, computed at placement;
* `worst`: the worst-price offset (as `slip_cap`).
* **A market action has a price too.** Its PriceOrder carries `price` = the level of the program's price condition (or, without a price condition, eToro's quote at the evaluation), and a worst price from it. The fire then refuses anything past that worst price.

**The limits are mandatory.** `validate()` refuses a program without them:
* `per_day`: default 1;
* `cooloff_h`: default 4;
* `total`: required, with no default;
* `until` (the program's own end): default 30 days.

**One live idea per program.** No new firing while the program has either of these:
* a PriceOrder in ARMED, FIRING, WORKING or IN_DOUBT;
* an OPEN or CLOSE_PENDING trade from its last firing.

This holds on the manual lane too, which has nothing like `ALREADY_OPEN`. Its duplicate window, `MANUAL_REPEAT_WINDOW_SECONDS = 60` (`manual_trade.py:126`), equals the evaluator's own cadence, so it cannot be the guard.

**Runs as:**
* **"My manual lane"** fires through `_execute(at_fire=...)` (§5.6), with no accepted advisories: a program accepts nothing on the operator's behalf.
* **"Bot config #N"** fires through the bot path (§8.3, `at_fire`). The decision's rule name is `program:<id>`.
  * **A rule with no `RuleControl` row is forced to paper** (`signals/rule_actuator.py:106-112`: "paper venue only until it is promoted").
  * So a bot-run program trades on the paper venue until the operator promotes `program:<id>` on the existing promotion ladder.
  * **Code never creates that row**; a test pins it. After the promotion, size by proof applies as for any rule.

### 7.2 The data model (migration `0047_order_programs.py`)

```python
class OrderProgram(models.Model):
    STATES = ("ACTIVE", "PAUSED", "CANCELLED", "DONE", "BROKEN")
    user, name (CharField 80)
    instrument FK; symbol; asset_class        # one symbol per program; "copy to..." clones it
    conditions = JSONField(list)              # validated by order_programs.validate()
    action     = JSONField(dict)
    limits     = JSONField(dict)              # {per_day, total, cooloff_h, until}: all required (defaults filled)
    runs_as    = "manual" | FK(AssetBotConfig, null=True)
    mode       = "shadow" | "live"            # create() always stores shadow, whatever the caller passes
    state, state_at, state_why
    author     = "operator" | "bot:<cfg id>" | "council"   # council: shadow only, by law; bot: runs only as itself
    version    = PositiveInteger              # an edit makes version n+1
    memory     = JSONField(dict)              # per-condition last side and its time, armed, the window's baseline
    last_eval  = JSONField(dict)              # {at, rows: [{cond, ok, read, source, age_s}], fired: bool}
    record     = JSONField(dict)              # per version: {since_version, windows, fired, missed,
                                              #   mean_all, mean_fired, mean_missed, last_graded_at}
    created_at, updated_at

class ProgramFiring(models.Model):
    program FK; version; at
    conditions = JSONField(list)              # the truth table at the fire
    order      = FK(PriceOrder, null=True)    # null for a "missed window" grade row
    kind       = "fired" | "missed"
    grade      = JSONField(dict)
```

### 7.3 The evaluator: one scheduled task

`bot_program.tasks.evaluate_order_programs`, beat `evaluate-order-programs` every 60 s, `@guarded_task("order_programs")`, one pass at a time.

`order_programs.evaluate_all(now)`:
* It memoises one quote, one preset read and one bar frame per symbol for the pass.
* For each ACTIVE program, it evaluates every row and writes `last_eval` (the page shows it as a truth table).
* **It fires only when all of these hold:**
  * the set of conditions turned true on this pass (the edge);
  * the limits allow;
  * the one-live-idea rule passes.

  It then creates a `ProgramFiring` and a `PriceOrder(source="program", mode=…)`. The order is ARMED in every case, the market kind included, and is fired by the watcher's path (§5.6), through the shared eToro budget (§9). If a token is free on that pass, the fire runs at once. If not, the order waits for the watcher's next pass and is judged on the then-current price, against its worst price. The evaluator never goes around the budget.
* **The program never sends anything itself.**

**The mode of the order it creates:**
* shadow, unless the program is LIVE **and** `order_programs_live` is ON (in every world, demo included);
* **and**, for real money, `price_orders_live` is ON as well;
* otherwise shadow, with words saying which switch is off.

**The baseline for grading** (shadow and live). The market entry the firing is compared with is taken at the first pass in the window where every condition held **except the price condition**: the moment a person would have "taken it now".
* `value_r = r_program - r_market`, walked as in §5.8.
* When a window closes with no fire, a `ProgramFiring(kind="missed")` grades `0 - r_market`, the cost or benefit of waiting. This is the council's "never fired" rule (`council_grading.py:430-436`).
* **The record's headline is one number over all windows:** "14 windows: +0.05 R per window against taking it at market". Fired and missed are its breakdown ("fired 5: +0.21 R · missed 9: -0.04 R").
* **The record restarts with each version**, shown as "record since v3". Older versions stay folded under it.

### 7.4 The page

`/orders/programs/` (new, `dashboard/views_programs.py`), linked from the `/orders/` page, the WORKING ORDERS card and the instrument page. See `mockups/program_builder_1280.png`.

**The list comes first**, on the phone and on the desktop. Each program row holds:
* name, symbol, and chips for mode, state, runs as and version;
* the record's headline and its breakdown, "record since v3";
* its last evaluation, folded inside its own row and titled with the program's name, expanded on tap;
* actions on **every** state: EDIT, COPY TO…, PAUSE or RESUME, CANCEL, and GO LIVE (locked with its reason).

**+ NEW PROGRAM** opens the builder: its own page on a phone, a panel under the list on the desktop.
* **The builder starts with an instrument search field.** It drives the level picker and the RUNS AS list: the manual lane for that class, and the bots whose config holds that symbol.
* Condition rows come from fixed menus. The level picker shows the P3 chips with source and age. The remove button (×) and the small segments are 40 px tall.
* The THEN row; then the limits, with their defaults filled; then RUNS AS.
* **There is no MODE control.** One line says: "Starts in shadow. GO LIVE is on the list, with its record and your PIN."
* **A plain-English sentence** of the whole program, rebuilt on every change by the server's own renderer. The page shows what the server will evaluate, not what the browser assumes. It says "The order expires 8 h after the program places it".

**Endpoints and doors:**
* Save a new program: no PIN; it is stored in shadow.
* **Edit or copy: no PIN.** An edit of a LIVE program, or a copy of one, lands **PAUSED in shadow** as version n+1 (or as a new program). It needs GO LIVE (ACT) again, with the new version's record, which starts empty.
* Pause and cancel: STOP when live, no PIN in shadow.
  * **PAUSE and CANCEL also cancel the program's ARMED orders.** The confirm dialog names them: "its SELL LIMIT XAUUSD 2,742.0 is cancelled too".
  * A venue-held WORKING order goes through `cancel_working_entry`. An IN_DOUBT one stays, and RESOLVE is the way out.
* Resume and go live: ACT.

**GO LIVE is locked when any of these hold:**
* `order_programs_live` is OFF (the button names the switch);
* the program runs as a bot and its record is short (§8.4);
* it runs as a bot and `program:<id>` has no `RuleControl` promotion. The words say it would trade on paper.

For an operator program, GO LIVE shows its shadow record in the confirm dialog, empty or not, and the PIN decides.

### 7.5 "By me and the bots"

* **The operator** writes programs (above).
* **A bot config runs a program** when RUNS AS names it. The firing goes through the bot's own propose and execute, at the bot's size by proof, and on paper until `program:<id>` is promoted (§7.1).
* **Bots author programs** through `order_programs.create(..., author="bot:<cfg>")`.
  * `create()` ignores any mode a caller passes and stores shadow.
  * A bot-authored program may run only as its own config.
  * In P4 this is used only by P5's would-orders (§8).
* The council's Striker ("wait for a touch of X within 72 h") may become a **shadow-only** program (`author="council"`). A test pins that a council-authored program can never be set LIVE (council.py's law).

### 7.6 Switches, files, tests, screenshot (P4)

* **Switches:**
  * `order_programs` (the evaluator), OFF, not live money: shadow programs move nothing. Description: "Off (default). On: every 60 s the order programs written on /orders/programs/ are evaluated; a program whose conditions turn true places its order, in shadow unless it is live and order_programs_live is on. Graded against a market entry."
  * `order_programs_live`, OFF, in `LIVE_MONEY_SWITCHES`. **Turning it OFF pauses every LIVE program and cancels their ARMED orders, with words, in every world, demo included.**
* **Files:**
  * `bot_program/order_programs.py` (new): `validate`, `render_sentence`, `evaluate_all`, `evaluate`, `create`, `edit`, `copy_to`, `pause`, `resume`, `go_live`, `cancel`, `grade_missed`;
  * `bot_program/order_models.py` (`OrderProgram`, `ProgramFiring`);
  * `dashboard/views_programs.py`; `templates/dashboard/order_programs.html`;
  * `tasks.py` and `celery.py`;
  * `platform_control.py`.
* **Tests first:** `tests/test_order_programs.py`:
  * Validation:
    * `validate` refuses an unknown condition, a fifth row, a free-text field, or a level that is not a P3 id or a positive price;
    * `test_missing_limits_refused`, and the defaults are filled (per_day 1, cool-off 4 h, until 30 d, total required).
  * Reading the conditions:
    * crosses-above needs the stored previous side, and the first read only records it;
    * `test_memory_older_than_two_periods_only_records`, and `test_monday_gap_across_the_level_does_not_fire`;
    * a close condition reads final bars only;
    * the window edges;
    * a gone level makes the row false, and after three days the program is BROKEN.
  * Firing:
    * `test_is_above_held_for_ten_passes_fires_once` (the edge);
    * the limits (per day, total, cool-off);
    * `test_working_venue_order_blocks_a_refire`, `test_open_trade_from_last_firing_blocks_a_refire`, `test_in_doubt_order_blocks_a_refire`;
    * `test_market_action_carries_price_and_worst_price`, and `test_market_action_goes_through_the_budget`;
    * **a program never calls a client** (the client factory is patched to raise).
  * Mode and doors:
    * shadow unless both switches allow, and `order_programs_live` covers demo;
    * `test_edit_of_live_program_lands_paused_in_shadow_as_new_version`, `test_copy_lands_in_shadow`;
    * `test_create_ignores_a_passed_mode`;
    * `test_bot_authored_program_runs_only_as_its_config`;
    * `test_order_programs_live_off_pauses_and_cancels_in_every_world`;
    * `test_pause_and_cancel_cancel_armed_orders`;
    * a council-authored program can never go live;
    * go-live needs ACT.
  * The bot path:
    * `test_bot_run_program_is_paper_without_rulecontrol_and_code_never_creates_one`;
    * the bot-run record gate (§8.4) on the mean over all windows.
  * The record:
    * the baseline is taken at the first eligible pass;
    * a missed window is graded;
    * the record is per version, and the headline is the mean over all windows.
  * The sentence renderer matches the evaluator on twenty fixtures.
* **Screenshot:**
  * the list first, with the records and actions on every state;
  * a paused program whose order was cancelled with it;
  * the last evaluation folded in its row and titled with the program's name;
  * the builder, with the instrument field, three conditions, the THEN row, the limits with their defaults, RUNS AS, "Starts in shadow", and the sentence.
  * At 390, the list comes before the builder, and the condition rows stack.

---

## 8. P5: the bots' entry at a level

### 8.1 The setting

On each bot config, `extras["entry_mode"]` holds only the shape of the level entry. **It holds no live flag:**
```
{"mode": "market" | "level",
 "level": "pool_against" | "po3_edge" | "pullback_atr" | "card_entry",
 "k_atr": 0.5,               # pullback_atr only
 "valid_hours": 8}
```
* `pool_against`: the nearest menu pool on the far side of the mark from the trade (below for a buy), with its stop.
* `po3_edge`: forex only. The Asian edge on the trade's side after London has run it (`map_levels.md` §4, shape B).
* `pullback_atr`: k × 4h ATR back from the mark.
* `card_entry`: the entry of the SMC card that backs the signal, if one does.

`order_presets.PRESET_POLICY` refuses a family the class does not support.

**The go-live record lives in its own table, outside free-form extras.** The HQ bot form writes extras from a raw JSON box, merged over what the config holds (`dashboard/views_admin_hq.py:765`, :840-848). A `"live": true` typed there would need no PIN on a paper config, and on a live config only the PIN for "save a live bot config" (:870-876). That would get around the record gate.
* So the record is `EntryLevelGrant(config FK, family, live_at, by, record_n, mean_value_r, revoked_at, revoked_why)`, in migration `0048_entry_level_grants`.
* It is written **only** by the ACT endpoint (§8.4).
* `hq_create_asset_bot` strips any `entry_mode.live` key, and any key the grant owns, from the posted JSON. A test pins that the HQ save cannot make a level entry live.

### 8.2 In shadow (`bot_entry_levels` ON, no grant)

`execute_entry` (`base.py:5543`) does exactly what it does today: the market order, or its own config shadow (`safety.is_shadow` :125).

After the decision, sent or not, `price_orders.record_would_order(cand, entry_mode)` creates a would-order: `PriceOrder(source="bot", mode="shadow", kind="limit", price=<the level>, stop=<the level's stop or cand.stop>, target=cand.target, expires=valid_hours, baseline={at: now, price: cand.price})`.
* P2's watcher follows it to WOULD_FIRE or EXPIRED.
* P2's grader grades it against the bot's market entry: the walked market entry with the same cost model, so like is compared with like. The live row's realised R, when one exists, rides along as a note.
* **The would-orders show on the bot config page, with their record. They are not on the operator's Working or Shadow tabs**, and they are not in any count.
* An `order_cancel_blocks` entry for the symbol and side (§5.7) suppresses the would-order too.

**Nothing in this shadow changes the bot's order, its size or its row.**

### 8.3 Live (`bot_entry_levels_live` ON and an unrevoked grant for the config and the family)

1. **Re-checked at every live placement:** `bot_entry_levels_live` is ON, the grant is unrevoked, and the config's record is still at or above the gate (§8.4). If any of these fails, the would-order path of §8.2 runs instead.
   * `execute_entry` places a `PriceOrder(source="bot", mode="live")` instead of the market order, and records the skip `ORDER_RESTING`.
   * The holder is the platform, or eToro after P2b on the better side.
   * `propose_entry`'s `ALREADY_OPEN` (:4233-4240) also counts an ARMED, FIRING, WORKING or IN_DOUBT order from this config on this symbol, so the bot does not stack a second idea.
   * An `order_cancel_blocks` entry refuses: "cancelled by the operator until the signal changes".
2. **At fire**, `price_orders.fire_bot_order(order)` re-runs the whole bot path, with an explicit `at_fire=order`:
   * `bot.propose_entry(symbol, decision=<re-checked>, at_fire=order)`. There is a new keyword, `decision=None`; when it is given, `decide()` is skipped and every later gate runs. The decision is re-checked first: the signal that made it must still be ACTIVE and in the same direction, or the order is CANCELLED with "the signal is gone".
   * then `bot.execute_entry(cand, at_fire=order)`, with `_last_look(fail_closed=True, anchor=order.price)`.
   * **`at_fire` excludes exactly that order's pk from `ALREADY_OPEN`, and bypasses the level branch of `execute_entry`.** Without it, the fire's own re-run would refuse its own FIRING order, or rest a new order instead of sending. A test pins that one bot fire calls `market_order` exactly once and creates no new PriceOrder.

   So these gates all run on the bot's own terms **at the moment of sending**: the proof gate, size by proof, the cost filter, the correlation, the daily loss, the open-risk cap, the pool, the venue floor, the timing, the quote, the health and the in-doubt check.
3. **Who cancels a bot's order:**
   * the brakes: `_withdraw_working_while_braked` (`base.py:1011`) also cancels the config's ARMED orders;
   * Telegram `/stop` and `/stopall`;
   * the Morgul brake;
   * the kill switch;
   * the config disabled;
   * the world changed (§5.6);
   * `bot_entry_levels_live` turned OFF, in every world, demo included;
   * the grant revoked.

### 8.4 The gate to go live

`bots/<cfg>/entry-mode/live/` (POST, door ACT) writes an `EntryLevelGrant` only when:
* `bot_entry_levels_live` is ON;
* the config's own shadow record for this family has **at least 30 graded would-orders, filled or not** (a never-filled one grades 0 − r_market), **with a mean `value_r` over all of them above 0**. Thirty is the trade debate's number (`platform_control.py:345`).

The dialog shows the record, the fill rate and the mean. The same threshold applies to a program run as a bot (§7.4), on the mean over all its windows. Revoking the grant (STOP) needs no record.

### 8.5 Files, switches, tests, screenshot (P5)

* **Files:**
  * `base.py`: `propose_entry(decision=, at_fire=)`, `execute_entry(cand, at_fire=)`, the `ALREADY_OPEN` extension, the would-order hook and the live branch in `execute_entry`, the brake;
  * `price_orders.py`: `record_would_order`, `fire_bot_order`;
  * `order_models.py`: `EntryLevelGrant`; migration `0048_entry_level_grants`;
  * `dashboard/views_admin_hq.py`: `hq_create_asset_bot` strips `entry_mode.live`;
  * the config page: the entry-mode block, with its would-orders and its record;
  * `dashboard/views_bots.py` (or the existing bot-config view): the grant and revoke endpoints.
* **Switches:**
  * `bot_entry_levels`, OFF, not live money: it records and grades only. Description: "Off (default). On: a bot whose config names a level entry also records the limit order it would have rested at that level, and grades it against the market entry it took. Nothing it records is sent."
  * `bot_entry_levels_live`, OFF, in `LIVE_MONEY_SWITCHES`. Turning it OFF cancels the resting live orders with words, in every world.
* **Tests first:** `tests/test_bot_entry_levels.py`:
  * Shadow:
    * shadow changes nothing in the order, the size or the row;
    * one would-order per entry;
    * a family not allowed for the class is refused;
    * grading against the walked market entry.
  * Going live:
    * go-live needs the switch, ACT, and 30 graded with a mean above 0 over all of them;
    * `test_hq_save_cannot_set_live`;
    * `test_grant_and_record_rechecked_at_every_live_placement`.
  * At fire:
    * live places an order instead of sending;
    * ALREADY_OPEN counts an ARMED, WORKING or IN_DOUBT order;
    * `test_one_bot_fire_calls_market_order_once_and_creates_no_new_price_order`;
    * the fire re-runs `propose_entry` (patched to refuse; nothing is sent);
    * the signal gone cancels the order.
  * Cancels:
    * the brakes, `/stop` and the kill switch cancel;
    * the switch OFF cancels the resting orders with words, demo included;
    * an operator cancel blocks the symbol and side until the signal changes or 12 h pass.
* **Screenshot:** the config's entry-mode block: the family, the hours, the shadow record (n, fill rate, mean value R over all), the would-orders list, and GO LIVE locked with its reason.

---

## 9. Cross-cutting

**The kill switch** (`kill_switch.execute_kill_switch` :41) gets a new step before the asset sweep (:138):
* every ARMED `PriceOrder` in scope is CANCELLED;
* every ACTIVE program is PAUSED;
* venue-held orders are WORKING rows, and are withdrawn by the existing sweep (:580-594);
* every row the sweep leaves CLOSE_PENDING carries `close_intent` KILL (§3.4);
* the counts go in `results`: `orders_cancelled`, `programs_paused`, `orders_in_flight`.

**FIRING orders are left to finish.** Marking one CANCELLED would not stop its send: `_execute` read the config before the kill disabled it, and the broker leg runs outside any lock (`manual_trade.py:2600-2717`). Instead:
* `fire()` re-reads `config.enabled` and the kill record right before the POST, and the kill disables configs first, so most fires abort.
* **After the main sweep**, so that the emergency flatten is never delayed, the kill switch waits up to 30 s for each FIRING order in scope to leave FIRING. It then closes the trade row that order produced, through the same `_close_asset_trade`, in a second pass over those rows only.
* An order still FIRING after the wait is listed in `errors`: "an order was being sent at the kill: check positions at eToro".

**Morgul guards** (`bot_program/morgul.py`). The new guard `check_price_orders` alerts on:
* an ARMED order whose source has had no fresh price for 30 minutes of open market;
* an IN_DOUBT order older than an hour;
* a FIRING order older than 5 minutes: a worker died mid-fire. It becomes IN_DOUBT, never ARMED or CANCELLED;
* a WORKING order flagged `withdraw_unproven`, and a venue-held order whose cancel was not proven.

`check_stuck_close` (:681) already ignores a row once it is OPEN, so P1 needs no change there.

**The audit chain** (`bot_program/audit.record_event` :36) records: `close_cancelled`, `close_hand_claim`, `price_order_placed`, `price_order_fired`, `price_order_cancelled`, `price_orders_cancelled_bulk`, `price_order_moved`, `price_order_in_doubt_resolved`, `program_live`, `program_paused`, `program_edited`, `entry_level_granted`, `entry_level_revoked`.

**Telegram.** Every new message carries URL buttons only (the `alerts/links.py` rule, :62-70). An order's button goes to `/orders/#po-<pk>`. Any new deep-link shape goes into `DEEP_LINK_PATHS` (:89), with its test.

**eToro's request budget** (`bot_program/engine/etoro_budget.py`, new):
* **One token bucket per eToro key**, in Redis, shared by the Celery workers and the web process.
  * Until M11 is pinned, it is sized from the documented limits: writes 20 a minute and lookups about 20 a minute. These are unmeasured, as `etoro_client.py:345-357` assumes.
  * M11 records whether order POSTs, close POSTs and lookups share one group.
* **Every eToro request a caller makes on purpose spends from it:**
  * the watcher's eToro reads, every fire, the evaluator, P5's placements and the bots' entries;
  * the TAKE TRADE button, which is counted and never refused (the operator is there, and is told when the bucket is low);
  * lookups (`_lookup_once`), cancels and closes.
* **A reserve** (a fixed share; until M11, 6 writes and 8 lookups a minute) may be spent only by closes, close proofs and the kill switch.
  * An entry sender that finds only the reserve left HOLDs ("queued behind other orders").
  * A close is never refused by the bucket, only counted.
* **A 429 on a lookup is now seen.** `_lookup_once` (:2162-2186) uses `self._sess().get` and bypasses `_read`. A 429 there was noted on nothing, and `position_state` turned it into None, an unproven close. It now records the 429 on the venue's health and takes the measured pause (:417-449).
* **What this does and does not claim.** Entries cannot spend the reserve, which keeps headroom for protective closes. Until M11, that is headroom, not a guarantee that an entry can never delay a close.

---

## 10. The order to build, smallest and safest first

1. **P1a, step 1.** eToro's `close_position` in-doubt split (§3.3a), alone in its own commit.
2. **P1a, step 2.** The cancel of a close retried after a refusal, the manager check, the kill marker, the exit hold, the honest words for eToro's accepted close, the hand claim, the WITHDRAW labels, the two-view dialog. No migration, no switch.
3. **P0**, in parallel. First M7 (a-d), M8, M9, M11, M12, M13 and M14; then M1-M6, M4b, M6b and M10.
4. **P2a, step 1.** The TAKE TRADE in-doubt note (§5.9), alone in its own commit.
5. **P2a, step 2.** The shared eToro budget, and lookup 429s on the venue's health (§9).
6. **P2a, step 3.** `PriceOrder` and the watcher: paper and demo, with real money in shadow. The ticket's head and ORDER block, `/orders/`, and the WORKING ORDERS card. On demo, eToro-watched classes fire only after M13.
7. **P3.** Smart prices on the ticket.
8. **P1b.** eToro's close cancel behind its switch, after M7 and M8.
9. **P4.** Programs in shadow; live behind two switches.
10. **P5.** Bots' would-orders in shadow; live per config with the PIN, the grant and the record.
11. **P2b.** eToro MIT behind its switch, after its measurements.

---

## 11. Decisions for the operator

| # | Question | This spec assumes |
|---|---|---|
| D1 | "Cancel the closing order possibility": cancel a pending close (this spec), or remove the close button? | cancel a pending close |
| D2 | Does an order's GTC end at 30 days? | yes: the platform cancels at day 30 and says so |
| D3 | At fire, are the daily stop and the open-risk cap refusals even when accepted at placement? | yes, and an unreadable book is a HOLD, never a pass |
| D4 | The default worst price: 0.10 R past the price for a stop entry, 0.02 R for a limit? | yes, editable per order |
| D5 | May a DEMO order of the operator's fire with only `price_orders` ON (no `_live` switch)? | yes: demo is the measurement ground. Its world is re-checked at fire, and the demo-to-real flip is refused while it rests |
| D6 | The bot go-live threshold: 30 graded would-orders with a mean value above 0, over all of them? | yes, as the trade debate |
| D7 | May the operator cancel one leg of a kill-switch flatten? | no, in P1; a new trade is the way back in |
| D8 | When eToro cannot hold an order (a stop entry always; a limit before P2b), may the platform hold it and send a market order when touched? | yes on paper and demo; on real money, in shadow until `price_orders_live` is turned on |
| D9 | Which classes get smart prices first? | crypto and forex (fresh streams; levels already judged on forex), then index and commodity once eToro's rates are measured (M13), stocks last |
| D10 | The bots' level entries: shadow first, then live per config with the PIN once its record passes D6? | yes |
| D11 | A TAKE TRADE market order sent while the market is shut is withdrawn after 26 wall-clock hours, so a Friday-evening order is withdrawn on Saturday and never fills. Keep that (the ticket and the row now say it), or keep queued market orders until the open? | keep the 26 h and say it plainly |
| D12 | A cancel of a bot's order blocks that bot on that symbol and side until its signal changes, or for 12 h? | 12 h |

---

## 12. Left out on purpose

* One-cancels-other between two orders, and orders on one asset conditioned on another asset's price. The vocabulary in §7.1 can take them later; nothing in this build needs them.
* Trailing entry orders, and scale-in ladders (several levels for one idea).
* A stream-driven watcher (Binance, Finnhub, OANDA through `signals/fast_rules.dispatch_event`) for second-level triggers. The read in §5.5 is honest about what it misses, and this is the first thing to improve once the shadow record says the misses cost money.
* Orders at a price on the options lane.
* Partial cancels of a partly filled close.
* Adopting a position found after an in-doubt send. The platform cannot adopt it; the operator closes it at eToro, then resolves the order (§5.6a).
* Moving an order by dragging its line on the chart. MOVE is on the row (§5.7).
* Counting the 26 h withdrawal of a queued market order in open-market hours (D11).

---

## 13. Review log: every finding, and where it landed

Severity: B blocking, S should-fix, N nit. Every finding was applied. None was rejected outright. Where the fix differs from the one proposed, the reason is in the last column.

| # | Finding | Sev | Where it landed | Changed from the proposed fix, and why |
|---|---|---|---|---|
| 1 | P1: nothing checks that the row will be managed after a cancel; the kill switch leaves no marker | B | §1.1 care row; §3.2 the first extra refusal; §3.3 steps 3 and 8 (`_manager_refusal`, re-checked before the write); §3.4 the KILL stamp in `_close_asset_trade` and at :794-811; §3.7; §3.12 | The manager check is also re-read under the write lock, since a config can be stopped during the cancel |
| 2 | P2: world and mode stored at placement, never derived at fire | B | §1.1 world row; §5.4 CANCEL group; §5.5 step 2; §5.6 step 2 (`world_now`) and step 5 (the `pin_ok` rule); §5.8 the two refused flips; D5; §5.13 | Standing down (live to paper) is not refused: `arm_manual_lane`'s own rule is "stopping must never be gated". It cancels the lane's live orders instead |
| 3 | P4: one-order rule misses FIRING, IN_DOUBT, WORKING and open trades; level conditions refire; limits optional; the evaluator goes around the budget | B | §7.1 edge-triggered firing, mandatory limits with defaults, one live idea per program; §7.3 every order through the shared budget; §9 the budget; §7.6 tests | none |
| 4 | P2: IN_DOUBT resolution adopts nothing and reads positions only | B | §1.1 in-doubt row; §5.3 `reserved_risk`; §5.6a whole; §5.9; §5.10; §5.13 | One hand act only ("nothing from it is at eToro"). There is no "found it" act, because the platform cannot adopt a position (§12) |
| 5 | P2: a fire into a shut eToro market becomes a queued order that fills at the gap | B | §1.1 timing row; §5.4 HOLD list (`fail_closed` clock, eToro quote age and gap rule); §5.6 steps 4 and 6; §5.13 | The unproven-withdrawal case is merged with finding 22 (see there) |
| 6 | P2b: a resting MIT fills into the daily stop and across weekend gaps | B | §5.15 the tick's standing gates (daily stop, cap, unreadable book means withdraw); withdrawal before a shut; `rest_through_shut` only after M6b | none |
| 7 | Kill switch vs FIRING orders | S | §9 kill switch; §5.6 steps 1 and 5 (compare-and-set, re-read before the POST); FIRING older than 5 min becomes IN_DOUBT; §5.13 | The 30 s wait runs **after** the main sweep, not before it, so the emergency flatten of every other position is never delayed |
| 8 | At fire, a fail-open book read would pass | S | §5.4 HOLD list; §5.13 `test_preflight_raising_at_fire_holds_and_sends_nothing`; D3 | none |
| 9 | P1 "Retrying" after a timeout looks like a refusal | S | §3.2 new sub-state "Retrying after a transport failure"; resting-close check on Saxo and Alpaca; §3.12 | none |
| 10 | Shadow guarantee not pinned | S | §1.2; §5.4 `judge()`; §5.8 the mode stored once; §5.13 two tests | none |
| 11 | P4: PIN and switch doors for edit, copy, create, and switches OFF | S | §7.2 `mode`; §7.4 doors; §7.5; §7.6 switch OFF in every world; §8.3 | none |
| 12 | P5: the live flag in extras can be typed in the HQ form | S | §8.1 `EntryLevelGrant` (migration 0048); the HQ strip; §8.3 re-check at every placement; §8.5 tests | The record is its own table, not a field on `AssetBotConfig`: it carries who, when and the record, and can be revoked |
| 13 | P5/P4: the bot fire refuses its own order or rests a new one; a program does not trade "at a quarter" | S | §8.3 step 2 `at_fire`; §7.1 "Runs as" corrected (forced to paper until promoted, never by code); §1.1 proof row; tests | none |
| 14 | P4: "crosses" memory across gaps; a market action has no price for the cap | S | §7.1 the crosses row (memory older than 2 periods, or spanning a shut); a market action's price and worst price; tests | none |
| 15 | P1b: DELETE unproven, "first read after the open" | N | §3.5 the one rule for OPEN | Superseded by finding 17: neither branch now relies on a clock. The close-order read decides |
| 16 | `pin_door` comment reads as storing the PIN | N | §1.4; §5.3 `pin_door`, `pin_checked_at`; §5.13 `test_pin_never_stored` | none |
| 17 | P1a hand cancel, and P1b None, book OPEN on a read that cannot see the close order | B | §2 P1a and P1b rows; §3.5 "why the position read cannot..." and P1a claim only; P1b's one rule; M7 extended (a-d); §3.10; §3.12 | none |
| 18 | P2a: the watcher's price source is neither fresh nor eToro's for most classes | B | §5.5 step 3 (`watch_source` per class, the near band, eToro's reads and W); §5.1 the holder line; M13; the `/rates`-forbidden test dropped; §5.13 | none |
| 19 | P1: eToro `close_position` has no in-doubt split | S | §3.3a (first commit of P1a); §3.2; §10 step 1 | none |
| 20 | P1: "Queued at eToro" words state what cannot be known; no eToro-session clock exists | S | §3.2 renamed "Accepted at eToro, not confirmed"; §3.5 words; M14 | none |
| 21 | P2a: IN_DOUBT on eToro must not clear on flat reads; measure `ordersForOpen` | S | M12; §5.6a; §5.9 (the bots' own note follows M12 in the same commit) | none |
| 22 | P2a: a status-11 answer to a fire must be a HOLD | S | §5.6 step 6 | Findings 5 and 22 disagreed on the unproven case ("never WORKING" against "WORKING plus an alert"). The trade row stays WORKING, so every reader counts it and the tick keeps trying, but the order is flagged `withdraw_unproven`, shown red, alerted and reserved. It is never treated as an accepted outcome |
| 23 | P2a: the 2/min budget does not separate eToro's quota; lookup 429s are invisible | S | §9 the budget, with its reserve; `_lookup_once` on the venue's health; M11 in P0 for P2a, extended | "Never delay" is not claimed; the venue's grouping is unmeasured, so the text says headroom, not guarantee |
| 24 | P2a: the deterministic id never reaches eToro | S | §5.3 `fire_n`, `client_order_id`; §5.6 step 5; M9 in the P2a set; the test renamed to assert the header sent | The UUID is per send attempt (`po{pk}:{fire_n}`), so a re-fire after a HOLD is never deduplicated by eToro against the earlier attempt |
| 25 | P2b: measurements missing (M4b, M6b), M3 for status 12, thin [C] support | S | §2 P0 table; §5.15 | none |
| 26 | P1b: the DELETE would pass the first-segment attestation unmeasured | N | §3.5 P1b; §3.8; §3.12 `test_delete_on_real_raises_without_attestation_whatever_the_switch` | none |
| 27 | TAKE TRADE note written on not-sent errors | N | §5.9 the first bullet; §5.13 | none |
| 28 | eToro bid/ask "0.0" passes a side test | N | §5.4 HOLD; §5.6 step 4; M13 records the row's keys; §5.13 | none |
| 29 | Ticket title and message say "executes immediately" on non-market and shadow orders | B | §5.1 head table (server-built `head`); §5.12; §5.14; `mockups/ticket.html` renders the real live title, the red frame and the shadow head | none |
| 30 | P1 retry-or-cancel dialog: two opposite acts in one foot, one PIN | S | §3.1; §3.6 two views; mockups | none |
| 31 | The hold choice cannot be built with `ask()` | S | §3.6 | Took the alternative the finding offered: `closeFlow` builds the pending dialog, as `sizeDialog` does. `ask()` is unchanged, and the earlier `opts.alt` is dropped |
| 32 | One AT A PRICE link cannot know the side; the chart copy unspecified | S | §5.1 "On the deal ticket" | none |
| 33 | Price pre-filled at the legal edge | S | §5.1 price (nearest tappable legal preset or empty; too-close refusal); §6.1; tests | none |
| 34 | A chip tap silently changes four things | S | §6.1 (chips under the price, the kind named, the Set line, the flash) | none |
| 35 | "Send only within 13" | S | §5.1 kind line, "LIMIT · ON TOUCH", More with "Worst price you accept" | none |
| 36 | END OF DAY placed while shut | S | §5.1 expiry; §5.13 `test_eod_placed_on_saturday_is_next_session_per_class` | none |
| 37 | Working-orders card is ~460 px per order on a phone | S | §5.7 the table (`sv-stack--pairs`, `po-sum` with details behind a tap, 3 rows, `#working-orders`) | none |
| 38 | Shadow orders mixed into the operator's list and count | S | §5.7 tabs; counts only orders that can send; bot would-orders on the config page (§8.2) | The tabs are "Working" and "Shadow", not "Live": on this platform LIVE means real money (the deal ticket's ● LIVE), and the tab also lists paper and demo orders that can send |
| 39 | No order history | S | §5.7 the `/orders/` page, its Recent 48 h tab, `#po-<pk>` links from Telegram | Both proposals taken: the page, and a "recent 48 h" link on the card |
| 40 | No bulk cancel | S | §5.7 CANCEL SELECTED, CANCEL ALL ORDERS (STOP) | none |
| 41 | No MOVE | S | §5.7 MOVE (ACT, atomic) | MOVE only for a platform-held ARMED order: eToro cannot swap a venue-held order atomically. Dragging the chart line is left for later (§12) |
| 42 | A cancel of a bot's or program's order does not stick | S | §5.7 `order_cancel_blocks`, a program's day consumed and the "also pause" box; §8.2, §8.3; D12 | none |
| 43 | Pausing a program leaves its armed order | S | §7.4 doors (PAUSE and CANCEL cancel its ARMED orders, named in the dialog); mockups | none |
| 44 | Builder lacks symbol, edit, cancel and copy | S | §7.4 (instrument field, EDIT, COPY TO… and CANCEL on every state, record per version) | none |
| 45 | Program page: the builder before the list on a phone | S | §7.4 (list first, + NEW PROGRAM); mockups | none |
| 46 | "8 h after it fires" is ambiguous | S | §7.1 expiry; §7.4 sentence; the list shows the absolute moment | none |
| 47 | Program headline overstates by leaving missed windows out | S | §7.3 the record's headline; §8.4 gate on the mean over all | none |
| 48 | A queued market order shows "queued for the open", but is withdrawn before it | S | §5.7 and mockups: the row says it cannot fill; D11 | Took the words option; changing the 26 h rule is the operator's decision (D11) |
| 49 | Builder MODE control | N | §7.4 (no MODE; "Starts in shadow") | none |
| 50 | Queued-close dialog wording | N | §3.5 (KEEP THE CLOSE; CANCEL AT ETORO…; the interim row line) | The interim line names no check time: after finding 17, nothing returns the row to OPEN in P1a |
| 51 | "Levels" label | N | §5.7 `data-label="Stop · Target"` | none |
| 52 | MARKET state not drawn | N | §5.1; §5.14 item 1; `mockups/ticket.html` | none |
| 53 | Words on chips and controls; small touch targets | N | §6.1 chip lines and plain reasons; §7.4 40 px controls; the program's name on its evaluation | none |
