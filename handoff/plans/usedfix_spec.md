# Used-capital fixes: the build spec (from the 2026-11-01 investigation)

Line numbers refer to ba71a9f (threefix C2) and must be re-checked. Decisions taken for the operator: fix 7 NO (outside money is shown, never gated); fix 4 YES (a lane stood down to paper still closes its real rows); no adoption of positions tied to Sauron's own in-doubt orders; the gates value an eToro row at max(Sauron's capital_at_work, eToro's amount for its position id).

Status on branch claude/usedfix: U1 = fixes 1 and 2 (8e1d248); U2 = fixes 3, 4 and 5 plus client_for_row for the drain, the kill switch, the CLOSE button, the reconcile and the manage tick (building); U2b = the demo short-proof runner no longer waits on a real row whose close eToro holds queued (close_order_working) or the operator cancelled at eToro; U3 = fix 6, the outside figure position by position with its own 'eToro holds more than Sauron counts on Sauron's own rows' line, the max() valuation in the gates, and eToro holdings with no mark print a dash, never 0 (treasury command, /positions/ At the broker card).

## Fix 1
**cause**

C02(a) and C16: two booking paths leave nothing. First, when the order POST raises after the send, the TAKE TRADE / instrument-page ticket books no row, writes no note and alerts nobody (manual_trade.py:2956-2968). The bot lane writes a note and alerts (base.py:6587-6611). Second, a 5xx on the order POST is read as a refusal on both lanes (etoro_client.py:2524-2529), so an order eToro may have taken leaves no trace. Today's consequence (test_R2): after an in-doubt ticket, a second ticket on the same symbol sends a second order and books a second row.

**change**

(1) bot_program/manual_trade.py:_execute, the except after client.market_order (manual_trade.py:2956-2968). When getattr(e, 'in_doubt', False):
- call bot._remember_in_doubt(inst.symbol, reference) on the lane's own AssetBot (bot = make_bot(cfg), manual_trade.py:2484; base.py:1668);
- call notify_staff with the bot lane's title and body (base.py:6594-6605);
- call bot._reread_account_soon(client, why='order in doubt') (base.py:7522), so eToro's cells are read again within seconds.
The ticket keeps its 'MAY have reached the broker' text.
(2) Same function, under the lock beside the _dup() re-check (manual_trade.py:2858), and in _preview (bot at manual_trade.py:1541): refuse while bot._in_doubt_note(symbol) is fresh and bot._settle_in_doubt(symbol, note) does not clear it. Use propose_entry's words (base.py:4264-4276).
(3) bot_program/engine/etoro_client.py:EtoroTrader.market_order (etoro_client.py:2513-2529): a 5xx answer to the order POST raises EtoroOrderInDoubt(rid, symbol, 'HTTP <code> ...', client_order_id=...) instead of RuntimeError('eToro refused (5xx)'). The venue-health note stays. A 429 and every 4xx stay refusals.

**money_direction**

No used, free or gate sum moves. The fix adds refusals only.
- The ticket refuses a resend of that symbol while the note is fresh: at most IN_DOUBT_QUIET_HOURS, 12 h (base.py:1645); about 2-3 minutes when eToro reads flat twice past its 60 s lag (base.py:1780, etoro_client.py:366).
- A 5xx quiets the symbol the same way instead of being resent on the next tick.
- The re-read lets the pledge gate see eToro's used margin with the in-doubt order within seconds instead of at the next 300 s sync. It is tighter sooner, by exactly what eToro holds and never more.

**c3_interaction**

C3 already shows what eToro holds for such an order inside 'outside Sauron', because there is no row. Without a label, the split calls Sauron's own order 'outside Sauron'. Add to C3's builder: an outside position, or the held-order part, on a symbol with a fresh entry_in_doubt note on any of the user's configs reads 'may be Sauron's order of <time> that did not come back'. No number moves between the split's parts.

**tests**

Red at ba71a9f (I ran them; each FAILS), in /home/user/Sauron_Vision/.claude/worktrees/usedprobe/tests/scratch_used/test_fixspec_red.py:
- FixSpecRed.test_R1: the ticket's ReadTimeout leaves no note and 0 alerts.
- test_R2: 2 POSTs; the second ticket booked a second row.
- test_R3: bot lane 502, skip 'order_error', no note.
- test_R3b: ticket 504, no note.
Port them to threefix as a new tests/test_order_in_doubt_lanes.py.
Must stay green: tests/test_venue_health.py (the in-doubt POST tests at :342-400 and TheInDoubtNoteSettlesTests) and tests/test_take_trade_live.py. A grep of tests/ finds no test that pins a 5xx order POST as 'eToro refused'.
Run log for the whole file: /tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/used_fixspec/run_ba71a9f.log (17 tests: the 11 R tests fail, the 6 guard and command tests pass).

## Fix 2
**cause**

C16, a held order with no row. The in-doubt note's settle reads /portfolio only (base.py:1783-1845), and a held order is in no /portfolio row (deploy/ETORO_DEPARTURE.md:447-454). Two flat reads therefore clear the note while eToro still holds the order. The symbol trades again, and at the next open the order fills as a position with no row (C02).

**change**

(1) bot_program/asset_engine/base.py:AssetBot._settle_in_doubt: a flat read counts only when all three hold:
- C3's frozen-cash cell (EtoroAccount.last_frozen_cash, stored from accountFrozenCash) was read after the note;
- it was read in the account's world;
- it is no larger than Sauron's own WORKING eToro rows explain (sum of qty_requested x price / leverage, plus a fee tolerance).
Otherwise the note stands, saying 'eToro holds X of frozen cash no Sauron order explains'. A cell never stored (None), or a non-eToro client, keeps today's rule.
(2) C3's split builder (bot_program/etoro_used.py): carve 'held at eToro, no Sauron row' = max(0, frozen cash - Sauron's WORKING rows' counted capital) out of 'outside Sauron', with its age. Display only.

**money_direction**

No sum or gate moves. The symbol stays quiet longer while eToro holds an order no Sauron row explains: until a read shows the order gone, at most 12 h. No second order is sent on that symbol meanwhile. The pledge gate already counts the held order through last_used_margin (base.py:7584; test_skeptic_c16_held b2: used = frozen = frozenAmount).

**c3_interaction**

Needs C3's last_frozen_cash. Today C3's split would show the held order only as an unexplained remainder of 'outside Sauron', with no position line, because a held order is never in /portfolio. (2) names it. It must not count Sauron's own WORKING rows twice: C3 already counts them under 'opened by Sauron', since a WORKING row is OPEN (base.py:142-152).

**tests**

Red at ba71a9f: FixSpecRed.test_R8. eToro's cells say 2000 frozen (illustrative) and there is no WORKING row, yet the note cleared after two flat reads: FAIL.
On threefix after C3, add a split test: frozen 2000 and no WORKING row give a held part of 2000 and a positions part of 0.
Must stay green: tests/test_venue_health.py TheInDoubtNoteSettlesTests. Those tests have no frozen cell, so today's rule applies.

## Fix 3
**cause**

C03/C08 route (a). While eToro holds a queued close, a drain pass whose order lookup fails spends an attempt:
- the proof is None;
- eToro cannot cancel a close-order id, so cancel_order answers False (etoro_client.py:2727-2732);
- pending_closes.py:1815-1849 then books 'could not be cancelled, refusing to stack' as a failed attempt, although nothing was sent.
Blocked passes never reset the counter. 12 such passes give ERROR (pending_closes.py:49, :1355-1361), and the row leaves every sum while eToro holds it. The operator's own CLOSE_PENDING a live forex row row has already spent 1 attempt this way.

**change**

bot_program/pending_closes.py:retry_trade_close, just before the cancel gate (pending_closes.py:1815). When all three hold:
- CLOSE_ORDER_WORKING_KEY is set;
- the venue declares it cannot cancel a close order (add EtoroTrader.CANCELS_CLOSE_ORDERS = False rather than testing the class);
- the book did not read flat this pass;
call _note_close_blocked (pending_closes.py:1286) and return False. No attempt is spent, and the words are those of the proof == 'open' block (pending_closes.py:1725-1732). The flat, lag and venue-proved paths above it are unchanged.

**money_direction**

The row stays CLOSE_PENDING and counted while eToro holds the queued close. Compared with today:
- used_live, the exposure gate and the open-risk gate keep the row's capital_at_work and its risk at the stop instead of dropping them after the 12th failed read (test_R4: 2000 kept, illustrative; 0 today);
- the pledge gate is unchanged, since eToro's cells hold the position either way;
- nothing is sent that is not sent today.

**c3_interaction**

The row stays in C3's 'opened by Sauron' instead of moving to 'Sauron stopped closing'. C3 puts CLOSE_PENDING rows in the platform list, and its Treasury shows the row as CLOSING.

**tests**

Red at ba71a9f: FixSpecRed.test_R4. Over 240 passes, 12 failed lookups give ERROR with attempts 12, and used_live and the gate read 0 while eToro holds the position: FAIL.
Guards that must still hold:
- test_skeptic_c03_error.test_control_queued_close_healthy_lookups (100 healthy passes, 0 attempts);
- test_skeptic_c08_shut.test_k1b (a REFUSED close still reaches ERROR in 12 passes);
- tests/test_close_path.py and tests/test_venue_exit.py.

## Fix 4
**cause**

C03/C08 route (b). The drain picks the client by today's routing: client_for_symbol(user, symbol, trade.config) (pending_closes.py:1669). Two operator actions hand a live eToro row a PaperTrader:
- a lane stood down to paper (broker_router.py:255; arm_manual_lane has no open-row check);
- an unticked eToro class box (broker_router.py:272; commodity has no other venue).
Every pass then spends an attempt (pending_closes.py:1679-1699). The row reaches ERROR in 12 passes, about 1 h, with eToro still holding the position.

**change**

(1) bot_program/engine/broker_router.py: new client_for_row(trade, purpose='trade'):
- a live row stamped broker 'etoro' (base.py:6772-6821) gets the user's EtoroTrader in the world its broker_env names, whatever the lane's mode and class box;
- it gets a PaperTrader when the keys are gone or the account now trades the other world;
- every other row goes to client_for_symbol, as today.
(2) pending_closes.retry_trade_close uses it (pending_closes.py:1669).
(3) Its live-row-plus-PaperTrader branch (pending_closes.py:1679-1699) calls _note_close_blocked instead of _after_failed_attempt: nothing was sent and nothing was refused.

**money_direction**

The row stays CLOSE_PENDING and counted (test_R5: 2000 kept, illustrative; 0 today after about 1 h). The gates move as in fix 3.
One order-path change, stated plainly: on a lane stood down to paper, a pending close that nothing holds at eToro is now SENT to eToro. Today nothing is sent and the row is abandoned. This is closes only: no entry path calls client_for_row.

**c3_interaction**

Same as fix 3: the row stays in 'opened by Sauron', and this route no longer feeds 'Sauron stopped closing'.

**tests**

Red at ba71a9f, both FAIL:
- FixSpecRed.test_R5 (lane on paper): ERROR at pass 12, and 0 lookups were asked of eToro.
- test_R6 (box unticked): ERROR at pass 12.
Existing test that must change with the fix: tests/test_exit_truth.py PaperFallbackProvenanceTests.test_the_retry_loop_refuses_to_book_a_simulated_fill asserts that close_retry_last_error names PaperTrader (test_exit_truth.py:607). It should assert close_blocked_why instead, and that no attempt was spent.
Unchanged: tests/test_trade_session_contention.py (the IBKR session-busy branch).

## Fix 5
**cause**

C03/C08 residue. A row can still reach ERROR by route (c), when eToro refuses the close POST 12 times. It then leaves every money reader, because all of them filter OPEN/CLOSE_PENDING (services.py:386; risk_gate.py:530 and :889; manual_trade.py:1813-1817). Yet the platform itself calls such a row 'still open at the broker' (views_close.py:167-183, alarm.py:605-618, horde.py:724-728).

**change**

One predicate, e.g. portfolio/services.py:abandoned_still_held(user). It keeps rows with paper=False, status ERROR and closed_at null when:
- the carrier's stored holdings (C3's snapshot, with position ids) list the row's broker_position_id; or
- that snapshot is missing or older than TRACKING_FRESH_SECONDS (capital_truth.py:451).
Read by:
- capital_summary, in used and used_live (services.py:384-398);
- risk_gate.open_capital_at_work, in live_total (risk_gate.py:528-545);
- risk_gate.open_risk_state, at the row's stop (risk_gate.py:888-899);
- manual_trade._preview, in committed (manual_trade.py:1813-1817).
Not read by _pledged_since, the drain, reconcile or the manage tick.

**money_direction**

Tightens, in display and in gates.
- Exposure gate: plus the capital_at_work of each abandoned row eToro still lists (test_R7: +2000 for one 0.5 oz gold at 1x, illustrative).
- Open-risk gate: plus qty x |entry - stop| x value_per_unit at the row's stop (test_R7: +60), or the whole notional when there is no stop.
- TAKE TRADE lane pool: plus its own abandoned rows.
- Pledge gate: 0. In test_G1, used is eToro's cell and pledged since the read is 0; SETTLE_S is 3 s (etoro_cells.py:67).
- Pages: used_live goes up and free_live goes down by the same amount.

**c3_interaction**

C3 shows these rows as 'Sauron stopped closing, still open at eToro'.
- Its part must use this same predicate, not every ERROR row. Then the split, the pages and the gates agree, and a row eToro closed at the reopen (test_skeptic_c03_error test_a, part d) drops from both.
- Put the predicate in portfolio/services.py and have etoro_used import it, so C3's guard test (no gate module reads etoro_used) stays true.
- If C3 takes 'opened by Sauron' from capital_summary instead of its own row walk, it must subtract this part, or the split counts it twice.

**tests**

Red at ba71a9f: FixSpecRed.test_R7. An ERROR row eToro still lists reads used_live 0, open_capital_at_work 0 and open_risk 0: FAIL.
Guards, green now and after:
- FixSpecGuards.test_G2: an ERROR row eToro no longer lists counts 0.
- test_G3: 24 drain passes and a reconcile send nothing for an ERROR row.
- test_G1: the pledge gate reads eToro's cells and charges no old row.

## Fix 6
**cause**

C02(c). An eToro position the client cannot name reads 'ETORO:<id>'. Only 8 of the 32 catalogue commodities have an eToro spelling, and every class is affected.
- The config loop counts such a position 'unreadable' and never reports it (reconcile_asset.py:995-1005).
- The account-entry path, the only one a user trading only through TAKE TRADE gets, drops it silently (reconcile_asset.py:1131-1154).

**change**

bot_program/reconcile_asset.py:_broker_open_symbols (reconcile_asset.py:156-211) returns the unnamed positions themselves, not only their count: position id, side, units, open rate and multiplier (get_positions keeps the id, etoro_client.py:1804-1824).
reconcile_unknown_positions then reports each one whose position id no live row's broker_position_id claims, in both the config loop and the account-entry path. The alert carries side, units, rate and multiplier, so the position can be found in the eToro app.
Report only; the 3 h dedupe stays.

**money_direction**

Report only. No sum and no gate moves.

**c3_interaction**

C3 already lists such a position under 'outside Sauron' (Treasury BROKER ONLY ETORO:<id>, broker_vision.py:361-362) and compares by position. This fix makes the alert fire for it too. If C3's per-position sweep already reports it, test_R9 passes after C3 and nothing more is needed.

**tests**

Red at ba71a9f: FixSpecRed.test_R9. An unnamed position placed in the app, with only the TAKE TRADE lane armed, gives unclaimed 0 and 0 alerts: FAIL.
Existing sweep tests that pin 'unnamed is not unclaimed' narrow to: an unnamed position whose id a row claims is not reported.

## Fix 7
**cause**

C02 and C16 in the gates. A position or held order that eToro holds with no row is in eToro's used margin and in the pledge gate (base.py:7584). It is in neither the exposure gate nor the open-risk gate, which sum rows only (risk_gate.py:528-578, :888-913).

**change**

OPERATOR DECISION: not to build without his written yes (used.md F7). portfolio/risk_gate.py:open_capital_at_work and open_risk_state each add one live line, 'at eToro, outside Sauron'. It equals the amounts of positions no row claims, plus the frozen cash no Sauron order explains (fix 2). It comes from cached columns, is dated, and uses the same builder as C3's split.

**money_direction**

Tightens.
- Exposure gate: plus the outside amount.
- Open-risk gate: plus the same amount, counted whole because Sauron knows no stop for it.
- Pledge gate: 0, since the amount is already in last_used_margin.
He asked for more room this week (issue 2), so this is his call.

**c3_interaction**

It reads C3's outside figure, so it is only right once that figure is built position by position (see the open question on per-row differences). A residual figure would also charge the differences on Sauron's own rows.

**tests**

Red at ba71a9f: FixSpecOperatorDecision.test_R10. An outside gold of 2000 (illustrative) gives open_capital_at_work 0 and open_risk 0: FAIL.

## Open questions (as found)

- Operator decision, fix 7: should the exposure and open-risk gates count money eToro holds outside Sauron? It tightens both by exactly C3's outside figure. The pledge gate already counts it (base.py:7584).
- Operator decision, fix 4: on a lane he stood down to paper, a pending close that nothing holds at eToro would now be sent to eToro. Today nothing is sent and the row is abandoned after about 1 h (pending_closes.py:1679-1699). Is 'stand down' meant as 'no new entries, keep closing'?
- Operator decision: should Sauron ever book a row for a position it can tie to its own in-doubt order? Today it never adopts one (base.py:1789-1793), because eToro's order lookup cannot find the reference (etoro_client.py:745-752).
- His 2026-11-01 gap is not one of these four causes: every eToro holding pairs with a counted row, a live forex row included (CLOSE_PENDING, services.py:386). The command may show 'eToro minus Sauron' above zero on some of his own levered forex rows. If so, C3's 'outside Sauron', computed as a residual (eToro used minus Sauron's rows), would absorb that difference and call Sauron's own rows' margin 'outside'. Ask the C3 builder to compute 'outside' position by position, from unmatched positions plus unexplained frozen cash, and to print 'eToro holds more than Sauron counts on Sauron's own rows' as its own line. Then decide whether the gates should value an eToro row at the larger of Sauron's figure and eToro's amount. That is protective and tightens by the difference.
- To check on threefix: when eToro is unreadable, the command falls back to C3's snapshot keys 'position_id' and 'amount'. I did not read threefix (rules). If C3 named those keys otherwise, change the two p.get keys in that fallback branch. Today's snapshot has neither key, so it prints '-'; tested in OperatorCommand.test_CMD_etoro_unreadable_falls_back_to_the_stored_holdings.
- Out of scope, same pattern as fix 4: kill_switch.py:536, manual_close.py:345/510/534 and reconcile_asset.py:344/609/866 also use today's routing for a live row. The manage tick refuses to manage a live row on a PaperTrader (base.py:1090-1110). So a lane stood down to paper leaves its live rows unmanaged until it is re-armed.
- Not in this spec: booking an ERROR row CLOSED once eToro proves the position gone. That books a realized P&L at the time of the proof, which the daily-loss window would read. Fix 5 instead drops such a row from the sums once a fresh snapshot no longer lists it.