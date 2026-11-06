# eToro-grade prices with harmless source switching: final spec

*2026-11-06. Judge's synthesis of two independent designs (a fidelity lens and a safety lens). Read-only work: nothing here called eToro, a broker or a model API, and nothing was written into a git worktree.*

**Base.** main `d81a035`. In flight: `claude/etbudget` (local `3cff385`, rebased on main; the worktree's HEAD `93fa656` has the same tree), `claude/pnltruth` (local `a08c87b`, committed on its branch, not merged).

**Also in flight, uncommitted (found by the verifier, §10).** The etbudget worktree holds work in progress for the interim cadences: `bot_program/etoro_quotes.py` (untracked, 2026-11-06 10:43) and a beat `refresh-etoro-quotes` every 30 s that **writes eToro's rates into LiveQuote under the source `etoro` (rank 70)** for the instruments of open real rows; the sync at 60 s; the forex poll at 300 s. This collides with I2 as first written. §3.3 harm 29, I2, P-c and F11 now account for it.

**Markers.**
- ✓ = re-read in the code, or checked offline, on 2026-11-06 for this spec.
- (map) = taken from the code maps, not re-read.
- [E#] = an eToro fact in §2.1.
- Paths with no prefix are on main. `[BUD]` = the etbudget worktree. `[PNL]` = the pnltruth worktree.

---

## 0. Decision record

### 0.1 Scores (1 to 10; the weighted total follows the operator's two orders)

| Criterion (weight) | Design 1, fidelity lens | Design 2, safety lens |
|---|---|---|
| Fidelity to eToro (20%) | **9.** Live P&L restarts from eToro's own figure every 10 s, so it is exact there; bot-side stops act in about 1 s | **8.** An absolute P&L formula with fees kept beside it; bot-side stops act within 15 s |
| Harmless source juggling (25%) | **7.** One store merged by eToro's time. But today's "a disagreeing outside quote blocks protection" stays until its F6 (after the stream ships), and its last phase makes LiveQuote a composite that puts eToro and outside feeds back in one row | **9.** Separate stores per channel; types that stop an outside quote reaching money code; the reference block is removed first; a watchdog catches a topic that has gone silent |
| Money safety (20%) | **7.** Closes go out without a price, but nothing stops an unpriced loss vanishing from the daily-loss gate (the gate skips unpriced exits ✓ `portfolio/risk_gate.py:671-678`). The feed process itself queues the guard's actions | **9.** Protection comes first; a pending exit counts as a provisional loss and never as a gain; the feed is kept off every order path |
| Feasibility on verified facts (10%) | **7.** The feed resolves unknown ids through /search, the read whose 429s once made eToro SICK (✓ `etoro_client.py:415-423`). A Lua merge, plus a LiveQuote migration at the end | **8.** Fewer moving parts and known ids only. But "REST is LIVE only while eToro's Date is ≤ 5 s old" degrades every quiet market, and that contradicts its own halt rule |
| Latency achieved (10%) | **9** | **7** |
| Request budget (10%) | **7.** /search from the feed, up to 12 a minute | **9.** Watchdog 4 to 12 GETs a minute, no /search, P&L reads at the lowest priority |
| Effort (5%; higher means less) | **5** | **6** |
| **Weighted total** | **7.5** | **8.4** |

**Verdict.** Design 2 is the skeleton: order 2 asks for harmlessness *by construction*, and Design 2 is the one that builds it into types, stores and order of shipping. Design 1 supplies the fidelity parts that make it "same grade".

### 0.2 What this spec takes from each

**Kept from Design 2 (the skeleton)**
- Protection never waits for a price, and no outside quote ever blocks protection. This ships first, before any stream exists.
- One authority per instrument, fixed by affinity. Each eToro channel keeps its own store; Sauron picks the newest at read time. The feed never writes LiveQuote; the one eToro writer there today (etbudget's interim beat, P-c) is retired at the end of F11, once no consumer needs it.
- Type separation (`VenuePrice` vs `ReferenceQuote`) and AST pins. Money code has exactly one way to get a price.
- A REST watchdog that catches a stream topic that is "behind". Trust is lost quickly and regained slowly. Alarms fire only for lasting problems in an open session.
- The daily-loss gate counts a pending exit as a provisional loss that is never positive.
- The feed's REST reads are background reads at P5 until F9 (P3 for held instruments only from F9), on known ids only, with no /search, and they honour Retry-After. Before F9 they never write the engine's rates cache.
- Harm counters (evidence before any PIN), decision replay, the private stream used only as a hint, and a 15 s manage loop.

**Grafted from Design 1**
- eToro's own `/pnl` figure on screen early, before any stream (F4). This settles the operator's P&L complaint (2026-11-06) within about 10 to 20 s.
- Live P&L as "eToro's last figure plus the change since then". It is exactly eToro's figure at each eToro figure, and it carries fees and any other constant through.
- Freshness by confirmation age (the last evidence that a price is still eToro's current one), never by Sauron's write time.
- Every channel store is written by compare-and-set on eToro's Date, so no store moves backwards.
- "An outside quote can only make Sauron look again": one P0 read of eToro's price, nothing more.
- Per-user marks go over the existing per-user eye socket, which already closes on the PIN lock (✓ `dashboard/consumers.py:217-258`).
- In the browser, the newest value wins and is re-applied after every region swap; painting runs from an index; a "live prices paused" chip shows when the socket is down.
- A watchdog thread exits the process so Docker restarts it. A file healthcheck.
- A latency budget.
- The fidelity guard, reshaped into an optional F13: the feed may only wake the manage code for one row. It never decides and never sends.

**Corrected in both**
- REST confirmations use a REST cache bound measured by M1 and M2 (C_rest). Until it is measured, REST alone never makes a price LIVE. A quiet market can stay LIVE only once the REST floor is below L − C_rest (§5.4, §4.5.6); until then it drifts to RECENT, the safe direction.
- Never imitate a browser User-Agent (Design 2 offered `--ua browser`). If eToro's edge refuses an honest one, the operator asks eToro API support.
- The level editor never refuses a stop move for want of a price.
- Price alerts never fire on an outside quote (Design 1 allowed a labelled one).
- Design 2's ask to keep forex polling at 600 s is dropped. At 600 s the Yahoo quote already sits inside the 900 s second-opinion window between polls, so 60 s changes how fresh it is, not whether it is there (etbudget's uncommitted file currently says 300 s). F2a removes the block, not the cadence.
- Morgul's new eToro feed guard is warning-only until F11, so a false finding can never apply the brake.
- **Added by the verifier (§10):** the feed's REST never writes the engine's rates cache and runs at P5 before F9; a REST floor of max(C_rest, 30 s) until lowered on evidence; protected rows keep today's wire read when the stream is not LIVE; a dead-man for the 15 s loop; one money switch per pull request (F2a/F2b, F10a/F10b, F11 one by one); a 429 on a protective close is resent; refuted glitches never act; P&L cells never step back in time; badges degrade at once; the forex break follows New York 17:00; latency is measured raw; etbudget's interim LiveQuote writer is accounted for and retired only at the end of F11.

---

## 1. Goal

### 1.1 The operator's orders (verbatim)

1. « Toute les 5min c'est beaucoup beaucoup beaucoup beaucoup trop long pour du trading. I want sauron to be alike etoro on Price data flow and feed you understand? Same grade »
2. « Faites aussi par définition donc que le jonglage entre les sources des prix soit parfaite et non pénalisante ou possiblement blessante même »

Order 2 in English: by construction, the juggling between price sources must be perfect, never penalizing, and never even possibly harmful.

### 1.2 "Same grade", as checks

These apply to every instrument held, traded or watched at eToro.

| # | Check | Where it is measured |
|---|---|---|
| G1 | Every price cell shows eToro's own bid/ask, or a value computed only from them, labelled with its source and age | the payload contract test; side-by-side check with eToro's app |
| G2 | eToro print → screen: p50 ≤ 0.5 s, p99 ≤ 1.5 s while the stream is LIVE. A target, not a promise: the eToro → server leg is unmeasured (M2) and may alone use part of it | /health/ latency line: raw arrival − eToro's Date on an NTP-synced host (M6), never "corrected" by its own median (§5.3) |
| G3 | Open-position P&L equals eToro's own figure at each figure (about every 10 s, eToro's cache [E22]). Between figures it moves only with eToro's prices and eToro's conversion. When "to the cent" cannot be guaranteed, the cell shows eToro's own figure with its age | `manage.py pnl_parity`; /health/ match rate |
| G4 | Bot-side levels and care decide on eToro's closing side (bid for a long, ask for a short [E24]) within 15 s (F9), or about 2 s with F13. eToro-held stops stay at eToro | shadow ledger; `feed_status --loop` |
| G5 | Exits are booked at eToro's executed price (F8) | `feed_shadow_report --exits` |
| G6 | Entries are sized and gated on eToro's executable side (ask for a BUY, bid for a SELL) and on eToro's conversion (F10) | shadow ledger |

### 1.3 "Harmless by construction", as checks

Whatever source is up, down, late, wrong or changing:

| # | Harm that must never happen |
|---|---|
| H1 | No price switch creates a false jump (on screen or in any store) |
| H2 | No wrong P&L |
| H3 | No false alarm |
| H4 | No stop or exit triggered or booked at a price eToro did not show |
| H5 | No entry sized or gated on a price that is not eToro's |
| H6 | No protective action blocked |
| H7 | Degraded data is always visible as degraded |
| H8 | Every transition (authoritative → fallback → back) is proven harmless by tests on every money path |

§4.1 maps each harm to the invariants that prevent it and the tests that prove it.

---

## 2. Facts

### 2.1 eToro (public sources only; no credentials used)

Confidence, as tightened by the verifier (§10):
- **confirmed** = quoted word for word, and re-read on 2026-11-06, from eToro's self-declared official repositories (S-d, S-e: `etoro-public`, plugin author "eToro", apisupport@etoro.com, homepage api-portal.etoro.com, README "Official eToro plugin"). The org's ownership could not be checked from this session: github.com's org pages and api-portal.etoro.com are unreachable here.
- **likely** = eToro's spec text read through a third-party copy (S-a, S-b, S-c), or a portal or help-centre search extract. Where an independent live probe (S-f) saw the same thing, the row says so.
- **unverified** = third-party code or reports alone, conflicting sources, or nothing written down.
- A row about what a community client's own code does is "confirmed (about that code)": it says nothing about eToro.

| # | Fact | Confidence | Source |
|---|---|---|---|
| E1 | There is one WebSocket server, `wss://ws.etoro.com/ws`. Every request is `{id, operation, data}`, where operation is Authenticate, Subscribe or Unsubscribe. Each request is acknowledged with its `id`, `success`, and `errorCode`/`errorMessage` on failure. The protocol has no trading operation | likely (spec text via a third-party copy, re-read; the live probe S-f saw the same envelope and acks) | S-a, S-f |
| E2 | Login is a message, `Authenticate {userKey, apiKey}`, using the same two keys as REST's `x-user-key`/`x-api-key`. The spec copy says it is "Required before subscribing to `instrument:{instrumentId}`" and every other topic. Builders tutorials that show header login contradict the spec | likely (spec copy; S-f logged in the same way) | S-a, S-f, S-j, S-l |
| E3 | Acknowledgement error codes include InvalidKey, Unauthorized, Forbidden, TooManyRequests, DataRequired, ApiKeyRequired, UserKeyRequired, SessionAlreadyAuthenticated and UnhandledException | likely (spec copy; S-f saw Unauthorized, InvalidKey, TooManyRequests and BinaryMessagesNotSupported) | S-a, S-f |
| E4 | `Subscribe {topics[], snapshot}`. With `snapshot: true` the current rate is sent at once (market topics only; the default is false) | likely (spec copy; S-f used snapshot:true live) | S-a, S-f |
| E5 | Topic `instrument:<id>` pushes `{messages:[{topic,type,id,content}]}` with type `Trading.Instrument.Rate`. `content` is a JSON string carrying Ask, Bid, LastExecution, Date and PriceRateID, every value a string. Every field is optional in the schema (so a push without Ask or Bid is legal). The instrument id appears only in the topic. There are no conversion fields (the USD fields are obsolete). The WS PriceRateID is a string ("106439224591"); REST v1's `priceRateID` is an integer | likely (spec copies; S-f saw the type and fields live) | S-a, S-c, S-f |
| E6 | A community probe (2026-06-29) saw a one-time `Snapshot` frame carrying ConversionRateAsk/Bid, OfficialClosingPrice, DailyClose and IsMarketOpen. Later updates carry the price only, and some carry no price at all (`{Date, PriceRateID}`). BTC updated every 0.3 to 1.5 s | likely | S-f |
| E7 | A second client also drops the price-less frames, so two independent clients report them | likely (eToro sends them); confirmed (about etoropy's code, re-read) | S-g, S-f |
| E8 | The endpoint sits behind Cloudflare. The client may send text frames only; a binary frame gets `BinaryMessagesNotSupported`. The server sends binary `\x00` keepalives. Clients send protocol pings every 20 to 30 s with about a 10 s timeout | likely | S-f, S-g, S-h |
| E9 | No heartbeat rule, idle timeout, or cap on topics or connections is published | unverified (absence) | S-a, S-j |
| E10 | The MarketStatus and Position.Opened messages are marked illustrative; Position.Closed and the candle topic carry template text | likely | S-a |
| E11 | The private topics `private` (alias `private:real`) and `private:demo` are separate streams of order updates: StatusID, ExecutedUnits, EndRate, NetProfit, CloseReason, ErrorCode. There is no P&L or equity stream. One SDK saw "Filling" arrive at once on the stream and "Executed" confirmed by REST | likely | S-a, S-h |
| E12 | REST v1 `GET /api/v1/market-data/instruments/rates?instrumentIds=` returns ask, bid, lastExecution, conversionRateAsk/Bid (instrument currency to USD, "used for position value calculations"), date and priceRateID; the row's id key is `instrumentID`. The v1.408 copy caps the list at 100 (`maxItems: 100`, 400 "exceeding maximum limit"); the v1.413 Go copy cannot express maxItems, so its silence is not a change | confirmed (the path, S-d) / likely (fields and the 100 cap, spec copies) | S-b, S-c, S-d |
| E13 | Id lists need a literal comma; `%2C` is rejected (eToro's own rule). Community clients report encoded commas being silently ignored or answered with a 500 | confirmed (the rule, re-read) / unverified (the community reports) | S-d, S-k, S-h |
| E14 | REST v2 `GET /api/v2/market-data/rates`: up to 1000 ids; `quoteType` realtime or delayed; 206 when only some ids are found, 404 when none are; bid, ask **and date** can be null; the id key is `instrumentId`; no conversion fields | likely | S-b, S-c |
| E15 | The spec gives market data 120 requests per 60 s, shared by 11 endpoints including both rates endpoints and candles (re-counted in both copies). The portal guide says 60 reads a minute per user key over a rolling window. The two conflict, and nothing says whether the guide's 60 covers the account reads too | likely (two independent spec copies agree) / likely (guide, search extract) | S-b, S-c, S-j |
| E16 | `/real/pnl`, `/portfolio` and `/instrument-breakdown` share 60 per 60 s (demo has its own group). The close-order read `/real/close-orders/{orderId}` shares 60 per 60 s with `/real/orders/{orderId}` and `orders:lookup`. Trade history and **the stop/target edit `PATCH /api/v2/trading/positions/{positionId}` are on the default 60 per 60 s pool**, not the execution pool. Execution (opens, closes, cancels, limit orders) is 20 per 60 s per mode | likely (spec copies, re-read) | S-b, S-c |
| E17 | Responses carry RateLimit-Limit, -Remaining, -Reset and -Policy (`120;w=60`). A 429 adds Retry-After in seconds (example 60); the spec defines no 429 body, so it may be empty. A builders page says the headers are X-RateLimit-* instead | likely (conflict) | S-c, S-l |
| E18 | Trades are sent at most once. Only a 429 is safe to resend; after any ambiguity, reconcile through /pnl. Execution requests should be spaced ≥ 3 s apart, with backoff of 15, 30, then 60 s | confirmed | S-d |
| E19 | An open position's P&L is `positions[].unrealizedPnL.{pnL (account currency), pnlAssetCurrency, closeRate, closeConversionRate, timestamp}`, present only on PnL endpoints. Positions also carry openRate, openConversionRate, pnlVersion, totalFees and totalExternalFees | confirmed / likely | S-b, S-d |
| E20 | The spec's open-position object has no `netProfit`; that field appears only on closed trades and push messages | likely | S-b |
| E21 | Account P/L = Σ unrealizedPnL.pnL, plus copy-trading terms, in USD | confirmed | S-d |
| E22 | `/pnl` caches its whole answer for about 10 s on a rolling basis, and there is no bypass | confirmed | S-e |
| E23 | Never rebuild a live rate from P&L fields (it drifts from eToro's own valuation) | confirmed | S-d |
| E24 | A long is valued at the bid (sell price) and a short at the ask (buy price). Buys fill at the ask, sells at the bid | likely | S-i, S-b, S-e |
| E25 | Currency, index and commodity CFDs open and close at raw market prices. A separate fee is taken from the balance and does not change the P/L price. The help pages disagree on the date this started | likely | S-i |
| E26 | Forex hours: the sources conflict and could not be re-read (help.etoro.com and www.etoro.com are unreachable here). An older help article (about three years old by its search date) says Sunday 21:05 to Friday 20:30 GMT, with a daily break 22:00-22:05 GMT. eToro's current market-hours tables, by search summary only, list most pairs Sunday 22:05 to Friday 21:30. The GMT times appear to move with US daylight saving, as the FX week's New York 17:00 edge does (✓ `core/exchange_status.py:470-500`). Hours can change | unverified (conflicting; DST-dependent) | S-i |
| E27 | Rates carry no open/closed flag (v2 has only quoteType). `isMarketOpen`/`isTradable` appear only in watchlist enrichment, and `isOpen` only in search | likely | S-b |
| E28 | Orders placed while a market is closed are accepted as pending | confirmed | S-e |
| E29 | A close answers 200 when it is submitted. The executed rate and proceeds are read at `GET /api/v1/trading/info/real/close-orders/{orderId}`. This contradicts Sauron's 2026-09-23 finding ✓ `etoro_client.py:100-113` | likely | S-b |
| E30 | eToro's own skills contradict each other on whether REST rates are cached server-side. One gives a polling interval for a live price of **30-60 s** ("may be cached server-side; faster polling doesn't yield fresher data and burns rate-limit budget"), and 10-30 s for P&L ("The PnL endpoint's own cache TTL is 10s"). The other says the rates endpoint is "not subject to this cache" and suits "sub-second price-threshold triggers" | confirmed (both statements, re-read) | S-e |
| E31 | The Builders terms require respecting rate limits and polling intervals. eToro's guidance is to stream rather than poll rates every second | likely | S-m, S-l |
| E32 | Community clients have known faults: resubscribing without a snapshot, giving up on reconnect, and treating "any instrument ticking" as proof of liveness | confirmed (about those clients' code, re-read; not a fact about eToro) | S-g, S-h, S-f |
| E33 | `/instrument-breakdown` exposes currentRate, currentConversionRate, rateTimestamp and fxValueImpact | likely | S-b |
| E34 | The WebSocket endpoint is Cloudflare-fronted (S-f). Requests without a browser-like User-Agent met 403 on another base path (`…/api/public`, per S-f's REST notes) and on the API portal; one MCP client sends a browser-style token for that reason. **Sauron's own REST client on `public-api.etoro.com` sends requests' default User-Agent and works** (✓ no User-Agent override, `etoro_client.py:168`, `:1093-1103`; ✓ measured 200s, `:1296-1330`). Whether `ws.etoro.com` accepts an honest User-Agent is unmeasured (M2) | likely (the 403 reports) / ✓ (Sauron's REST) | S-f, S-k |
| E35 | The Builders tutorials use wire formats that are not in the spec; do not rely on them | likely | S-l |

**Sources.**

| Key | Source |
|---|---|
| S-a | AsyncAPI v1.413.0 as regenerated 2026-11-06: https://raw.githubusercontent.com/psyb0t/go-etoro/v0.6.2/ws/etorows.gen.go |
| S-b | OpenAPI v1.413.0 in the same client: https://raw.githubusercontent.com/psyb0t/go-etoro/v0.6.2/client.gen.go |
| S-c | OpenAPI v1.408.0 copy: https://raw.githubusercontent.com/n-kostadinov/etoro-trading-mcp/main/openapi/etoro.core.json |
| S-d | eToro-Public rules (self-declared official: plugin author "eToro", apisupport@etoro.com; ownership of the org not verifiable here): https://raw.githubusercontent.com/etoro-public/etoro-cursor-plugin/HEAD/rules/etoro-api-conventions.mdc and `.../rules/etoro-account-snapshot.mdc` |
| S-e | eToro agent skills (same org, same caveat): https://raw.githubusercontent.com/etoro-public/etoro-agent-skills/HEAD/skills/etoro-trading-assistant/references/ (account-snapshot.md, conditional-rules.md, single-trade-walkthrough.md) |
| S-f | Community probe: https://raw.githubusercontent.com/weirdapps/etoro-tui/master/docs/etoro-websocket-actual.md |
| S-g | etoropy 0.1.7: https://pypi.org/project/etoropy/ |
| S-h | shayhe-tr/etoro-sdk: https://raw.githubusercontent.com/shayhe-tr/etoro-sdk/main/src/ws/ws-client.ts; the order-event and "comma list returns 500" rows are in the **master** README (https://raw.githubusercontent.com/shayhe-tr/etoro-sdk/master/README.md); the main README says "100 requests/minute" instead |
| S-i | Help centre, read through search extracts: `help.etoro.com` articles "how do I calculate the P/L per trade", "pricing model for CFD indices, commodities and currencies", "what are the market hours" |
| S-j | API portal, read through search extracts: `api-portal.etoro.com/core/websocket/overview`, `/core/getting-started/rate-limits` |
| S-k | https://raw.githubusercontent.com/florinel-chis/etoro-mcp/master/src/etoro_mcp/client.py |
| S-l | builders.etoro.com learn pages, read through search extracts |
| S-m | Builders' Economy Terms (17 Feb 2026), through search summaries |

### 2.2 Sauron (verified in code for this spec)

**Price table and its rules**
- ✓ Sources are ranked oanda_stream 100, binance_ws 100, finnhub_ws 90, ibkr 80, etoro 70, coingecko 40, alpha_vantage 30, yfinance 20; anything else gets 50. A better source holds the row for 300 s of *write time* (`market_data/quotes.py:28-47`).
- ✓ A writer that supplies no bid/ask clears both, and sides are never validated (`market_data/quotes.py:146-158`).
- (map) LiveQuote holds one row per instrument, and its `updated_at` is Sauron's write time (`market_data/models.py:31-60`).
- ✓ yfinance falls back to `previousClose` as `last` (`market_data/tasks.py:58-64`).
- ✓ The pollers use fixed-UTC hours (`core/market_calendar.py:6-30`). `core.exchange_status.market_clock` (`:743`) and `_forex_week` (`:470`) know daylight saving and holidays.
- ✓ Cadences: watchlist quotes 60 s, forex 600 s, commodity, index and crypto 300 s (`config/celery.py:226-252`); bot tick 300 s (`:470-472`); pending-close drain 300 s (`:618-620`); reconcile every 5 min (`:648-651`); eToro account sync 300 s (`:683-686`).

**eToro client (main)**
- ✓ `ticker()` sends one GET per instrument id. `lastPrice` = lastExecution, else the mid. The keys are a belief, never measured on a real key. eToro's `date` is not read (`bot_program/engine/etoro_client.py:1650-1733`).
- ✓ Timeout 10 s (`:1063-1069`); one retry after 0.8 s on a 5xx or transport failure (`:394-395`).
- ✓ One key pair answers both worlds (`:1400-1408`). `/info/real/pnl` was measured 200, read-only, on the real key (`:1296-1330`).
- ✓ A close answer carries no price, and the close order id was findable nowhere on 2026-09-23. Exits are therefore booked at the engine's mark (`:100-113`, `:3115-3138`). The close answer does carry `orderForClose.orderID`, which the client returns as the record `orderId` (✓ `:3119-3124`, `:3199-3202`): the id M4 needs comes from a close Sauron sent, never from a close made by hand in the app.
- ✓ A close POST that meets a 429 raises (`raise_for_status`, `:3197`) and the row goes to CLOSE_PENDING for the 300 s drain; writes are never retried (`:386-393`).
- ✓ Stop and target moves are `PATCH /api/v2/trading/positions/{id}` (`:2950-2958`), on eToro's default 60/60 s pool per the spec copy [E16]; etbudget counts them in its execution family, the stricter one ([BUD] `etoro_budget.py:12-17`).
- ✓ The REST session sets only `x-api-key`, `x-user-key` and the content type: requests' default User-Agent, and it works (`:1093-1103`) [E34].
- ✓ `/portfolio` `netProfit` is stored as "the public reference's name, unmeasured on this account" (`:2112-2140`).
- ✓ /search answers 429 "after a few dozen asks", and seven /search 429s in one second made eToro SICK on 2026-10-06 (`:203-210`, `:415-423`).

**Engine and money paths**
- ✓ Mark sanity jump bars: forex 0.5%, crypto/stock/ETF 3%, index 1.5%, commodity 2%. The window is 15 min; 2 prints confirm a jump; a second opinion counts while ≤ 900 s old; a mark frozen for 45 min is flagged; VENUE_SOURCES is `("etoro",)` (`bot_program/mark_sanity.py:50-66`).
- ✓ A disagreement is never out-voted (`:133-154`). The second opinion is any LiveQuote whose source does not start with "etoro", ≤ 900 s old, with no stand-in check (`:176-195`).
- ✓ A failed verdict skips the vanished-stop net, care, trailing and SL/TP for that row this tick (`bot_program/asset_engine/base.py:1548-1557`). Protected rows skip bot-side SL/TP (`:1620-1635`). SL/TP compare the lastPrice (`:1641-1656`).
- ✓ CLOSE refuses a live close when it has no usable mark: "the position is still OPEN rather than booked at a price nobody quoted" (`bot_program/manual_close.py:555-564`).
- ✓ The kill switch asks the venue ticker before each close. If that fails it falls back to `venue_mark.for_booking`, then books the exit UNPRICED (`bot_program/engine/kill_switch.py:269-342`; called at `:845-846`).
- ✓ The daily-loss gate counts unpriced exits (`pnl is None` or `exit_price_unavailable`) as "unmeasured" and sums only the priced ones (`portfolio/risk_gate.py:650-718`).
- ✓ `venue_mark.resolve` picks, in order:
  1. a stamp ≤ 900 s old, at its closing side;
  2. otherwise the same instrument's quote `last`, with **no age bound**, provided it is no older than the stamp;
  3. otherwise a stamp ≤ 4 days old.

  (`bot_program/venue_mark.py:400-432`; thresholds `:104`, `:116`, `:133`.) The stand-in test is waived only when the quote's source exactly equals the carrier (`:343-358`).
- ✓ Exit booking falls back to the mark, and a broker price wins when one is present (`bot_program/pending_closes.py:404-412`).
- ✓ The forex conversion uses a LiveQuote ≤ 900 s old, else a bar ≤ 6 h old, from any source (`bot_program/asset_engine/forex_bot.py:31-46`).
- ✓ Morgul's G10 mark staleness threshold is 3600 s (`bot_program/morgul.py:202-208`).

**Pages and push**
- ✓ Every dashboard socket joins `dashboard_live` (`dashboard/consumers.py:58-63`).
- ✓ `push_quote_update` carries no source and no time (`:134-147`). `push_stream_update` has no callers (map) (`:163-175`).
- ✓ The eye socket is per user, refuses locked and investor sockets, and closes on `session_locked` (`:217-258`).
- ✓ The browser re-dispatches every eye event as `sv:eye-event`, and an unknown kind raises no banner (`templates/base.html:7462+`, `:7655-7699`).
- ✓ The watchlist rail matches ticks by exact text (`:4086-4092`). The dashboard socket's `alive` flag (`:4052`) is read by nothing (map).
- ✓ The live sweep runs every 20 s × 3 = 60 s while the socket is up (`templates/_partials/live_region.html:47-51`).
- ✓ "Current" is printed with 4 decimals (`dashboard/views.py:1865`).
- ✓ The channel layer runs on library defaults (`config/settings.py:305-318`). Tests run on LocMemCache and InMemoryChannelLayer (`:266`, `:301`, `:320`). The venv has no hypothesis, freezegun, fakeredis or pytest.

**Libraries and pins**
- ✓ Pinned versions: channels 4.3.2, channels-redis 4.3.0, daphne 4.2.3, requests 2.34.2, websockets 17.4 (`requirements.txt:32-34`, `:55`, `:87`).
- ✓ websockets 17.4 `ClientProtocol.process_response` raises InvalidStatus on any status other than 101 (venv `websockets/client.py:132-145`). `websockets.asyncio.client.connect` follows up to 10 redirects (`asyncio/client.py:37`, `:448`, `:523-559`).
- ✓ The no-redirect pin's FOLLOWERS list `websockets.connect`, websocket-client, curl_cffi and aiohttp, but not `ClientProtocol` (`tests/test_etoro_no_redirect.py:1160-1191`). A request "site" is a following callable (`:1312-1345`). The set of eToro modules with a site must stay exactly two (`:1905-1918`). So a ClientProtocol over `asyncio.open_connection` is not a site.
- ✓ PIN switches: `LIVE_MONEY_SWITCHES` is written by hand, and a System key ending `_live` must be listed in it. `ORC_MIND_SWITCHES` is the same idea for the Orcs. All of them are excluded from "all on" (`core/platform_control.py:88-150`). `manage.py component list|on|off` exists (`core/management/commands/component.py:37-43`).
- ✓ Compose uses `restart: unless-stopped`. The streamers sit in the opt-in profile `streamers` with no healthcheck (`deploy/docker-compose.yml:27`, `:84`, `:210-240`). `./deploy/dc` is the compose wrapper.

**In-flight branches**
- ✓ etbudget's `_rates_get` passes `params={"instrumentIds": "a,b"}` (`[BUD] bot_program/engine/etoro_client.py:2256-2265`). Checked offline today: requests 2.34.2 prepares this as `instrumentIds=1%2C2%2C3`, while a pre-built URL keeps `1,2,3`.
- ✓ `rates_raw` is a background read (`:2396-2416`).
- ✓ `etoro_rates_shape` sends one GET with two ids and prints field kinds, never values (`[BUD] bot_program/management/commands/etoro_rates_shape.py:1-40`, `:96-104`).
- ✓ The rates cache stores `{lastPrice, bid, ask, at}`, dated on arrival, under `etoro_rates:r:{world}:{iid}` (`:170`, `:192-193`). It writes unconditionally, "0" answers included (`[BUD] bot_program/engine/etoro_rates.py:370-420`). **Money reads it:** `_mark_price` takes an answer ≤ 30 s old inside the manage walk (`[BUD] base.py:3513-3540`), and the time stop's close can book a cached mark (`[BUD] pending_closes.py:547-557`). Every rates read of the client writes it (`[BUD] etoro_client.py:2233`, `:2378`); `rates_raw` does not (`:2396-2416`). A "0" answer is the platform's no-price sentinel, which every money reader skips (`etoro_client.py:1712-1731`).
- ✓ **Uncommitted interim (`[BUD] bot_program/etoro_quotes.py`, untracked; beat `refresh-etoro-quotes` 30 s in the modified `config/celery.py:755-759`).** Every 30 s it reads eToro's rates for the instruments of open REAL eToro rows (P3, at most 6 single reads a pass, batched once proven) and writes them to LiveQuote as source `etoro` (rank 70) with bid and ask. The same modified file sets the sync to 60 s (`:740-742`) and the forex poll to 300 s (`:253-255`). Its effects, read in code: mark sanity's second opinion ignores `etoro` sources (`mark_sanity.py:64`, `:189-191`), so held instruments lose their outside second opinion while it holds the row; `venue_mark.quote_stand_in` waives the stand-in check for it (`:351-354`); pnltruth's tier 2 lights up on it; any running stream (ranks 90-100) out-ranks it, and its writes are then refused for 300 s after each stream tick (`quotes.py:95-106`).
- ✓ etbudget constants: MARK_MAX_AGE_S 30, BATCH_MAX_IDS 20 (a guess), MEASURED_FIRST (`:138-162`).
- ✓ `_mark_priority` gives P1 to a live row with no stop at eToro and P3 otherwise (`[BUD] bot_program/asset_engine/base.py:3489-3511`).
- ✓ `_confirm_mark`: a cached mark never acts alone. If the re-read fails, nothing price-based acts on the row this tick (`:3644-3660`).
- ✓ pnltruth (`a08c87b`):
  - tier 1 is `net_profit` from `/portfolio`, if ≤ 900 s old (`[PNL] portfolio/services.py:1018-1040`, `_etoro_own` `:1183`, `:1214`);
  - tier 2 is an eToro-written LiveQuote (`_etoro_side` `:1221`; `_is_etoro_source` `:1090`), at its closing side, converted with the row's `value_per_unit` stamp, i.e. the conversion frozen at entry (V-open, `_usd_per_unit_of`, `[PNL] services.py:1302-1308`), labelled "estimate: eToro quote".

### 2.3 Not measured by anyone yet (settled in §6.1)

| Unknown | Settled by |
|---|---|
| Whether the stream works with the operator's key | M2 |
| The snapshot's fields | M2 |
| Tick gaps per class | M2 |
| Price-less and one-sided frames | M2 |
| The Date format, and whether PriceRateID only increases and equals REST's | M2 |
| Whether the same PriceRateID carries the same Date on both channels (so Dates compare across channels) | M2, F6 |
| How far REST trails the stream (C_rest, measured directly) | M2 |
| Behaviour at the close, the reopen and the daily break, in each daylight-saving regime | M2 (winter now, again after March) |
| Whether market and account reads share one quota pool | M1 + M3a |
| Topic caps | M2 |
| Private-stream shapes | M2 |
| Whether the stream's prices equal the app's | M2 |
| Whether REST is cached server-side | M1 |
| Batch encoding and the id limit | M1 |
| Rate-limit header names and the real quota | M1 |
| v2 availability | M1 |
| The /pnl formula and sides, the meaning of pnlVersion, whether fees are in the app's P/L, `netProfit` on rows | M3 |
| Whether the close-order read works (with an id Sauron kept from its own demo close) and whether trade history works | M4 |
| What eToro's candle close is | M5 |
| Memory headroom and NTP | M6 |

---

## 3. Today

### 3.1 How a price reaches a decision and a screen

- **One price row per instrument.** `LiveQuote` keeps one source per instrument and dates it by Sauron's write time (map). The writers all go through `write_quote` (✓):

| Source (rank) | Writer | Cadence | `last` is | Sides |
|---|---|---|---|---|
| oanda_stream (100) | `stream_oanda` (opt-in) | stream, ≤ 20 pairs | mid | OANDA's |
| binance_ws (100) | `stream_binance` (opt-in) | stream | last trade | Binance's |
| finnhub_ws (90) | `stream_finnhub` (opt-in) | stream, first 50 stocks | last trade | none (clears them) |
| ibkr (80) | `ibkr_data_feed` | hourly 13:30-20:30 UTC (being retired) | IBKR last | IBKR's |
| etoro (70) | legacy Sync button only | manual | `currentRate` | none |
| binance_public (50, unlisted) | `fetch_crypto_quotes` | 300 s | lastPrice | none |
| coingecko (40) | crypto fallback | 300 s | aggregate | none |
| alpha_vantage (30) | `fetch_forex_quotes` | 600 s, 20 calls a day | AV rate | AV's (a 0 is stored as given) |
| yfinance (20) | forex 600 s, commodity and index 300 s, stocks 60 s in the US session | ✓ `config/celery.py:226-252` | regularMarketPrice, else **previousClose** ✓ | none |

- **eToro's own price never reaches LiveQuote on main**, except through the Sync button. etbudget's uncommitted interim (`etoro_quotes.py`, §2.2) changes that for the instruments of open real rows: every 30 s, as source `etoro`, rank 70. The engine reads eToro's REST rates itself, one id per GET, at decision time. It uses `lastPrice` (lastExecution, else the mid) and never reads eToro's date ✓. Each read is stamped on the row as `metadata["venue_mark"]` (map).
- **Money paths** (map M1-M19):
  - **Manage tick, every 300 s.** `_mark_price` → mark sanity → stamp → vanished-stop net → care → SL/TP on lastPrice ✓.
  - **Entries.** Ticker lastPrice → entry-quote gate (second opinion from LiveQuote) → last look → sizing, with the forex conversion taken from any source ✓.
  - **CLOSE.** Refuses with no mark ✓.
  - **Kill switch.** Reads the ticker first ✓.
  - **Bookings.** At the mark ✓. Reconcile uses the ticker, then a quote from any source ≤ 900 s old, then estimates from bars of mixed sources (map).
  - **Valuation.** `resolve` ✓.
  - **Daily-loss gate.** Skips unpriced exits ✓.
  - **Elsewhere.** Posture, Morgul, alerts, paper and the Orcs all read LiveQuote (map).
- **Screens.**
  - Positions refresh through a 60 s sweep ✓. The P&L panel is cached 20 s, keyed on a fingerprint that excludes marks (map).
  - Only the three streamers and the Yahoo stock push reach the browser. The forex, commodity and index pollers push nothing (map).
  - "Current" has 4 decimals ✓. The watchlist rail matches by exact text ✓. Nothing shows the quote socket down (map).

### 3.2 How sources are juggled today

1. A fixed rank plus a 300 s hold, measured on write time ✓.
2. A sideless writer clears bid and ask; sides are never validated ✓.
3. Three different "is this eToro's?" tests:
   - an exact `etoro` match ✓ `venue_mark.py:343-358`;
   - an `etoro` prefix ✓ `mark_sanity.py:64`;
   - three spellings ✓ `[PNL] services.py:1090`.
4. Valuation: a fresh stamp, then any same-instrument quote's `last` with no age bound, then a stale stamp ✓.
5. The second opinion is any non-eToro quote ≤ 900 s old, with no stand-in check. A disagreement is never out-voted, and it skips all management of the row ✓.
6. Two clocks: fixed UTC for the pollers ✓, and `market_clock` with daylight saving and holidays for paper, Morgul and `venue_mark` ✓.

### 3.3 Harm table (and the phase that removes each harm)

| # | What happens today | Money path that reads it | Harm | Removed by |
|---|---|---|---|---|
| 1 | A non-eToro quote that disagrees with eToro's mark by more than the class bar suspends every check on a real row: the vanished-stop net, care, trailing and bot-side SL/TP, for as long as it disagrees. It is never out-voted ✓ `mark_sanity.py:133-154`, `base.py:1548-1557` | M1, M2 | H6 | F2a |
| 2 | That second opinion can be a different instrument: an old cash-index close re-stamped as fresh against an index CFD overnight, or Yahoo futures against a commodity CFD ✓ (no stand-in check, `mark_sanity.py:176-195`; map `tasks.py:393-396`) | M1, M2 | H6, H3 | F2a, F5 |
| 3 | CLOSE refuses a live close when it has no usable mark ✓ `manual_close.py:555-564` | M5 | H6 | F2b |
| 4 | The kill switch reads the venue price before each close. A hanging read costs about 20 s per row: 10 s timeout plus one retry ✓ | M6 | H6 | F2b |
| 5 | The daily-loss gate skips unpriced exits, so an unpriced real loss is invisible to the floor ✓ `risk_gate.py:671-678`; when every close in the window is unpriced the gate fails open (✓ `:782-788`) | M17 | H2, H6 | F2b; F4 makes it rare; F8 (U28) |
| 6 | A real row with no eToro stamp younger than 900 s is valued at any same-instrument quote's `last`, with no age bound and no closing side ✓ `venue_mark.py:419-424`. This is the reported case | M9, display | H1, H2, H7 | F4, F7, F9 |
| 7 | Every eToro exit is booked at Sauron's mark (lastExecution or mid), about half a spread kinder than eToro. Reconcile can book another source's quote ≤ 900 s old ✓ `etoro_client.py:100-113`, `pending_closes.py:404-412`; map `reconcile_asset.py:657-692` | M5-M8, M17 | H4, H2 | F8 |
| 8 | Stops, targets, care and crossing notes compare lastPrice or the mid, not the closing side ✓ `base.py:1641-1656`. Stops fire half a spread late and targets half a spread early. A target touched only by the mid, followed by a stop fill, can be booked at the target (map `venue_exit.py:320-359`, `:430-436`) | M1, M7 | H4 | F9, F8 |
| 9 | Entries are sized on the mid and fill at the ask. The conversion comes from any source ≤ 900 s old and is frozen at entry ✓ `forex_bot.py:31-46`; map `base.py:5048-5066`, `:6037` | M3, M4, M12 | H5, H2 | F10 |
| 10 | Yahoo writes `previousClose` as a fresh `last` ✓ `tasks.py:58-64` | second opinion, conversion, alerts, QUOTE valuation | H1, H2, H5 | F5 |
| 11 | Fixed-UTC poller hours ✓ give winter fossils, and holidays get polled | same | H1, H5 | F5 |
| 12 | A sideless writer clears sides. Sides are never validated, and Alpha Vantage's 0 is stored as given ✓; map `alpha_vantage.py:93-95` | ticket, entry gate | H5, H7 | F5, F7 |
| 13 | Rank plus a 300 s hold on write time: after a stream gap, a lower source takes the row ✓ | paper, alerts, conversion | H1 | F5; money stops reading LiveQuote for eToro instruments (F9-F11) |
| 14 | Write time is treated as freshness (map `models.py:39`) | every LiveQuote reader | H1, H5 | the eToro stores keep eToro's Date and the confirmation time (F6) |
| 15 | At the weekend, eToro's Saturday rate is stamped fresh each tick and counts as "bookable". At the reopen, mid-based stops ignore the spread (map `venue_mark.py:493-494`) | M9, M1 | H4 | F6 (CLOSED, by eToro's Date), F9 |
| 16 | Stand-in bars are appended after the venue's last bar (map `bot_bars.py:852-889`) | rules, paper, `venue_exit` bars, Morgul G4 | H4, H5 | F8, F11 |
| 17 | Paper rows read whoever owns LiveQuote (map `paper_trader.py:265-270`) | M16 | mixed promotion evidence | F11 |
| 18 | Posture appends a cash index's `last` to CFD daily closes (map `market_stress.py:101-119`) | M13 → care | H3, H4 | F11 |
| 19 | Price alerts fire on any source's `last` (map `alerts/models.py:505-523`) | M15 | H3 | F11 |
| 20 | Morgul G10 reads LiveQuote freshness, not eToro's (map `morgul.py:1518-1538`) | M14 | H3 | F6 (G10v), F11 |
| 21 | The Orcs' census ring and news-shock corroboration read LiveQuote (map `drum_bus.py:174-180`, `:413`) | M19 | H3, AI spend | F11 |
| 22 | Candle stamps: which side the close is on is unmeasured, and a half-spread is carried forward (map `bot_bars.py:655-656`, `venue_mark.py:189-211`) | display | H2 | M5, F9 |
| 23 | Positions refresh every 60 s. The P&L panel cache ignores marks. The broker panel is frozen until reload ✓ `live_region.html:47-51`; map `context_processors.py:20`, `:202-227`, `positions_list.html:88-140` | display | H1 (late), H7 | F4, F7 |
| 24 | Two broadcasters paint one headband cell, and Yahoo pushes carry no source or time ✓ `consumers.py:134-147` | display | H1, H7 | F7 |
| 25 | Nothing shows that the quote socket is down (map `base.html:4052`) | display | H7 | F7 |
| 26 | The deal ticket's bid/ask belong to whichever source holds LiveQuote, not eToro (map `deal_ticket.html:31-53`) | M4 display | H5 | F7, F10 |
| 27 | Three different tests of "is this eToro's?" ✓ | M2, M9, P&L display | latent H2 | F1 |
| 28 | The etbudget batch would send `%2C` ✓ (checked offline) | the batch measurement | a wrong "batching fails" conclusion, so more single reads; worse, `etoro_rates_shape` records a proof when the parser trusts an answer (`[BUD] etoro_rates_shape.py:29-31`), so a partial answer to the encoded list could switch the batch on | P-a |
| 29 | etbudget's uncommitted interim writes eToro into LiveQuote at rank 70 (§2.2). Read in code, not "harmful either way" as first written, but mixed: (a) where a stream runs (OANDA, Binance, Finnhub), the stream holds the row and eToro's write is refused for 300 s after each stream tick, so the interim does nothing there, silently; (b) elsewhere the second opinion for that instrument disappears while eToro holds the row (mark sanity ignores `etoro`), which removes harm 1 for held rows but also the outside cross-check of entries on them; (c) every LiveQuote reader (paper, conversion, posture, alerts, Morgul G10, `resolve`'s QUOTE branch, the kill switch's `for_booking`) then reads eToro's `last` (lastExecution or mid, not the closing side) for those instruments; (d) when the row closes, the writes stop and yfinance takes the row back after the 300 s hold: a source switch with no label on the pushed tick (harm 24) ✓ `quotes.py:28-47`, `:95-106`; `mark_sanity.py:64`, `:189-191`; `venue_mark.py:351-354` | all LiveQuote readers | H1, H7 (and H6 relief) | P-c; retired at the end of F11 |

---

## 4. Design

### 4.1 Invariants

| # | Invariant | Enforced by | Proven by |
|---|---|---|---|
| I1 | **One authority per instrument**, fixed by where the instrument is held, routed, ticketed or watched at eToro (with a verified id). Never by write order or freshness. Leaving eToro authority needs 60 s of absence | `venue_quotes.authority()`, recomputed every 10 s | authority stays eToro through every timeline T1-T24 |
| I2 | **Stores never mix.** The eToro stores never hold an outside quote, and each eToro channel writes only its own key. The feed never writes LiveQuote. LiveQuote stops holding eToro at the end of F11: until then its one eToro writer is etbudget's interim beat (P-c), which no phase extends, and every replay counts it as part of today | separate keys; AST pins: only the feed writes `vq:*`; only the client's rates parser writes `etoro_rates:r:*`, and the feed writes it only from F9 (`venue_marks_live`); the feed never writes LiveQuote; `write_quote` refuses `etoro*` sources only once the interim beat is retired (end of F11) | pin tests; write-race tests |
| I3 | **A quote is one coherent tuple**: bid, ask, eToro Date, rate id, channel, arrival, confirmation. No carried spread, no stored mid, no foreign conversion inside eToro's P&L | the `VenueQuote` constructor refuses values that are ≤ 0, non-finite, crossed or unparsed (W1) | constructor tests |
| I4 | **eToro's time orders everything.** No store and no screen cell ever moves backwards in eToro's time. That includes a P&L cell changing tier: it shows the newer of its last live value and eToro's last figure, by time (§4.7.4) | compare-and-set by (Date, then rate id once proven); newest-wins in the browser | T3, T5, T12; property A2 |
| I5 | **Freshness comes from evidence**: the confirmation age, never Sauron's write time | §5.4 | grade table tests |
| I6 | **One pure grade function.** Consumers receive grades and never compute venue ages themselves | `venue_quotes.grade()` | table tests by class × session × channel |
| I7 | **Money code has one door.** It reads prices only through `money_price(purpose)`, which returns eToro's closing or executable side at LIVE (entries must also be fresh), or a Refusal. A Refusal leads to today's eToro wire path, or to hold/refuse. Never to an outside quote | types (`ReferenceQuote` is rejected by every money function); AST pin: money modules may not import `display_quote`/`reference_quote` (only `mark_sanity` may take a `ReferenceQuote`, for entries) | spy tests: any money path that reads LiveQuote for an eToro instrument fails |
| I8 | **Protection never waits for a price.** The close, kill switch, cancel, vanished-stop net, time stop and eToro-held stops all go out without one. A booking is eToro's executed figure or "pending". The daily-loss gate counts a pending exit provisionally and never as a gain | F2a, F2b, F8 | A7, A10 with every price source dead |
| I9 | **An outside quote never blocks or triggers.** It can only make Sauron look again (one P0 eToro read) and, for entries only, refuse | F2a, F5, F9 | T10 |
| I10 | **The screen never substitutes.** The main cell and the P&L cell of an eToro instrument show eToro numbers only, live or labelled stale. Outside quotes appear only in their labelled slot | `display_quote()`; `sv-venue.js` | payload and DOM tests (A1, A4, A5) |
| I11 | **Quick to lose trust, slow to regain it**, and no money decision ever waits on hysteresis: REST carries an instrument while the stream regains trust | §5.6 constants in one module | T1, T13, T17 |
| I12 | **Every transition is one event.** Alarms fire only for a lasting problem in an open session | `FeedTransition`; Morgul and staff rules (§5.9) | A11, A12 |
| I13 | **Never worse than today.** With the feed absent or a switch OFF, every decision is today's. "Today" is main plus the in-flight etbudget, its interim beat included. With a switch ON and the feed absent, a decision falls back to today's own path, never to "hold" where today acts (§5.8, §7) | every consumer keeps its pre-feed path as the fallback | decision replay (A15) |
| I14 | **Shadow before power.** Each money change sits behind its own `*_live` PIN switch, OFF on arrival, records its shadow decisions while OFF, and ships in its own pull request (§9.14). An observe-only phase changes no input of a money decision, not even a cache the engine reads | `core/platform_control.py`; `FeedShadowDecision` | replay ON/OFF |
| I15 | **The feed observes; it never trades.** It imports no order path, never calls /search, and its REST runs inside etbudget as background reads: P5 until F9, P3 for held instruments from F9. The WS protocol has no trading operation [E1] | AST pins | pin tests |

**From harm to invariant to proof**

| Harm | Invariants | Proven by |
|---|---|---|
| H1 false jump | I2, I3, I4, I10 | A1, A2, A16 on T1-T24 |
| H2 wrong P&L | I3, I5, I10, §4.7 | A5, A13; the `pnl_parity` tally |
| H3 false alarm | I9, I12 | A11 |
| H4 stop or exit at a price eToro did not show | I7, I8 | A8, A10 |
| H5 entry on a non-eToro price | I7, §5.8 | A9, A13 |
| H6 protective action blocked | I8, I9 | A7; F2a and F2b tests |
| H7 degraded not visible | I6, I10, I12 | A3, A11 |
| H8 every transition proven | I13, I14 | §5.10 matrix; replay A15 |

### 4.2 Architecture

```
 eToro stream: Authenticate, Subscribe instrument:<id> with snapshot      eToro REST v1 rates (literal commas)
        │ text frames only; ping 20 s                                           ▲ watchdog and fallback paced by §4.5.6
        ▼                                                                       │ (floor max(C_rest, 30 s) until lowered; P5 until F9)
 ┌─────────────── stream-etoro: own container, asyncio, imports no order path ──┴───────────────────┐
 │ conn ─► parse + validate (W1-W7) ─► WS store  vq:ws:{iid}   compare-and-set by eToro Date       │
 │ watchdog ─► feed REST store  vq:rest:{iid}   compare-and-set by eToro Date                     │
 │             (reads the engine's cache etoro_rates:r:* as a third record; writes it only from F9)│
 │ ring vq:ring:{iid} (120 s, 1 Hz)        subs ◄── feed:wants (10 s task) + page want keys (TTL)  │
 │ sweep 1 s ─► grades ─► FeedTransition          publish 250 ms ─► dashboard_live "venue_quotes"  │
 │ marks 500 ms ─► eye_user_<id> "marks" (P&L from portfolio/pnl_venue.py, the one formula)       │
 │ health 2 s ─► feed:etoro:health; alive file every 5 s; watchdog thread exits 70 on a 60 s stall│
 └────────────────────────────────────────────────────────────────────────────────────────────────┘
 Celery etoro_pnl_anchor (11 s) ─► /real/pnl, /demo/pnl ─► etoro_pnl:{world}: eToro's own figures
 Celery venue-rest-fallback (10 s) ─► takes the REST role while the feed's heartbeat is > 15 s old
 Money code ─► market_data.venue_quotes.money_price(purpose) ─► a LIVE eToro side, or Refusal ─► today's eToro wire path
 Pages ─► display_quote() and the P&L overlay ─► eToro numbers; outside quotes only in their labelled slot
 OANDA / Binance / Finnhub / Yahoo / Alpha Vantage ─► LiveQuote (outside quotes only; never eToro)
```

### 4.3 Modules

| Module | Holds | Never |
|---|---|---|
| `bot_program/engine/etoro_stream.py` | the protocol client: websockets 17.4 sans-I/O `ClientProtocol` over `asyncio.open_connection`; envelopes; ack matching; frame parser (Decimal) | `websockets.connect`, aiohttp, websocket-client, Django ORM, any order path |
| `market_data/venue_quotes.py` | types (`VenueQuote`, `ReferenceQuote`, `VenuePrice`, `Refusal`); `authority()`, `grade()`, `money_price()`, `display_quote()`, `reference_quote()`, `is_venue_source()`; hysteresis constants | keys, network, `bot_program.engine` |
| `market_data/venue_store.py` | the feed's stores `vq:ws:*` and `vq:rest:*` (a Redis Lua compare-and-set, plus an in-memory twin with the same rules for tests); a read-only view of the engine's `etoro_rates:r:*` until F9; the ring | network; writing `etoro_rates:r:*` before F9 |
| `market_data/venue_session.py` | the session rule (§5.5) | changing `market_clock` |
| `market_data/management/commands/stream_etoro.py` | the service loop | order paths, /search, `instrument_id()` |
| `market_data/feed_wants.py` | the subscription set (beat every 10 s) | — |
| `portfolio/pnl_venue.py` | the P&L formula registry, calibration, and the "anchor plus change" calculation (pure Decimal) | network |
| `bot_program/etoro_pnl.py` | the `/pnl` reader and the anchor task | any money decision |
| `bot_program/feed_shadow.py` | the shadow recorder and its report | sending anything |
| `bot_program/feed_harms.py` | the harm counters and their report | — |

`money_price(instrument, purpose)` takes a purpose of CLOSING(position side), EXECUTABLE(order side) or CONVERSION(currency). It returns either `VenuePrice{price, side, vt, confirmed_at, channel, grade}` or `Refusal{reason}`. The reason is one of `switch_off`, `not_live`, `unconfirmed_jump`, `session`, `quiet`, `no_record` or `stale_conversion`.

The core lives outside `bot_program/engine`, so the O2a pin (Orcs may not reference callables there, map `tests/orcs/test_orc_o2a_shadow_pins.py:335-341`) holds for every module that the Orcs and the pages read.

### 4.4 Source per asset class (instruments held, traded or watched at eToro)

| Class | Authority | Fallback, same authority | Outside quotes (labelled, never money) | Never |
|---|---|---|---|---|
| Forex | eToro stream | eToro REST v1, batched, with conversion | OANDA stream (same pair); Yahoo `=X` labelled "delayed" | another feed's mid or conversion inside eToro's P&L |
| Crypto | eToro stream | eToro REST | Binance stream, with the USDT-vs-USD gap labelled | Binance's price passed off as eToro's |
| Stocks/ETFs | eToro stream | eToro REST | Finnhub stream; Yahoo labelled "delayed" | a delayed quote as a second opinion |
| Index CFDs | eToro stream | eToro REST | Yahoo cash index, labelled "cash index, different instrument", never compared | a cash index spliced into the CFD's stress series |
| Commodity CFDs | eToro stream | eToro REST | Yahoo futures, labelled "future, different instrument", never compared | futures as a second opinion |
| Conversion (e.g. NZD→USD for a pair quoted in NZD) | eToro REST `conversionRateBid/Ask` [E12]; the conversion pair's eToro stream only if M3 proves it tracks eToro's `closeConversionRate` | the snapshot conversion while ≤ 60 s old | — | LiveQuote's FX |
| Watched beyond the topic cap | eToro REST at P5 every 60 s (v2 up to 1000 ids if M1 proves it, else v1), labelled with its age | — | as above | a v2 `delayed` quote for anything but labelled display |

Instruments not at eToro keep today's path; after F5, their freshness is judged by the exchange clock.

### 4.5 The eToro feed service

**4.5.1 Process**
- `python manage.py stream_etoro` runs as one asyncio process in its own container. Its tasks:
  - `conn`: connect, authenticate, subscribe, read;
  - `subs`: diff the wanted set every 2 s;
  - `flush`: every 250 ms;
  - `sweep`: every 1 s, recomputing grades and transitions;
  - `watchdog`: REST reads on a worker thread;
  - `marks`: every 500 ms;
  - `health`: every 2 s;
  - `alive`: touches `/tmp/stream_etoro.alive` every 5 s.
- A task that raises is logged and restarted.
- A separate thread exits the process with code 70 if the event loop's heartbeat stalls for 60 s. Docker restarts a container when its process exits (`restart: unless-stopped`), not when it is merely "unhealthy".
- With no eToro keys the process idles and re-checks every 60 s. It never exits, so it never loops on restarts.

**4.5.2 Connection and security**
- **Transport.** `asyncio.open_connection("ws.etoro.com", 443, ssl=<default context>, server_hostname="ws.etoro.com")`, with the sans-I/O `ClientProtocol` on top.
  - Any answer other than 101 raises InvalidStatus ✓. That is a failed connect: nothing more is sent, and no second connection is opened. A 3xx is never followed.
- **Login.** `Authenticate {userKey, apiKey}` goes in the first text frame after the 101 [E2].
  - The keys are decrypted from `EtoroAccount` with Fernet, as the REST client does (map `bot_program/models.py:484-489`).
  - They are held in memory only and never logged (only a 12-character hash is). They are never written to Redis.
  - They are re-read after a login refusal or whenever the account row changes.
- **Frames.** The client sends text frames only [E8]. Incoming binary `\x00` keepalives count as liveness and are never echoed.
  - A protocol ping goes out every 20 s, with a 10 s pong timeout.
  - No frame of any kind for 30 s → reconnect. Requests carry uuid ids; no acknowledgement within 10 s → reconnect.
- **User-Agent.** An honest, fixed one such as `SauronVision-feed/1`, set explicitly on the handshake request: the sans-I/O `ClientProtocol` adds none by itself (only the asyncio `connect` does, ✓ venv `websockets/asyncio/client.py:89-99`). Sauron's REST client already works on eToro's API host with requests' default User-Agent [E34]; the WS edge is unmeasured (M2). If Cloudflare refuses the honest one, the feed stops and says so, and the operator asks eToro API support. It never imitates a browser.
- **Cannot trade.** The protocol has no trading operation [E1]. A pin forbids feed modules from importing order paths, /search or `instrument_id()`.

**4.5.3 Reconnect and error codes**

| Event | Action |
|---|---|
| Socket closed; no frame for 30 s; no pong within 10 s; no acknowledgement within 10 s | Reconnect after 1, 2, 4, 8, 16, 32 s, then every 60 s (the cap), each ±20% jitter, **forever** [E32]. Every resubscribe sends `snapshot: true` [E4] |
| InvalidKey, Unauthorized, Forbidden, ApiKeyRequired, UserKeyRequired | State `auth_refused`; one staff alert; retry in 10 min (60 min if it repeats), or at once when the keys change |
| TooManyRequests on Authenticate | Back off 60 s |
| TooManyRequests on Subscribe | Halve the batch, pause 5 s, retry. If it persists, cap topics at the last accepted count and report it |
| SessionAlreadyAuthenticated | Treat as authenticated |
| Unknown message type | Count it by type, log once a minute, show it on /health/ |

**4.5.4 Subscriptions**
- **Priority**, highest first:
  1. instruments of open eToro positions, real then demo: Sauron's rows and anything in `EtoroAccount.broker_positions`;
  2. open TAKE TRADE and CLOSE dialogs (`feed:want:ticket:{iid}`, 120 s TTL);
  3. conversion instruments of held rows. They are subscribed from F6 so that F7's calibration can compare them with eToro's `closeConversionRate`, but they are used in a P&L only once proven (§4.7.3);
  4. symbols of enabled configs routed to eToro, live configs first;
  5. instrument pages in view (`feed:want:chart:{iid}`, 60 s TTL, refreshed by the page's 15 s poll);
  6. the watchlist;
  7. the headband's eToro-tradable symbols.
- **Cap.** `ETORO_WS_MAX_TOPICS` = 50 until M2 measures the real limit.
- **Ids.** Taken only from `_known_id()`, which needs no request (map `[BUD] etoro_client.py:2108-2130`).
  - An unknown id is listed on /health/ as "no eToro id". That instrument shows its outside quote, labelled as such; it never pretends to be eToro's.
- **Pacing.** Diffs every 2 s. Subscribe/Unsubscribe batches go out at most once a second, with sizes taken from M2. A topic leaves only after 60 s unwanted.

**4.5.5 Parsing**
- Each `messages[]` item [E5] is handled as follows:
  - **Topic** → instrument id, which must be in the verified table.
  - **Type** → `Trading.Instrument.Rate`, `Snapshot` (the community's name for it [E6]), a private order type [E11], or unknown (counted).
  - **Content** → parsed as a second JSON document; its values are strings, read as Decimal.
- Duplicate message ids are dropped, using the last 10,000.
- The write rules W1-W7 (§5.3) then apply.

**4.5.6 REST watchdog and fallback (the same authority, through a second channel)**
- **The cadence floor.** eToro's own skill gives 30-60 s as the polling interval for a live price [E30], and the terms ask for respect of "polling intervals" [E31]. So no feed REST GET (watchdog, quiet pull-forward, fallback) goes out more often than **every max(C_rest, 30 s)** per batch, until both (a) M1/M2 measured C_rest < 30 s and (b) eToro API support has answered a generic question ("is one batched rates GET every few seconds during a WebSocket outage acceptable?") or the operator decides in writing. Then the floor becomes max(C_rest, 4 s). This is today's interim level (etbudget's beat reads held rates every 30 s), so the floor is never worse than today.
- **Watchdog, while the stream is healthy.**
  - One batched v1 GET per floor period for held, ticket and conversion instruments. It uses literal commas and at most 20 ids until M1 proves up to 100 [E12-E13].
  - Watched instruments every 60 s.
  - A topic quiet for longer than Q[class] pulls the next read forward, never sooner than the floor.
  - Total ≤ 12 GETs a minute.
- **Comparison.** Each REST row is written to the feed's REST store `vq:rest:{iid}` (compare-and-set by Date, with date, priceRateID and the conversion) and compared with the WS store:
  - REST newer → that topic is "behind": downgrade it, resubscribe with a snapshot, count it;
  - REST equal or older → a confirmation (§5.4).
- **Fallback, once the stream has been unhealthy for an instrument for 3 s.** Held instruments once per floor period, watched every 60 s, until the stream has been LIVE again for 30 s.
- **No duplicate reads.** An instrument any reader answered within the floor period (the engine's cache `etoro_rates:r:*`, read-only to the feed before F9, or the feed's own store) is not asked again.
- **Batching not yet proven (M1).** Single-id GETs round-robin within the same per-minute caps, held instruments first.
- **Pacing.**
  - On Retry-After, all of the feed's own REST stops for that long [E17].
  - When `RateLimit-Remaining` drops below 25% of the limit, it halves its rate.
  - Never faster than eToro's measured REST refresh (C_rest) or the floor above.
- **Budget.**
  - Every feed REST read is a background read inside etbudget at **P5 until F9** (so it is refused before the engine's P3 marks and never crowds them out), and self-limited to 15 GETs a minute so the candles keep their P5 share. From F9, held-instrument reads move to P3: they then replace the engine's own mark reads for LIVE instruments. A failure never counts on venue health and never starts the shared 429 pause.
  - A budget refusal reads as "degraded". P0/P1 are untouched (✓ `[BUD] etoro_budget.py:20-41`: "P0 AND P1 ARE NEVER REFUSED, NEVER DELAYED, NEVER QUEUED").
- **The engine's cache is not the feed's before F9.** Until `venue_marks_live` is ON, the feed reads through an uncached path (the parser shared with the client, as `rates_raw` sends: no write to `etoro_rates:r:*`, ✓ `[BUD] etoro_client.py:2396-2416`). The engine's `_mark_price` reads that cache (✓ `[BUD] base.py:3513-3540`) and the time stop can book a cached mark (✓ `[BUD] pending_closes.py:547-557`), so a feed write there would change money inputs in an observe-only phase.
- **Feed process down** (its heartbeat > 15 s old). The Celery task `venue-rest-fallback` (every 10 s, expiring after 8 s, under a Redis lock) takes over the held part of the fallback, with the same floor and priority. The engine's own reads go on as today, so nothing is ever worse than today.

**4.5.7 Writes**
- **WS store `vq:ws:{iid}`.** At most 4 writes a second per instrument. The newest value wins in memory between flushes, and a grade change writes at once. Writes go through the compare-and-set script.
- **Ring `vq:ring:{iid}`.** (Date, bid, ask, rate id) at ≤ 1 Hz, kept 120 s. It serves P&L calibration and the price at a close.
- **Postgres.** No quote table. `FeedTransition` keeps 30 days; `FeedShadowDecision` keeps 90 days.
- **LiveQuote.** Never written by the feed (pin).

**4.5.8 Health**
- `feed:etoro:health`, written every 2 s, carries:
  - connected since, and the last frame;
  - topics wanted and acknowledged;
  - LIVE, RECENT and STALE counts;
  - reconnects in the last 24 h;
  - "behind" events in the last hour;
  - the last error code;
  - REST fallback on or off, and REST GETs a minute;
  - clock skew;
  - RSS.
- `market_data/feeds.py` gains `etoro_ws` and `etoro_rest`. The legacy `etoro` entry is renamed "etoro (legacy sync)".
- The status pill reads all of this.
- **Parity line, per held instrument.** The last watchdog verdict (same, newer or older); latency p50/p99 (raw arrival − eToro Date, shown only while M6's NTP check holds; a negative value raises the skew warning instead of being "corrected"); stream-vs-REST agreement. This is the objective "same grade" meter.

**4.5.9 Compose**

```yaml
  stream-etoro:
    <<: *django
    command: python manage.py stream_etoro
    profiles: ["etoro-feed"]          # opt-in at F6; joins the default set after a clean week (F11)
    mem_limit: 384m
    oom_score_adj: 900                # under host memory pressure the feed dies before any money worker
    stop_grace_period: 10s
    healthcheck:
      test: ["CMD-SHELL", "test $$(( $$(date +%s) - $$(stat -c %Y /tmp/stream_etoro.alive 2>/dev/null || echo 0) )) -lt 60"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 60s
```

- No new environment variable is needed.
- The feed exits cleanly above 320 MB RSS, as a leak guard. Its memory use is unmeasured (M6); the budget is about 200 MB, one Django process.
- On a 4 GB host under pressure, the operator chooses what stops first: the Binance depth and futures streamers, then OANDA (the only real-time forex outside quote).
- The feed never runs inside daphne or a Celery worker.

### 4.6 Browser push and pages

**4.6.1 Messages**

- **`venue_quotes` on `dashboard_live`.**
  - Every accepted dashboard socket receives it, with the same refusals as today ✓.
  - At most 4 a second per instrument, coalesced, carrying only instruments that changed. A full batch every 5 s repairs anything the channel layer dropped silently (it holds 100 messages per channel).
  - Payload: `{"type":"venue_quotes","t":<server ms>,"full":false,"q":[{"s":"<symbol>","i":<iid>,"b":"…","a":"…","vt":<eToro Date ms>,"c":<confirmed ms>,"g":"live","ch":"ws","dc":<eToro daily close or null>}]}`. Prices are strings in eToro's own digits.
- **`marks` per user, on the eye socket** (`push_eye_event(user, "marks", …)`).
  - The eye socket is per user, refuses locked and investor sockets, and closes on `session_locked` ✓.
  - At most 2 a second, carrying changed rows keyed by the page key `{{ p.key }}` (map `views.py:1796-1798`): `{key, mark, side, pnl, pnl_src, pnl_age_s, g, vt}`. `pnl_src` is "etoro", "etoro_live" or "awaiting". Per-world totals carry `partial k of n`.
  - A full set every 10 s.
  - P&L never goes on `dashboard_live`.
- **Pages ask for instruments.** A page sends `{"type":"want","symbols":[…]}` on the dashboard socket: catalogue symbols only, at most 20 per socket. Each becomes a TTL want key. This revives the dead `subscribe` handler (map `consumers.py:71-81`).

**4.6.2 Browser engine (`static/js/sv-venue.js`, new)**
- A map from symbol to the latest quote. A newer `vt` wins; an older one is dropped (H1).
- Painting happens in one requestAnimationFrame, from a symbol→elements index built once and rebuilt after each region swap. This replaces the three document-wide scans per tick (map `base.html:4073`, `:4088`, `:4102`). At most one flash per second per cell.
- It re-dispatches `sv:quote` and `sv:marks` DOM events for page scripts.
- After any server render (the 60 s sweep, the 20 s panel cache, the 15 s instrument preview), it re-applies its newer values in the same frame, so a cell never steps back.
- Ages are re-counted every second, corrected for the gap between the server clock and the browser clock.
- The dashboard socket's `alive` flag drives `body.sv-quotes-paused`: grey chips that say "live prices paused".
- `applyTick` (outside-quote ticks) never paints the main cell of a symbol the feed covers; it fills only the outside-quote slot.
- The watchlist rail matches through `dhSym` (fixes ✓ `base.html:4090`).
- The eye `add()` returns early for `marks` and `pnl`.

**4.6.3 Pages**

| Page | Live parts |
|---|---|
| Shell: headband, watchlist rail, status pill | The cell shows eToro's mid, labelled "eToro mid" in the hover. The hover shows SELL (bid), BUY (ask), spread, "eToro · live" or the age. Held eToro instruments join the fixed headband list (map `core/context_ui.py:18-27`). The day change uses eToro's daily close (the snapshot's `DailyClose` once M2 proves it, else eToro's daily candle); otherwise it is labelled with its own source. The pill shows the feed's state |
| `/positions/`, `/portfolio/`, `/command/` (hero and the PORTFOLIO tab), the bottom headband, "At the broker" | Current (the row's closing side, in eToro's digits instead of 4 decimals ✓ `views.py:1865`), P&L, P&L %, R, all patched by key. Wording: "eToro · live", "eToro · 12 s", "eToro's own · 8 s", "closed". The broker panel moves into a live region |
| Instrument page | The hero, the quote card and the deal-ticket buttons (BUY = eToro ask, SELL = eToro bid; disabled with a reason outside LIVE), from `sv:quote`. The 15 s preview stays as a backstop. The forming candle is welded only once M5 has measured eToro's candle close, and only on an eToro series |
| TAKE TRADE | "BUY at eToro's ask … · live", updated live. "Sized at X (eToro ask, N s ago)". "Price moved: preview again" once the executable side moves more than 0.25 R or past the slippage budget. `mark_delayed` is shown (map `manual_trade.py:2140`) |
| Close dialog | "Mark now" is the live closing side. "Books at" says "eToro's executed price" from F8 on |

**4.6.4 Latency budget**

| Leg | Time |
|---|---|
| eToro → server | M2 measures it (arrival − Date) |
| Parse and store | < 5 ms |
| Coalescing | ≤ 250 ms |
| Channels and network | 20-150 ms |
| Paint | ≤ 16 ms |
| **Quote on screen** | **about 0.2-0.5 s plus eToro→server** |
| **P&L on screen** (marks every 500 ms) | **about 0.3-1.0 s plus eToro→server** |

### 4.7 P&L like eToro

**4.7.1 eToro's own figure, the anchor (F4)**
- `EtoroTrader.pnl_book(world)` reads `GET /api/v1/trading/info/real/pnl` (measured 200, read-only, on the real key ✓) and the demo path from the same tables. It gives three answers: figures, no figure, or unreadable.
- **Per position:** positionID, instrumentID, isBuy, units, openRate, openConversionRate, pnlVersion, totalFees, totalExternalFees, and `unrealizedPnL{pnL, pnlAssetCurrency, closeRate, closeConversionRate, timestamp}` [E19].
- **Cadence:**
  - every 11 s while a real eToro position is open in an open market; eToro caches for 10 s [E22], so reading faster buys nothing, and 11 s rather than 10 s keeps each read past the cache's edge (M3 checks that `unrealizedPnL.timestamp` advances on every read, which also rules out a cache whose life is renewed by each read);
  - every 60 s when every held market is shut;
  - demo every 30 s, and only while a demo row is open;
  - one extra read 11 s after each fill or close.
- **Priority:** P5, background. These are the first reads refused under pressure; the age then shows.
- **Storage:** `etoro_pnl:{world}` in Redis (TTL 1 h): read time, per-position figures and totals.

**4.7.2 Identifying the formula (F7; Design 2's method)**

Notation:
- s = +1 for a long, −1 for a short;
- u = units, O = openRate, K0 = openConversionRate;
- C = the closing side (bid for a long, ask for a short [E24]);
- K = the current conversion.

The candidates, in Decimal:

| Name | Formula |
|---|---|
| V-now | s·u·(C − O)·K |
| V-both | s·u·(C·K − O·K0) (the help-centre formula for non-USD instruments) |
| V-open | s·u·(C − O)·K0 (what Sauron does today, map `forex_bot.py:78-104`) |

How calibration works:
- Each `/pnl` read evaluates every candidate at **eToro's own inputs** (closeRate, closeConversionRate, openRate, openConversionRate, units) and compares the result with pnL.
- A (world, pnlVersion, class) triple becomes **calibrated** when one candidate matches within 0.005 on ≥ 20 consecutive reads across ≥ 2 positions, with no miss. The world is part of the key: M3 measures demo, and the spec's demo and real breakdown schemas already describe `fxValueImpact` differently (asset currency vs account currency, S-c), so a demo calibration never lights a real row.
- A later miss makes it **uncalibrated** and writes a transition.
- Latency cannot contaminate this check, because it uses eToro's inputs only.

Side checks:
- closeRate against the ring's closing side at `unrealizedPnL.timestamp` ± 1 s: does the stream carry eToro's valuation price (U2)?
- closeConversionRate against eToro's `conversionRateBid/Ask`: which side does eToro use (M3)?

**4.7.3 Live P&L between figures (F7; Design 1's method)**
- With f the calibrated formula, at time t: **shown = pnL_e + f(C_t, K_t) − f(cr_e, k_e)**. Here pnL_e, cr_e and k_e are the pnL, closeRate and closeConversionRate of eToro's last figure.
- At eToro's own timestamp this is exactly eToro's figure. Anything constant inside eToro's figure carries through: fees, rounding, fxValueImpact [E33].
- It is shown only when all of these hold:
  - the pair is calibrated;
  - the instrument's grade is LIVE;
  - K_t is eToro's and fresh:
    - K ≡ 1 for USD-quoted instruments;
    - otherwise, the conversion pair's eToro stream once M3 proves it, or REST `conversionRateBid/Ask` ≤ 2 s old.
- Otherwise the cell shows eToro's own figure with its age.
- Why the conversion matters: on a 10,000-unit position on a pair quoted in NZD (about 18,000 NZD of value), a 0.0001 move in NZDUSD shifts V-both by about 1.80 USD. A stale conversion therefore cannot be "to the cent".

**4.7.4 What a P&L cell shows (built on pnltruth's overlay)**

| Tier | When | Label |
|---|---|---|
| 1 | Live, calibrated, conversion live | "eToro · live" (anchor plus change) |
| 2 | eToro's own figure ≤ 60 s old | "eToro's own · N s" |
| 2b | eToro's own figure older than 60 s | "eToro's figure · N min ago" |
| 3 | No eToro figure | "awaiting eToro". Sauron's own estimate appears only with the words "estimate, not eToro's", never coloured like a real P&L |

- **Tier changes never step back in time (I4).** When tier 1's conditions are lost (stream not LIVE, conversion stale, calibration lost), the cell does not jump back to eToro's last figure, which is up to 10 s older than the live value it was showing. It keeps the last live value, frozen, greyed and aged ("eToro · live paused · N s"), until an eToro figure whose `timestamp` is newer arrives; then it shows that figure. The same newest-by-time rule applies between every tier.
- **Never:** an outside price, a mid, LiveQuote's conversion, or a price rebuilt from P&L [E23].
- **Fees:** totalFees and totalExternalFees are shown beside the P&L, never added to it. M3 settles whether eToro's app P/L includes them.
- **Totals:** the sum of the rows, marked `partial k of n` whenever any row is on tier 3.

**4.7.5 Proof**
- `manage.py pnl_parity --hours 24` and the line on /health/: "P&L matches eToro to the cent on X% of reads (class, pnlVersion, formula)".
- This is the running proof of "to the cent".

**4.7.6 Why the reported pair differed (Sauron showed a gain of several dollars, eToro a small loss)**

| Cause | Today |
|---|---|
| Price | Yahoo's `last` or `previousClose` instead of eToro's bid |
| Conversion | NZD→USD frozen at entry (V-open) instead of eToro's formula |
| Age | Up to 900 s old, plus the 60 s sweep |
| Fees | Not modelled |

F4 removes all four from the screen by showing eToro's own figure; F7 then makes it live.

### 4.8 Account reads and the private stream

- **Unchanged:**
  - equity, cash and margin, read by the sync (60 s at P2 on etbudget's interim cadence). The live gates read the result (map `risk_gate.py:344-373`);
  - the `/portfolio` sync and the reconcile. Reconcile is tuned to the ~60 s portfolio lag (map `PORTFOLIO_LAG_S`).
- **`/pnl` display reader:** §4.7.1.
- **Private stream (F12):**
  - M2 records `private:demo` first.
  - `private:real` then joins the same connection **as a hint only**: an order or close update triggers the existing P1 confirmation reads at once (the fill lookup, and F8's close-order lookup).
  - It is never the only source of a booking [E11].

### 4.9 Request budget (per key pair, per rolling minute)

**Limits.**
- Spec [E15-E16]: market 120, account 60, execution 20 per mode.
- Portal guide: 60 reads a minute.
- etbudget's guesses (map): market 60 (P3 ≤ 54, P5 ≤ 30); account 30 (P2 ≤ 28, P5 ≤ 15); execution 20; lookups 18.

| Family | Main today | etbudget interim | With the stream LIVE (F6-F7) | Stream down | After F9 + F10 |
|---|---|---|---|---|---|
| Market | Marks: 1 per held row per 300 s. Proposals ~4/min (P4). Last looks (P1). Candles (P5, budget-capped) | + the interim beat: held real instruments every 30 s at P3, ≤ 12 single reads a minute (2 a minute once the batch is proven) | + watchdog ≤ 2-12 at P5 (floor §4.5.6) | + fallback at P5, the feed's REST ≤ 15 a minute in all | Marks 0, proposals 0, while LIVE. Last looks, candles and the watchdog stay; the interim beat retires at the end of F11 |
| Account | ~1 | ~2-4 | + `/pnl` ≤ 6 real + ≤ 2 demo (P5), + 1 after each fill or close | same | same |
| Execution | as orders occur | same | same | same | same |
| Default pool (stop/target PATCH, trade history) | as care moves occur | same | same | same | + care moves ≤ 1 per row per 60 s, ≤ 6/min overall, ≥ 3 s apart (etbudget counts PATCH as execution, the stricter way) |
| Lookups | fill lookups | same | same | same | + 1 per close (F8); history ≤ 1 per 5 min while an exit is pending |
| WebSocket | none | none | 1 connection; subscribe batches ≤ 1/s | reconnect with backoff | same |

**Rules**
- P0 and P1 (closes, stop moves, cancels, kill switch, orders, last looks) are never refused or delayed by anything here.
- The feed's REST reads are background reads.
- No feed path calls /search.
- No 1 Hz REST polling, ever [E31].
- Under a stream outage the worst case is the feed's 15 + candles + the interim beat's 12 + engine reads. etbudget's market cap of 60 holds the total for P2-P5 (P5 refused first, then P3); P0/P1 are never refused and can overrun it, which is today's rule. The portal's "60 reads a minute" may cover the account reads too [E15]; M1 and M3a settle whether market and account draw on one pool.
- PATCH is on eToro's default pool, not the execution pool [E16]. etbudget counts it in execution, the stricter of the two, and the loop still spaces its PATCHes ≥ 3 s apart.
- A burst of closes (the kill switch) can exceed the execution quota of 20 a minute: F2b's 429 rule applies.

---

## 5. Source arbitration

### 5.1 Authority

- `authority(instrument) = "etoro"` when the instrument has a verified eToro id (adopted only on an exact spelling match, map `etoro_client.py:1540-1588`) **and** any of these holds:
  - an open Sauron row routed to eToro, real or demo;
  - a position in `EtoroAccount.broker_positions`;
  - an enabled config routing it to eToro;
  - an open ticket or close dialog for it at eToro;
  - a watchlist entry.
- Otherwise authority is `reference`, and today's path applies.
- Authority is recomputed every 10 s. Leaving eToro authority needs 60 s of absence.
- Authority never depends on any quote's state, which is why a source can never flap.

### 5.2 Channel stores and the read-time choice

- **eToro records.**
  - WS: `vq:ws:{iid}`, written by the feed only.
  - Feed REST: `vq:rest:{iid}`, written by the feed's watchdog and the Celery fallback only.
  - Engine REST: `etoro_rates:r:{world}:{iid}`, etbudget's cache, written by the engine's own rates reads exactly as today. Read-only to the feed until F9; from F9 (`venue_marks_live`) the two REST records become one compare-and-set store.
- **Every feed write is a compare-and-set by eToro's Date** (a Lua script, with an in-memory twin for tests):
  - an older Date never replaces a newer one;
  - a "0" or price-less answer never replaces a priced one; the absence is recorded beside it, and it never refreshes the priced record's confirmation time.
- **Read.** `current(iid)` is the newest of the records, by (Date, then PriceRateID once M2 proves it only increases and is shared by both channels). On a tie the WS record wins. Comparing Dates across channels is valid only once M2 shows that the same PriceRateID carries the same Date on both; until then, and in F6 only, the comparison is recorded, never used.
- So a change of channel is a choice made at read time. No write can step backwards (I4).
- Market data carries no world (map `etoro_client.py:76-77`; ✓ one key pair answers both worlds, `:1400-1408`). The REST reader takes the newest of the world keys.

### 5.3 What counts as an eToro quote

| Rule | Input | Outcome |
|---|---|---|
| W1 refuse (counted) | Missing bid or ask (price-less frames [E6-E7]); a value ≤ 0, non-finite or unparsable; bid > ask; a spread above 10% of the mid; a v2 `quoteType: delayed` [E14] (display only, labelled); an id not in the verified table; a topic that does not parse | not stored |
| W2 newer | eToro Date newer than the store | replace; confirmed at arrival |
| W3 same | Same Date and same sides, or the same rate id | confirmation only |
| W4 conflict | Same Date, different sides | keep the stream's; count `same_ts_conflict` (M2 shows whether it ever happens) |
| W5 older | Older Date | never replaces. A snapshot older than the store logs `snapshot_older` and confirms nothing |
| W6 price-less frame | `{Date, PriceRateID}` | topic liveness only. A per-instrument confirmation only if M2 proves these frames are per-instrument heartbeats |
| W7 untimed REST | A REST answer without `date` | display only, labelled "untimed"; never money |

**One-sided updates.** If M2 shows eToro sends them, they are merged with the other side only within the same subscription session and only when the Date is not older. Otherwise they are dropped and counted.

**Clock skew.**
- The median of (arrival − Date) over the last 200 frames is network latency plus clock offset; the two cannot be told apart from it. So it is never subtracted from latency (that would make the median latency zero by construction) and never used to "correct" an age.
- Skew is checked independently: the host's NTP state (M6), and the HTTP `Date` header of eToro's REST answers against the host clock (one-second resolution). A median below 0, or above 2 s, or an HTTP-Date gap above 2 s raises one health warning.
- Print ages are raw (now − Date, floored at 0). Confirmation ages use Sauron's own clock (arrival), so skew cannot affect them; money decides on confirmation ages.

**Jumps.**
- A print that moves past `JUMP_PCT[class]` (✓ `mark_sanity.py:53-54`) from the last LIVE price within 15 min is stored and shown: it is eToro's. It is flagged `unconfirmed`.
- Money treats it as not LIVE until it is confirmed by either:
  - a second distinct print at that level ≥ 200 ms later, or
  - a P0 REST read that returns it (≤ 2 tries in about 3 s).
- **Refuted** (a newer eToro print or REST answer, later Date, back near the old level): the newer price is the price; the glitch is discarded for money, kept on screen as history, and counted. Nothing acts on a refuted print.
- **Unreadable** (no newer print, both reads fail):
  - a row eToro holds no stop for acts on it: it has no other protection, and an eToro stop would have acted on eToro's print too. Every such case is listed in the shadow report before F2a is turned ON;
  - a row eToro protects waits, since eToro's stop protects it.

### 5.4 Freshness and grades

**Confirmation.** Evidence, at a known moment, that the stored price was still eToro's current price. It counts as:
- a priced push, at its arrival;
- a proven per-instrument heartbeat (W6);
- a REST answer whose Date is not newer than the store, at its arrival − **C_rest**.

**C_rest** is the REST server-cache bound measured by M1 and M2 [E30]:
- until measured, C_rest = 60 s, so REST alone never makes a price LIVE;
- reads 3 s apart that advance cannot show a cache shorter than 3 s, so M1 alone gives at best C_rest = 3 s (when `date`/`priceRateID` advance in ≥ 90% of pairs on an active instrument), never 0;
- M2 measures it directly: for each REST read during the probe, how far REST's Date trails the stream's latest Date at that moment. C_rest = that lag's p99, if smaller than M1's bound;
- otherwise C_rest = the measured maximum.

**Ages.**
- `confirm_age` = now − the latest confirmation.
- `print_age` = now − eToro's Date (skew-corrected).

**Grades** (one pure function):
- **LIVE:**
  - the session is open for the purpose (§5.5);
  - the quote is valid;
  - it is not an unconfirmed jump;
  - confirm_age ≤ L[class];
  - if the current record is the WS one: the connection is healthy, the topic is acknowledged and not behind, and trust has been regained (§5.6).
- **RECENT:** L < confirm_age ≤ S.
- **STALE:** confirm_age > S. The record is kept up to 4 days, for display only.
- **CLOSED:** the session is shut, and eToro's last price stands as the close.
- **NONE:** there is no eToro record.
- **Flags:** `quiet` (print_age > EQ[class] while LIVE), `unconfirmed_jump`, `skew`, `behind`.

**Thresholds by class.** These are starting values. After M2: Q = max(5 s, 3 × the p99 gap between priced pushes in open sessions), and L = Q + 5 s. Every change is logged.

| Class | Q: quiet → pull the watchdog forward | L: LIVE while confirm_age ≤ | S: STALE after | E: entries need confirm_age ≤ | EQ: entries refuse once eToro's price has been unchanged for more than | Entry settle after a reopen |
|---|---|---|---|---|---|---|
| Forex | 10 s | 15 s | 60 s | 2 s | 60 s | 5 min |
| Crypto | 10 s | 15 s | 60 s | 2 s | 60 s | — |
| Index CFD | 10 s | 15 s | 60 s | 3 s | 60 s | 5 min |
| Commodity CFD | 15 s | 20 s | 60 s | 3 s | 120 s | 5 min |
| Stock/ETF | 60 s | 65 s | 120 s | 5 s | 300 s | 5 min |

A quiet topic stays LIVE only while REST confirmations keep confirm_age ≤ L. With the default REST floor of 30 s (§4.5.6) it drifts to RECENT between watchdog reads: the screen shows its age and money takes today's wire path, which is the safe direction. Once the floor is lowered below L − C_rest, the watchdog keeps it LIVE as long as REST shows nothing newer.

### 5.5 Sessions (`market_data/venue_session.py`)

- **The clock combines three things:**
  - `core.exchange_status.market_clock`, which knows daylight saving and holidays ✓ (its FX week already follows New York 17:00, ✓ `:470-500`);
  - eToro's forex daily break, taken as five minutes from New York 17:00 (22:00 UTC in winter, 21:00 UTC in summer), not a fixed GMT time: E26's sources conflict and move with daylight saving. M2 measures it this winter; it is measured again in the first week after the March change. Until a regime is measured, entries refuse in every candidate window of that regime (in summer both 21:00-21:05 and 22:00-22:05 UTC; protection is unaffected), and no feed alarm fires in any of them;
  - the snapshot's `IsMarketOpen`, once M2 proves it flips at the real close.
- **Asymmetric rule.**
  - Protection treats a market as open when either source says it is open.
  - Entries treat it as open only when both say so and the reopen settle period has passed.
  - When they disagree, the screen says "eToro says open" or "eToro says closed".
  - A disagreement can therefore only hold back an entry, never protection.
- **Weekend.** CLOSED, with Friday's eToro price. Its Date is Friday's, so it can never look fresh (this fixes harm 15).
- **Reopen.** The first prints, with their real spread, are what eToro's own stops act on. A gap past the jump bar is confirmed as in §5.3.
- **Halts.** There is no reliable signal [E10, E27]. The quiet flag applies: entries refuse past EQ, and protection is unaffected because nothing moves.
- `market_clock` itself is not changed: paper, Morgul and `venue_mark` read it today.

### 5.6 Hysteresis (no money decision ever waits on it)

**Stream trust after a (re)connect, per instrument.** Trust needs all of these:
1. the login is acknowledged;
2. the subscription is acknowledged;
3. a snapshot or a first priced push has arrived;
4. two distinct priced pushes have arrived, or one watchdog check has shown REST is not newer;
5. 5 s of dwell.

Until then the WS record is not a candidate, and REST carries the instrument. The REST fallback has been running since 3 s after the stream became unhealthy and stops only 30 s after it is LIVE again. Trust is lost immediately.

**Display badge.**
- LIVE → degraded is shown at once, with the age (H7: degraded is always visible as degraded; the grade thresholds L and S already absorb a late push, so a further delay would only show a stale price as live).
- A degraded badge stays at least 5 s.
- It recovers on the second fresh confirmation.
- The price itself repaints on every eToro tick.

**Outside-quote slot.** Shown after eToro has been STALE for ≥ 30 s; hidden after eToro has been LIVE for ≥ 10 s.

**Subscriptions.** An instrument leaves after 60 s unwanted, so a row that is closed and reopened does not churn.

### 5.7 Outside quotes ("references")

- **They qualify as a second opinion only when all of these hold:**
  - same instrument (the stand-in check ✓ `venue_mark.py:343-358`);
  - a real-time stream source: `oanda_stream`, `binance_ws` or `finnhub_ws`;
  - written ≤ 120 s ago.

  Pollers never qualify.
- **Band.** The class jump bar, mid against mid, each mid taken from its own coherent quote.
- **Uses, and only these:**
  - **Entries:** refuse when a qualifying reference disagrees beyond the band (today's rule, kept).
  - **Protection:** never blocked. One staff alert per episode.
  - **Look again:** one P0 eToro read for a row eToro holds no stop for, when eToro is not LIVE and a qualifying reference is beyond the row's level (≤ 1 per row per 10 s, F9).
  - **Display:** the labelled slot, with source, age and the gap to eToro (shown at ≥ 0.05%, map `chart_source.py:81`).
- **Without a streamer.** With no streamer running, entries have no second opinion. The jump rule and the last look still apply.

### 5.8 Every consumer, in every grade

| Consumer | LIVE | RECENT | STALE / NONE | CLOSED |
|---|---|---|---|---|
| Main price cell (headband, rail, hero, positions "Current") | eToro's bid/ask; compact cells show the mid, labelled; positions show the row's closing side. "eToro · live" | Same price, amber "eToro · N s" | Last eToro price, greyed: "eToro · N min · feed down" or "awaiting eToro". Outside quote only in its slot | eToro's last price: "closed · eToro close hh:mm" |
| P&L cells (positions, portfolio, command, headband, broker panel, Horde) | Anchor plus change, if calibrated and the conversion is live; else eToro's own figure with its age | eToro's own figure with its age | eToro's last figure with its age, or "awaiting eToro". Never recomputed from an outside quote | eToro's last figure |
| Deal ticket buttons and preview | BUY = eToro ask, SELL = eToro bid, live; "sized at X (eToro ask, N s ago)" | Shown with age; "the server re-checks at send" | Disabled: "no eToro price" | eToro's last prices, labelled "market closed: eToro holds an order until the open" [E28]; what may be sent follows today's rule |
| Bot-side SL/TP on rows eToro holds no stop for (P1) | Act on the closing side (jump rule, §5.3) | One P1 wire read (≤ 1 per row per 30 s); act on its closing side | The same P1 wire read. If it fails: no action, and an alert after 60 s in an open session that links to the row's CLOSE button (the existing CLOSE path with its own session rules; never a close sent from a message). A qualifying outside quote beyond the level → one P0 read (≤ 1 per row per 10 s) | Nothing (eToro executes nothing either). At the reopen, the first confirmed eToro prints decide |
| Care, trailing, eToro stop moves | Act on the closing side; PATCH ≤ 1 per row per 60 s, ≥ 3 s apart and ≥ the minimum step; ≤ 6/min overall | Today's path, never a hold where today acts (I13): one wire read (protected rows at today's cadence and priority, P3; unprotected rows at P1, ≤ 1 per 30 s), acted on at its closing side | The same wire read. If it fails, hold, as today, and alarm after 2 min in an open session for a held row | Hold |
| Vanished-stop net, time stop | Run | Run | Run | Run |
| CLOSE button, kill switch | Send at once | Send at once | Send at once | Send (eToro queues it [E28]) |
| Exit booking (every path) | eToro's executed figure, or pending | Same | Same | Same |
| Mark sanity verdict | Jump check on eToro prints. Outside quotes never block protection; entries are still refused by a qualifying reference that disagrees | The wire read is judged as today, without the block | — | — |
| Entries (proposals, size, gate, last look, ticket send) | Executable side, if confirm_age ≤ E, print_age ≤ EQ and the session is open for entries. Otherwise the last look's P1 wire read decides with today's checks | The last look's P1 wire read decides (today's path) | Refuse | Bots refuse (today they hold outside their sessions); the manual ticket follows today's rule, labelled |
| Conversion (value per unit, cash-gate need, minimums) | eToro's conversion (REST `conversionRateBid/Ask` ≤ 60 s old, or the proven stream); the conservative side for sizing | The same, if ≤ 60 s old; else sizing is refused | Sizing refused. Display uses closeConversionRate from eToro's last figure | Sizing refused |
| Level editor | Judged against the closing side | One P0 wire read judges it | If no eToro price can be read, the edit is still allowed after an explicit "no live price" confirmation. Never refused for want of a price; eToro validates | The at-the-close rule (map `venue_mark.py:505-524`) |
| Position review | eToro's price | eToro's price, with its age | Stale eToro price, with its age; never an outside quote | The at-the-close rule |
| Morgul eToro feed guard (G10v) | Quiet | Quiet | WARNING after 120 s in an open session for a held instrument; once per episode; one recovery note. Never the brake before F11 | Silent |
| Price alerts (eToro instruments) | Fire on the side the alert names (default: the mid, labelled) | Don't fire: "waiting for eToro" | Don't fire | Don't fire |
| Posture / market stress | eToro's index CFD daily candles plus eToro's live value | Yesterday's series only | Yesterday's series only | eToro's close |
| Orcs census and wakes | An eToro sample; wakes on the closing side | No sample, no price wake | None. A gap is never a shock | None |
| Paper rows of eToro instruments | Fill and mark on eToro's sides | Refuse or hold | Refuse or hold | Refuse (market shut) |
| Book value (`live_book_value`) | eToro's `/pnl` figures, with age | Same | Same, marked `partial` | Same |

**Wire reads.** A wire read that lacks one side (eToro's spec always carries both) is handled conservatively:
- an unprotected row acts on lastExecution, flagged "not the closing side";
- care moves hold.

### 5.9 Transitions and alarms

**What is logged.** Every change of grade, channel, trust, outside-quote slot, calibration or connection writes:
- one `FeedTransition` row: at, instrument, kind, from, to, reason, eToro Date, rate id, epoch. At most 6 per instrument per minute, plus a count of the rest;
- one log line: `venue_quote.transition sym=… from=LIVE to=RECENT why=no_confirmation_16s channel=ws epoch=17`.

The last 50 are shown on /health/, and `manage.py feed_transitions --hours 24` reads them.

**Alarms** (through the existing `notify_staff`):

| Condition | Alarm |
|---|---|
| Stream down ≥ 120 s while REST carries | Info, once |
| Both channels failing ≥ 120 s for a held instrument that is open for protection | Warning, once; one recovery note |
| An unprotected real row with no eToro price for 60 s in an open session | Warning, with a link to the row's CLOSE button (the existing path and its session rules; no close is ever sent from a message) |
| ≥ 3 episodes in 30 min | One "flapping" alarm, then 30 min of silence |
| A held instrument "behind" ≥ 3 times in 10 min | Once |
| Login refused | Once per 60 min |
| Outside quote disagreeing (protection proceeds) | Once per episode |

No alarm fires in a shut session, in an unmeasured candidate break window (§5.5), or for an instrument that is only watched.

### 5.10 The transition test matrix (H8)

**Harness (`tests/feed/harness.py`).**
- It runs the **real consumer code** against:
  - a fake clock;
  - a fake WS server;
  - fake REST rates with RateLimit headers, 206, 429 and Retry-After;
  - fake LiveQuote writers;
  - a fake private stream;
  - a fake eToro trader that records every send;
  - the in-memory store twin.
- No new dependency: the venv has no hypothesis, freezegun or fakeredis ✓.
- Random timelines use `random.Random(seed)`: 50 seeds in CI, 1,000 through `manage.py feed_soak`.
- "Today" in the replay is main plus the in-flight etbudget, its interim LiveQuote writer included (I13).
- A registry lists 20 adapters: display, plus M1-M19 from the map:

| Path | What it is |
|---|---|
| M1 | Tick, care and SL/TP |
| M2 | Mark sanity |
| M3 | Bot entry |
| M4 | Ticket |
| M5 | CLOSE |
| M6 | Kill switch |
| M7 | Drain |
| M8 | Reconcile |
| M9 | `resolve`, `bookable`, `for_booking` |
| M10 | Level editor |
| M11 | Position review |
| M12 | Conversion |
| M13 | Stress and posture |
| M14 | Morgul |
| M15 | Alerts |
| M16 | Paper |
| M17 | Book value and gates |
| M18 | NL trader and legacy |
| M19 | Orcs |

- **Completeness pin.** CI fails when a timeline lacks a run against any registered adapter. It also fails when a money module reads LiveQuote or the eToro rates without being registered (a ratchet).

**Assertions.** A6, A12 and A15 apply to every run.

| Id | Must hold |
|---|---|
| A1 | The main cell of an eToro instrument holds only eToro numbers |
| A2 | No store value or cell moves backwards in eToro's time; no step that eToro did not print |
| A3 | Every price and P&L carries its source and age; a degraded grade is styled as degraded |
| A4 | Outside quotes appear only in their slot, labelled, with their gap |
| A5 | A displayed P&L is eToro's figure or the calibrated anchor plus change; never an outside quote, a mid or a foreign conversion |
| A6 | Money paths read only LIVE eToro prices through `money_price`, or today's eToro wire path. A spy fails any LiveQuote or outside-quote read in a money path |
| A7 | With every price source dead, protective sends happen in the same tick or click |
| A8 | No stop, target or care action except on eToro's closing side; none on an outside quote. An unconfirmed jump is confirmed first, then acted on by the protected/unprotected rule |
| A9 | No entry is admitted or sized except on eToro's executable side at LIVE and fresh, or on today's last-look eToro wire read |
| A10 | Every booked exit is eToro's executed figure or "pending". The gate's provisional figure is never positive. Never an outside quote or bars |
| A11 | No alarm in a shut session; one alarm per lasting episode plus one recovery note; the flapping guard holds |
| A12 | Exactly one `FeedTransition` per transition, with a reason, rate-capped |
| A13 | eToro rows use eToro's conversion, with its age; never LiveQuote's |
| A14 | Series readers (stress, Orcs census, paper evidence) never see a source switch inside one series; a gap stays a gap |
| A15 | With the feed absent or a switch OFF, decisions equal today's replay |
| A16 | A badge changes at most once per its minimum display time; the outside-quote slot follows its hysteresis |

**Matrix.** Every timeline × every adapter; the cell lists the assertions that timeline targets beyond A6/A12/A15.

| Timeline | Display | Protection (M1 M2 M5 M6 M10) | Bookings (M5-M8, M17) | Entries (M3 M4 M12) | Valuation and context (M9 M11 M13-M16 M18 M19) |
|---|---|---|---|---|---|
| T1 Stream drops for 3 min → REST carries → stream back with a snapshot | A1 A2 A3 A16 | A7 A8 | A10 | A9 | A14 |
| T2 One topic silent while REST advances ("behind") | A2 A3 | A8 | — | A9 | A14 |
| T3 A reconnect snapshot older than the store; a late or cached REST answer older than the store | A2 | A8 | A10 | A9 | A14 |
| T4 Only price-less frames, for minutes | A2 A3 | A8 | — | A9 | — |
| T5 Bad frames: crossed, zero, NaN, one-sided, unknown type, binary, duplicate id, unknown topic | A1 A2 | A8 | A10 | A9 | A14 |
| T6 A genuine jump (2 prints) vs a glitch (1 print), on protected and unprotected rows | A2 | A7 A8 | A10 | A9 | A11 A14 |
| T7 Friday close → weekend → Sunday reopen with a wide spread; the daily forex break | A3 A16 | A8 | A10 | A9 | A11 A14 |
| T8 Quiet or halted instrument in an open session | A3 | A8 | — | A9 | A11 |
| T9 REST 429 with Retry-After; a budget refusal; the shared pause; Redis unreadable | A3 | A7 A8 | A10 | A9 | A11 |
| T10 An outside quote absent, stale, fossil, stand-in, disagreeing, agreeing, or beyond a level | A1 A4 | A7 A8 | A10 | A9 | A11 A14 |
| T11 Conversion fresh → stale → missing | A5 A13 | — | A10 | A9 A13 | A13 |
| T12 `/pnl` fresh → cached → failing; calibration reached → lost; pnlVersion changes; a fee is charged | A5 | — | — | — | A11 |
| T13 Login refused; TooManyRequests on subscribe; topic cap reached | A3 | A7 A8 | — | A9 | A11 |
| T14 eToro's Date 3 s ahead of or behind the host clock | A2 A3 | A8 | — | A9 | — |
| T15 Held → closed → reopened within 60 s; a ticket opened and closed | A1 A3 | — | — | A9 | — |
| T16 A money switch turned ON then OFF while a position is open | A1 | A8 (no step in the stop basis, no double close) | A10 | A9 | A15 |
| T17 Feed process killed and restarted; the Celery takeover | A3 | A7 A8 | A10 | A9 | A11 |
| T18 Both channels dead for 5 min with an unprotected real row | A3 | A7 (alert linking to CLOSE; no action on an outside quote) | A10 | A9 (refuse) | A11 |
| T19 An exit pending a price across the daily-loss gate; eToro's figure arrives later; the same with no stop, no ring, no /pnl figure | A5 | — | A10 | A9 (gate) | — |
| T20 Clock says open while eToro says closed, and the reverse | A3 | A7 A8 | A10 | A9 | A11 |
| T21 etbudget's interim LiveQuote writer on, off, and out-ranked by a running stream; then retired (end of F11) | A1 A3 | A7 A8 | A10 | A9 | A14 A15 |
| T22 The week of a daylight-saving change: the FX week's edges and the daily break move by an hour | A3 | A8 | — | A9 | A11 |
| T23 Kill switch with 25 open real rows: the 21st close meets a 429 with Retry-After | A3 | A7 (every close sent; the 429'd ones resent after Retry-After, nothing resent after a timeout or 5xx) | A10 | — | A11 |
| T24 A P&L cell in tier 1 when the stream drops, then eToro's next (older-stamped, then newer-stamped) figure | A2 A5 | — | — | — | — |

**Named regression scenarios:**
- the reported gap;
- an SPX500 CFD held overnight against a re-stamped cash close;
- an NFP release;
- the Sunday reopen;
- crypto at the weekend;
- a 2-minute stream drop on a quiet instrument;
- a target crossed by the mid but not the bid, followed by a stop fill;
- an OANDA stream holding a held pair's LiveQuote while the interim beat's eToro writes are refused (T21);
- a glitch print refuted by the next REST answer on an unprotected row (nothing acts).

---

## 6. Phases

Each phase is one pull request, with its tests written first using fakes. No test calls eToro, a broker or a model API.

### 6.0 Asks to the in-flight branches

**P-a: `claude/etbudget`, before the operator's demo measurement**
1. **Literal commas.** `_rates_get` (✓ `[BUD] etoro_client.py:2256-2265`) passes `params=`. requests 2.34.2 then prepares `instrumentIds=1%2C2%2C3` (✓ offline), which is the form eToro rejects [E13].
   - Build the query with a literal comma; a pre-built `?instrumentIds=1,2,3` keeps it ✓.
   - Test the **prepared URL**, not the params dict, in `tests/test_etoro_rates_batch.py`.
   - Without this fix, `etoro_rates_shape` measures the rejected encoding and can "prove" that batching fails.
2. **`etoro_rates_shape` options.**
   - `--repeat N --gap S`: do `date` and `priceRateID` advance between back-to-back reads? This gives C_rest.
   - `--v2`: v2 status (200 or 206) and the kinds of `quoteType`.
   - `--encoded-commas`: one GET in the old form, to record what eToro answers.
   - Up to 100 ids.
   - Print the names and values of the RateLimit-* or X-RateLimit-* headers, and the spelling of the row's id key.
   - Still kinds only, never a price.
3. **Carry eToro's fields.** Take `date`, `priceRateID` and `conversionRateBid/Ask` from each rate row into the tick dict and the cache value. These keys are additive; existing readers ignore them.
4. ~~No erasing~~ **Withdrawn by the verifier.** Keeping a priced entry over a later "0" would change what `_mark_price` and the time stop's booking read (✓ `[BUD] base.py:3513-3540`, `pending_closes.py:547-557`) without a switch. The engine's cache keeps today's semantics; "no erasing" applies to the feed's own stores (§5.2), and to the engine's cache only from F9.

The compare-and-set by Date comes in F6 for the feed's stores, and in F9 for the engine's cache.

**P-b: `claude/pnltruth` (a08c87b, committed, not merged)**
1. **Tier 1 is probably always empty.** It reads `net_profit` from `/portfolio`. The client calls that key unmeasured (✓ `etoro_client.py:2112-2140`), and the spec has no `netProfit` on open positions [E20].
   - Merge as is; it is harmless, because the row falls through to the estimate and says so.
   - F4 makes tier 1 the `/pnl` figure.
2. **Tier 2 reads an eToro-written LiveQuote.** The feed never writes one, but etbudget's interim beat does (P-c), so tier 2 lights up in the interim: eToro's closing side, converted at the conversion frozen at entry (V-open), labelled "estimate: eToro quote". That label is honest, and the reported gap shrinks to the conversion's drift since entry, plus whatever else eToro's figure holds (fees, if M3 shows they are in it). F7 points tier 2 at the eToro store and eToro's conversion.
3. **Source test.** `_is_etoro_source` (✓ `[PNL] services.py:1090`) becomes `is_venue_source()` in F1.
4. **Age.** Its 900 s window (`ETORO_PNL_MAX_AGE_S` ✓) is too generous for the words "eToro's own". From F4, "eToro's own" applies only up to 60 s.

**P-c: `claude/etbudget`'s uncommitted interim writer (`bot_program/etoro_quotes.py`, beat `refresh-etoro-quotes` 30 s)**
- It is the operator's interim fix and this spec does not redo or block it. It does write eToro into LiveQuote (source `etoro`, rank 70), which I2 forbids for the feed. Read in code, its effects are listed in harm 29.
- Asks, all additive:
  1. Count and show the writes refused because a stream holds the row (`should_write` False): where OANDA, Binance or Finnhub streams an instrument, the interim does nothing, silently.
  2. Label the pushed tick with its source (harm 24), so a switch back to yfinance after a row closes is visible.
  3. Keep its reads at P3 and inside its 12-a-minute cap. The feed adds its own ≤ 15 a minute at P5 (§4.5.6).
- **Its retirement is part of F11, not earlier.** While it holds a row, it also removes the outside second opinion for that instrument (harm 1 relief) and feeds eToro's `last` to paper, conversion, posture, alerts and Morgul. Retiring it before F2a, F9, F10b and F11's switches are ON would bring those harms back. The last F11 pull request retires it and, in the same change, makes `write_quote` refuse `etoro*` sources.

### 6.1 Measurements first (M0-M6)

All are read-only, run demo first on the production host inside the web container. This sandbox's proxy cannot upgrade WebSockets.

| # | When | Command (`./deploy/dc exec web python manage.py …`) | Settles | Decides | eToro requests |
|---|---|---|---|---|---|
| M0 | first | — (P-a merged into etbudget) | — | the measurement tests the right encoding | — |
| M1 | after P-a | `etoro_rates_shape --user <you> --world demo --ids <a>,<b>`; then `--ids <20 to 100 ids>`; `--repeat 20 --gap 3`; `--v2`; `--encoded-commas` (once, and its answer is never recorded as the batch's proof) | Literal-comma batch works; id key spelling; `date` format; an upper bound on the REST cache (3 s resolution at best, §5.4); header names and quota (`RateLimit-Policy` and `-Remaining` values are quota counters, not account figures, and are printed); v2 availability and `quoteType` | Batching on or off; C_rest's first bound; REST pacing; v2 for breadth | ≤ 25 market GETs, P5 background |
| M2 | after F3 | `etoro_ws_probe --user <you> --world demo --ids <held + conversion + one stock> --minutes 15`. Runs (winter time, US clocks changed on 1 November): a weekday; **Friday 20:00-22:30 UTC** (the close, covering both the 21:30 table time and New York 17:00 = 22:00 UTC); **Sunday 21:50-22:40 UTC** (the reopen: the current tables say 22:05; a run at 21:00-21:40 would catch nothing); **21:50-22:20 UTC** (the daily break). Again in the first week after the March change, an hour earlier. Also: `--batch 10,25,50` (one step at a time, 60 s apart, stops at the first refusal, with one REST control read after each step); `--idle-minutes 15`; `--private-demo --minutes 20` while the operator opens and closes a tiny demo position by hand; `--compare-app --ids <one pair> --minutes 2` (one public price line a second while he watches eToro's app); `--candles` (M5) | Login with his key and an honest User-Agent; snapshot fields; push gaps p50/p99 per class; whether price-less frames are per instrument; one-sided updates; Date format and raw latency; whether PriceRateID only increases, and **whether the same PriceRateID carries the same Date on both channels**; how far REST's Date trails the stream's at each REST read (C_rest); behaviour at the close, reopen and break; topic caps; what TooManyRequests means; whether WS operations consume REST quota (RateLimit-Remaining before and after); private message shapes and timing; whether the stream equals the app | Stream or REST-only; C_rest; Q and L per class; heartbeat confirmations; `IsMarketOpen` and the break in the session rule; topic cap; private hints | One WS connection; ≤ 30 REST GETs per 15 min (P5) |
| M3a | after F3 | `etoro_pnl_probe --user <you> --world demo --shape`, run right after an M1 read; it also prints `RateLimit-Policy` and `-Remaining` (quota counters) | Key names and kinds of `/pnl` (one read); whether market and account reads draw on one pool (the portal's 60 a minute) or two (the spec's 120 and 60) [E15] | F4 can ship; etbudget's family caps | 1 account GET |
| M3 | after F3 | First the operator opens small demo positions by hand: a long and a short on a pair not quoted in USD (for example one quoted in NZD), a long EURUSD, one stock CFD, one crypto. Then `etoro_pnl_probe --user <you> --world demo --reads 30 --gap 11` | closeRate's side; closeConversionRate's side; which formula reproduces pnL (≤ 0.5¢, ≤ 1¢, > 1¢); pnlVersion values; whether `unrealizedPnL.timestamp` advances; fee fields; `netProfit` on `/pnl` and `/portfolio` rows. He notes whether eToro's app P/L equals pnL or pnL minus fees | The formula and conversion side (§4.7); pnltruth's tier 1 | ≤ 30 account + 30 market GETs (P5) |
| M4 | after he closes a demo position by hand, and after a demo close that Sauron itself sent | `etoro_close_probe --user <you> --world demo --history --days 2` (finds the hand-closed position: close rate, time, proceeds). `etoro_close_probe --user <you> --world demo --proof <demo short proof id>` reads the close order id Sauron kept from its own demo close answer (the demo short proofs store it: ✓ `short_models.py:94`, `short_proofs.py:1006`; an AssetBotTrade row keeps no such field, and the client returns it only as `orderId`, ✓ `etoro_client.py:3199-3202`) and asks the close-order read with it, printing kinds only. A close made by hand in the app gives no order id to any probe, so it cannot test the close-order read | Whether the documented close-order read works now (it did not on 2026-09-23 ✓); executed rate and proceeds fields; lag; whether a position closed by eToro's own stop appears in history with its rate | F8's booking sources (if the close-order read still fails, F8 rests on history plus pending) | 1-3 GETs |
| M5 | inside M2 (`--candles`) | — | Whether eToro's 1-min candle close is the bid, ask, mid or last execution | The chart weld; candle stamps | 1 candle GET per minute of the run (P5) |
| M6 | with M2 | `docker stats --no-stream; free -m; timedatectl status` (on the host), before and after starting the probe or the feed | Memory headroom; NTP sync | The feed's memory limit; `worker-fast -c`; whether the skew check can be trusted | none |

**What the probes never do.**
- No command subscribes to `private:real` or reads a real-world account endpoint.
- None prints a key, an account id or an account figure.
- None places, changes or cancels anything. A fake-session test enforces GET-only paths.

### 6.2 The phases

---

#### F1: Truth core, one venue-source rule, pins, harm counters, replay harness

- **Scope**
  - **The pure core:** `venue_quotes`; `venue_store` (compare-and-set script plus its in-memory twin); `venue_session`.
  - **One source test:** `is_venue_source()` replaces the three tests.
  - **No effect yet:** while every switch is OFF, `money_price()` answers `Refusal("switch_off")` for every purpose.
  - **Harm counters** (`FeedHarmEvent`; `manage.py feed_harms --days N`) record:
    - every mark-sanity skip of a real row: why, the levels, and whether the closing side crossed SL/TP;
    - every CLOSE refusal for "no usable price mark";
    - how many seconds the kill switch waited before each close;
    - every poller write of `previousClose`, of a price outside the `market_clock` session, or of zero or crossed sides;
    - every exit booked at the mark, at an outside quote, or left pending.
  - **The transition harness, and decision replay:** golden scenarios for M1-M19, with a fake eToro client that records every request, fake LiveQuote writers and a fake clock.
- **Files**
  - New: `market_data/venue_quotes.py`, `market_data/venue_store.py`, `market_data/venue_session.py`, `bot_program/feed_harms.py` (with its migration and command).
  - Edits (the source test only): `bot_program/venue_mark.py:343-358`, `bot_program/mark_sanity.py:64`, `:189-191`.
  - Tests: `tests/feed/harness.py`, `tests/feed/test_truth_core.py`, `test_venue_store_rules.py` (W1-W7 on both implementations), `test_venue_source_one_rule.py`, `test_feed_pins.py`, `test_feed_harms.py`, `test_decision_replay.py`.
- **Pins**
  - Money modules may not import `display_quote` or `reference_quote`.
  - A ratchet list of today's LiveQuote reads in money modules; a new one fails.
  - Feed modules may not import order paths, /search or `instrument_id()`.
  - Only the feed writes `vq:*`.
  - The feed never writes LiveQuote.
- **Money direction:** none. Replay proves equality with today.
- **eToro requests:** none.
- **Switch:** none.
- **Needs:** nothing.
- **Acceptance on the server**
  - `./deploy/dc exec web python manage.py feed_harms --days 7` prints counts by kind. This is the baseline for F2a, F2b, F5 and F8.
  - `/ops/` shows no new switch.

---

#### F2: Protection never waits for a price, and no outside quote blocks it

**Two pull requests, one switch each (§9.14): F2a and F2b.** They can be built in parallel.

- **F2a scope, switch `protective_unblock_live`**
  - The vanished-stop net and the time stop run before the mark verdict and without it.
  - "Disagreed" no longer skips protection. Entries still refuse, and one alert goes out per episode.
  - "Jumped" triggers a P0 confirmation read (≤ 2 tries in about 3 s), by §5.3's rule:
    - confirmed → act now, instead of at the next tick;
    - refuted (a newer answer back near the old level) → the newer answer is the mark; nothing acts on the glitch;
    - unreadable (both reads fail) → act on rows eToro holds no stop for; wait on rows eToro protects.
  - "Frozen" no longer suspends protection; the alert stays.
  - This applies to real rows only.
  - **Shadow while OFF.** For each real row and tick where today's verdict suspends protection or holds a jump, `FeedShadowDecision` records what F2a would have done (act, wait, refuse entry) and, at the next confirmed print, whether the hold cost anything (the closing side's move past the level).
- **F2b scope, switch `close_without_price_live`**
  - **CLOSE** never refuses a live close for want of a mark (✓ `manual_close.py:555-564`).
    - It sends the close, then makes one P0 read to book the exit, through today's booking path (the same `lastPrice` semantics; F8 brings eToro's executed price).
    - If that read fails, it books "pending eToro's price" through the existing unpriced path (`exit_price_unavailable`, NULL P&L).
  - **Kill switch** sends every close first, unprotected real rows first, then reads prices for booking (✓ `kill_switch.py:269-342`, `:845-846`). Today each row can wait about 20 s behind a hanging read.
  - **A 429 on a protective close is resent**, after Retry-After (15, 30, then 60 s when absent), at most 3 times, before the row goes to CLOSE_PENDING. eToro marks a 429 as the only answer safe to resend [E18]; today the close raises on it and waits for the 300 s drain (✓ `etoro_client.py:3197`). A timeout, reset or 5xx is never resent: the drain reconciles it, as today. This matters once the kill switch sends more than 20 closes in a minute (the execution quota [E16]).
  - **Shadow while OFF.** F1's counters already record every CLOSE refused for no mark and every kill-switch wait, with its length.
- **Daily-loss gate (with `close_without_price_live` ON, the switch that creates pending exits; ✓ it skips unpriced exits today, and fails open when every close in the window is unpriced, `risk_gate.py:671-678`, `:782-788`)**
  - A pending exit counts as a provisional P&L = min(0, x), where x is the first available of:
    1. eToro's own last figure for that position (F4's `/pnl` anchor), read ≤ 15 min before the close;
    2. the P&L at eToro's closing side at the close, from the ring (after F6);
    3. the last eToro closing-side print ≤ 15 min old before the close (from the row's stamp);
    4. −1R.
  - With none of these (no figure, no ring, no print, no stop), the row stays "unmeasured" as today, and the gate's words say so. From F8 ON, while such an exit waits for eToro's figure, new real entries on that venue wait too (the safe direction), for at most 1 hour; then the gate falls back to today's words with one staff warning.
  - eToro's figure replaces the provisional one when it arrives (F8). The provisional figure is never positive.
- **Files**
  - F2a: `bot_program/asset_engine/base.py:1548-1660`; `bot_program/mark_sanity.py:91-248`
  - F2b: `bot_program/manual_close.py:357-599`; `bot_program/engine/kill_switch.py:269-866`; `bot_program/engine/etoro_client.py` (the 429 resend, closes only); `portfolio/risk_gate.py:595-829`; `bot_program/pending_closes.py`
  - Each: one key in `LIVE_MONEY_SWITCHES`, seeded OFF; the Wall's count rises by 1 per pull request.
- **Tests first** (`tests/feed/test_protective_first.py`)
  - Every price source dead → every protective path sends (A7).
  - Disagreement → protection acts, entries refuse.
  - Glitch vs crash vs refuted glitch under confirmation reads.
  - Kill-switch ordering, with a fake ticker that hangs 10 s.
  - T23: 25 rows, a 429 with Retry-After on the 21st close → every close is sent; only the 429'd ones are resent; a timeout or a 5xx is never resent.
  - The provisional figure is never positive; T19's no-figure row waits entries at most 1 hour.
  - With each switch OFF, replay equals today.
  - Pin that changes, with the switch ON only: `tests/test_mark_sanity.py:101-116` "a disagreeing second opinion is never out-voted" becomes "entries: never out-voted; protection: never blocked".
- **Money direction**
  - Protective actions happen where today they are suspended or refused.
  - An unprotected row acts on an unreadable jump that today would wait a tick: a needless close is possible if the print was a glitch eToro never repeated. The shadow lists every such case before ON.
  - Kill-switch closes go out up to about 20 s per row sooner when a read hangs; 429'd closes go out again within seconds instead of 5 minutes.
  - Those bookings become pending, instead of refused or booked at a stale mark.
  - The gate counts them provisionally, instead of not at all.
- **eToro requests:** ≤ 2 extra P0 rates reads per suspect jump on a real row (rare), plus one P0 read per manual close that had no mark, plus at most 3 resends per 429'd close.
- **Switches:** `protective_unblock_live` (F2a), `close_without_price_live` (F2b) (PIN, OFF on arrival). These are the recommended first ON.
- **Needs:** F1. Its counters give the before-and-after.
- **Turn-on evidence:** F2a: ≥ 7 days of shadow, every "unreadable → act" case read by the operator. F2b: ≥ 7 days of F1's counters, T23 green.
- **Acceptance on the server**
  - Run `feed_harms --days 7` for the baseline, then turn each switch ON at `/ops/` with the PIN.
  - Seven days later `feed_harms --days 7` shows:
    - zero "protection skipped by a disagreeing reference";
    - zero "CLOSE refused for no mark";
    - kill-switch wait before each send of about 0 s.

---

#### F3: eToro stream client and read-only probes

- **Scope**
  - `bot_program/engine/etoro_stream.py`: the protocol only, no store.
  - The probes `etoro_ws_probe`, `etoro_pnl_probe` and `etoro_close_probe` (§6.1):
    - P5 background, GET-only;
    - they print kinds, counts, timings and matches; never a key, an account id or an account figure;
    - `--compare-app` prints one public instrument price a second.
  - The ticker parse gains date, priceRateID and conversion, unless P-a did it.
  - The no-redirect pin is extended for `etoro_stream.py`:
    - its only network call is `asyncio.open_connection` to the host constant, on 443, with TLS and SNI;
    - a non-101 answer never opens a second connection;
    - Authenticate is built in one function, called only after the 101;
    - no key reaches a log call.

  The whole-tree site list stays the same two modules: the pin counts only FOLLOWERS, and `ClientProtocol` is not one ✓.
- **Files**
  - New: `bot_program/engine/etoro_stream.py`; `bot_program/management/commands/etoro_ws_probe.py`, `etoro_pnl_probe.py`, `etoro_close_probe.py`.
  - Edited: `tests/test_etoro_no_redirect.py`.
  - New tests:
    - `tests/test_etoro_stream_client.py` uses an in-process fake server over asyncio, with the TLS layer injected. It covers:
      - a 3xx → no frame sent;
      - the host is pinned;
      - text frames only;
      - ack matching and batched subscribes;
      - price-less, one-sided, crossed and NaN frames;
      - the snapshot;
      - TooManyRequests and SessionAlreadyAuthenticated;
      - reconnect with a snapshot;
      - backoff never gives up;
      - keys never appear in logs or exceptions.
    - `tests/test_probes_read_only.py`: a fake session records methods and paths, and any non-GET or execution path fails.
- **Money direction:** none.
- **eToro requests:** only the probes the operator runs (each ≤ 30 REST GETs; one WS connection while it runs).
- **Switch:** none.
- **Needs:** F1.
- **Acceptance on the server:** each probe ends with "read-only: N GETs, 0 writes, 0 orders". The results go into `deploy/ETORO_DEPARTURE.md`.

---

#### F4: eToro's own P&L on screen, about every 10 s (display)

- **Scope**
  - `pnl_book()` and the Celery task `etoro_pnl_anchor` (§4.7.1).
  - pnltruth's tier 1 → `/pnl` (P-b).
  - A per-user eye kind `pnl` patches the P&L and "Current" cells by key, until F7's marks arrive.
  - The "At the broker" panel (map `positions_list.html:88-140`) moves into a live region.
  - "Current" shows eToro's closeRate, with its age, when the value comes from the figure.
  - `manage.py etoro_pnl_status`, per world: last read age, reads a minute, refusals, rows covered k of n. No figures.
- **Files**
  - New: `bot_program/etoro_pnl.py`.
  - Edits:
    - `bot_program/engine/etoro_client.py`: `pnl_book`, read-only, P5 background;
    - `config/celery.py`: the beat entry;
    - `portfolio/services.py`: the overlay tiers;
    - `dashboard/views.py`;
    - `templates/dashboard/positions_list.html`, `portfolio_overview.html`, `_command_portfolio.html`;
    - `templates/base.html`: eye `add()` ignores `pnl` and `marks`;
    - `core/platform_control.py`: component `etoro_pnl_display`, ON.
- **Tests first**
  - The `/pnl` parser on the spec's shape and on missing keys (its three answers).
  - World and currency refusals.
  - The decision-module scan (the pnltruth pattern, map `tests/test_venue_pnl.py:448-484`) proves no money module reads it.
  - No cell moves backwards (by timestamp).
  - A P5 refusal shows the age, never a stale figure as fresh.
  - Reads stop when nothing is open.
- **Money direction:** none.
- **eToro requests (account family, P5 background)**
  - Real: ≤ 6/min while a real position is open in an open market; ≤ 1/min when every held market is shut.
  - Demo: ≤ 2/min while a demo row is open.
  - +1 read 11 s after each fill or close.
  - If F4 lands before etbudget, these are background reads, as klines are on main: never a health note, never a pause.
- **Switch:** component `etoro_pnl_display`, ON. `manage.py component off etoro_pnl_display` returns today's display.
- **Needs:** F1, P-b merged, M3a.
- **Acceptance on the server**
  - On /positions/ in an open market, each eToro row reads "eToro's own · N s" with N ≤ 20.
  - Side by side with eToro's app, the figure is the same within one refresh.
  - `./deploy/dc exec web python manage.py etoro_pnl_status` shows ≤ 8 reads a minute and rows covered n of n.

---

#### F5: Outside feeds stop lying

- **Scope, switch `reference_truth_live`**
  - The pollers' session gates move from fixed UTC to `market_clock` (✓ `core/market_calendar.py:6-30`).
  - `previousClose` is never written as a fresh `last` (✓ `tasks.py:58-64`).
  - The index poller stops re-stamping an old close (map `tasks.py:393-396`).
  - `write_quote` stores None for a zero or crossed side (✓ `quotes.py:146-158`; map `alpha_vantage.py:93-95`).
  - The second opinion qualifies only same-instrument, real-time stream quotes ≤ 120 s old (✓ `mark_sanity.py:176-195`).
  - The legacy Sync button stops writing LiveQuote as `etoro` (map `etoro_adapter.py:124-132`). etbudget's interim beat is not touched (P-c): `write_quote` keeps accepting `etoro` until the end of F11.
  - The legacy feed entry is renamed, and `deploy/LIVE_DATA_OPTIONS.md:139` is corrected (✓ it says `--profile finnhub`; the compose profile is `streamers`).
- **Shadow while OFF.** F1's counters record every write the F5 rules would refuse. At each entry decision and each conversion read on a real row, `FeedShadowDecision` records what the F5 rules would have given: the second opinion kept or dropped, the conversion's source and age, and the size.
- **Tests first**
  - Winter and holiday clocks.
  - The `previousClose` fallback.
  - A re-stamped close.
  - Alpha Vantage's zero sides.
  - A stand-in refused as a second opinion.
  - Switch OFF: replay equals today. `tests/test_tier345_truth.py:66-105` stays as the OFF pin; new pins cover ON.
- **Money direction**
  - The second opinion is absent more often: fewer false suspensions (while F2a is still OFF) and fewer false entry refusals.
  - The conversion no longer finds a fossil presented as fresh. With no fresh quote it still falls back, as today, to a bar ≤ 6 h old (✓ `forex_bot.py:31-46`); with neither, sizing is refused (size 0) instead of sizing on yesterday's rate.
  - Alerts fire less often on fossils.
- **eToro requests:** none.
- **Switch:** `reference_truth_live` (PIN, OFF).
- **Turn-on evidence:** one week of the shadow's entry and conversion records, the refused entries explained.
- **Needs:** F1.
- **Acceptance on the server:** after ON, `feed_harms --days 7` shows zero `previousClose` writes, zero writes outside the session, and zero zero-or-crossed sides stored.

---

#### F6: The eToro feed, observe-only

- **Scope**
  - The service (§4.5).
  - The feed's stores and their compare-and-set (§5.2). The etbudget cache is read, never written, and its writer is not changed: it feeds `_mark_price` and the time stop's booking, so changing it here would change money inputs in an observe-only phase (moved to F9).
  - Grades and transitions (§5.4-5.9).
  - Feed wants, the REST watchdog and fallback, and the Celery takeover.
  - Health and the parity line.
  - `feed_status`, `feed_transitions`, `feed_shadow_report`.
  - Morgul G10v beside G10 (map `morgul.py:1518-1538`), as a WARNING only. It never applies the brake before F11.
  - **The shadow comparator.** It runs at every decision that reads an eToro price today. It reads the store only, takes ≤ 5 ms, never raises, and runs only while the component is ON. Its hook points:
    - `_mark_price` and `_confirm_mark` (`[BUD] base.py:3513`, `:3644`);
    - `propose_entry` (map `base.py:4722-4740`);
    - the last look (`:5392-5508`);
    - the ticket (`manual_trade.py:442-470`, `:2376-2378`);
    - CLOSE (`manual_close.py:555-573`);
    - the kill switch (`kill_switch.py:269-342`);
    - the drain (`pending_closes.py:564-613`);
    - the reconcile (`reconcile_asset.py:644-651`).
- **Files**
  - New: `market_data/management/commands/stream_etoro.py`, `feed_status.py`, `feed_transitions.py`; `market_data/feed_wants.py`; `bot_program/feed_shadow.py` (with `feed_shadow_report`); models `FeedTransition` and `FeedShadowDecision` (a market_data migration).
  - Edits:
    - `bot_program/morgul.py`: G10v;
    - `market_data/feeds.py`;
    - `config/celery.py`: `feed-wants` every 10 s, `venue-rest-fallback` every 10 s;
    - `deploy/docker-compose.yml`: the service;
    - `core/platform_control.py`: component `etoro_feed`;
    - `dashboard/live_health.py`.
- **Tests first**
  - `tests/feed/test_feed_service.py`:
    - wants and hysteresis;
    - the topic cap, applied by priority;
    - behind → resubscribe with a snapshot;
    - fallback on and off, and its pacing, with a fake clock and a session that records URLs (literal commas);
    - Retry-After;
    - a budget refusal reads as degraded;
    - the takeover lock;
    - the watchdog exit;
    - the memory guard;
    - no keys → idle.
  - T1-T24 on the feed and stores, end to end, against a fake server.
  - `tests/feed/test_feed_morgul_guard.py`: shut sessions, flapping, and a warning never brakes.
  - `tests/feed/test_feed_shadow.py`: replay equals today with the comparator in place.
  - `tests/feed/test_feed_leaves_money_inputs_alone.py`: with the feed running against a fake server, the engine's cache keys `etoro_rates:r:*`, LiveQuote and every money reader's inputs are byte-for-byte what they are with the feed absent; the feed's REST reads are P5 and never exceed 15 a minute or the floor (§4.5.6).
- **Money direction:** none. Nothing that decides reads the feed's stores, and the feed writes nothing that a decision reads: not the etbudget cache, not LiveQuote. Its REST reads are P5, refused before the engine's P3 marks.
- **eToro requests:** one WS connection; REST ≤ 15/min in all (P5 background), at the floor of §4.5.6 (one batched GET per max(C_rest, 30 s) until lowered).
- **Switch:** component `etoro_feed` (non-PIN), plus the compose profile `etoro-feed` (opt-in).
- **Needs:** F3, M1, M2, M6, etbudget merged.
- **Acceptance on the server**
  - `./deploy/dc --profile etoro-feed up -d stream-etoro`, then `./deploy/dc ps` shows it healthy.
  - `./deploy/dc exec web python manage.py feed_status` gives, per held instrument: grade, channel, confirmation age, print age, push gap p50/p99, skew, and parity verdicts.
  - `feed_transitions --hours 24`; `feed_shadow_report --days 5`; `docker stats --no-stream` (RSS under the limit).
  - **Done when, over 5 market days:**
    - the stream is connected for ≥ 99% of open-market time;
    - stream = REST on ≥ 99.9% of watchdog checks, with zero "older";
    - every PriceRateID seen on both channels carries the same Date on both (100%), so Dates may be compared across channels;
    - "behind" happens < 1 time per instrument per day;
    - there is no memory restart.

---

#### F7: Same grade on screen

- **Scope**
  - §4.6: the `venue_quotes` push, per-user marks, `sv-venue.js` and the pages.
  - §4.7.2-4.7.5: calibration, the live change, and `pnl_parity`.
  - Display readers of eToro instruments use `display_quote()`: `core/context_ui.py`, `core/context_processors.py`, `dashboard/horde.py`, `dashboard/chart_source.py` (quote_facts), the deal ticket and the signal rail.
  - `resolve`'s QUOTE branch is never used to display an eToro row. `resolve` itself is not changed here: valuation and the gates still read it until F9.
  - pnltruth's tier 2 becomes the store's closing side × eToro's conversion.
  - P&L cells follow §4.7.4's newest-by-time rule across tiers; badges degrade at once (§5.6).
  - etbudget's interim LiveQuote writer stays (P-c): money readers still need it until F11.
  - Held eToro instruments join the headband.
  - "Current" is shown in eToro's digits.
  - The chart's live candle is welded only after M5, and only on an eToro series.
- **Files**
  - New: `static/js/sv-venue.js`, `portfolio/pnl_venue.py`, the model `PnlParityRead` and `manage.py pnl_parity`.
  - Edits:
    - `templates/base.html`: `onmessage`, `applyTick`, the rail match, the paused chip, `add()`;
    - `dashboard/consumers.py`: `want`;
    - the `stream_etoro` publisher;
    - `static/js/sv-instrument-live.js`;
    - `templates/_partials/deal_ticket.html`;
    - the positions, portfolio and command templates;
    - `dashboard/views.py:1865`;
    - `core/context_ui.py`.
- **Tests first**
  - The payload contract.
  - ≤ 4 pushes a second per instrument, and a full batch every 5 s.
  - P&L travels only on the user's own eye group.
  - The main cell never takes an outside quote (T1, T10).
  - Labels and ages.
  - Newest wins after a region swap.
  - The rail match and the paused chip.
  - The formulas against hand-computed long and short cases, USD-quoted and non-USD.
  - Calibration reached and lost, per (world, pnlVersion, class).
  - T24: a P&L cell never steps back in time when tier 1 is lost.
  - A badge degrades in the same frame as the grade.
  - The conversion never comes from LiveQuote.
  - Fees are kept apart; totals are marked partial.
- **Money direction:** none.
- **eToro requests:** none new.
- **Switches:** components `venue_feed_display` and `venue_pnl_delta_display`, both ON. Turning them OFF returns today's display, or eToro's own figure only.
- **Needs:** F6, M3 (the formula), M5 (only for the chart weld).
- **Acceptance on the server**
  - /health/ shows latency p50 ≤ 0.5 s and p99 ≤ 1.5 s (raw, NTP-synced host), or says by how much it misses and which leg (eToro → server is outside Sauron's control).
  - `pnl_parity --hours 24` shows ≥ 99% "to the cent" per class, with the formula named.
  - Side by side with eToro's app on a held pair: the same bid/ask and the same P&L, or the difference written down (U2).
  - Fault test:
    - `./deploy/dc stop stream-etoro`: each eToro cell turns degraded at once with a growing age, REST carries at the floor's pace, P&L cells hold their last live value greyed until a newer eToro figure arrives, and no cell jumps or steps back. ("Live prices paused" is the browser's own socket to Sauron: it shows when that socket drops, not when the eToro feed does.)
    - `./deploy/dc --profile etoro-feed up -d stream-etoro` brings it back to live after the trust rule (§5.6).

---

#### F8: Exits booked at eToro's executed price

- **Scope, switch `venue_exit_booking_live`**
  - Every close Sauron sends keeps the close answer's `orderForClose.orderID` on the row (today only the demo short proofs store it, ✓ `short_proofs.py:1006`; the client already returns it as `orderId`). Additive, recorded whether the switch is ON or OFF.
  - Every eToro exit path (bot close, care, CLOSE, kill switch, drain, reconcile orphan) books from eToro's own figures, in this order:
    1. the close-order read [E29] for Sauron's own closes, if M4 proves it (its quota is the 60/60 s lookups pool, etbudget's "lookups" family);
    2. trade history, for positions eToro or the operator closed, if M4 proves it (eToro's default 60/60 s pool; etbudget must name a family for it, since an unclassified request counts at P1, ✓ `[BUD] etoro_budget.py:19-22`);
    3. otherwise **pending**: retries at P1 for 2 minutes, then hourly at P5 for 3 days, then "unpriced" as today.

    The provisional value (F2b's rule) serves the daily-loss gate only.
  - `venue_exit.estimate` becomes a provisional value only (map `venue_exit.py:405-459`).
  - `for_booking` never answers with an outside quote for an eToro row.
  - Reconcile stops booking another source's quote (map `reconcile_asset.py:657-692`) and bars of any source (map `venue_exit.py:362-386`).
- **Shadow while OFF:** after each close the lookups run and record eToro's executed price beside the booked mark (the Δ per exit).
- **Files**
  - `bot_program/engine/etoro_client.py`: `closing_fill`, `trade_history` (read-only lookups)
  - `bot_program/pending_closes.py:365-525`
  - `bot_program/reconcile_asset.py:595-740`
  - `bot_program/venue_exit.py`
  - `bot_program/venue_mark.py`
  - `bot_program/engine/kill_switch.py`
  - `bot_program/manual_close.py`
  - `config/celery.py`: `price-pending-exits`
- **Tests first**
  - Each exit path.
  - Pending → backfill.
  - The gate is never loosened.
  - A lookup 404 → pending, never the mark.
  - A target crossed by the mid but not the bid, then the stop filled → booked at eToro's own price.
  - OFF replay equals today.
- **Money direction**
  - Realized P&L, R, grading and the daily stop see eToro's numbers instead of a mark about half a spread kinder.
  - The daily stop can trip sooner, on the truth.
- **eToro requests:** +1 lookup per close (P1, then P5 retries); history ≤ 1 per 5 min (P5), only while an exit is pending.
- **Switch:** `venue_exit_booking_live` (PIN, OFF).
- **Needs:** F1, F2b, M4. The ring source needs F6; without it, the provisional figure falls back to the last print, then −1R.
- **Turn-on evidence**
  - ≥ 20 exits with eToro's figure read in shadow.
  - The Δ distribution explained.
  - No lookup failing permanently.
- **Acceptance on the server:** `feed_shadow_report --exits --days 14`. After ON, every eToro exit in the last 24 h shows its source as "venue" or "pending", never "mark".

---

#### F9: Marks, stops and care on eToro's closing side, every 15 s

- **Scope, switch `venue_marks_live`**
  - §7 (the 15 s manage loop).
  - `_mark_price` returns `money_price(CLOSING)` when LIVE; otherwise today's path (the wire read, on its closing side).
  - `_confirm_mark` may veto only with a **newer** eToro answer (a later Date):
    - an older or cached REST answer cannot veto;
    - a failed confirmation read never blocks a protective close; for care moves, it holds.
  - `resolve` for real eToro rows uses the store, then the stamps. Never an outside quote (✓ today's QUOTE branch, `venue_mark.py:419-424`).
  - The loop writes `venue_mark` stamps from the store, so the 900 s handoff to LiveQuote never happens on an eToro row.
  - The level editor and the position review follow §5.8: a LIVE eToro price, a P0 wire read, or the at-the-close rule. The editor never refuses a stop move for want of a price.
  - The etbudget prefetch skips LIVE instruments.
  - The "look again" rule for outside quotes (§5.7).
  - **Never a hold where today acts (I13).** When an instrument is not LIVE, every row, protected or not, takes today's wire read at today's cadence and priority (P3 for protected rows, P1 for the others, ≤ 1 per 30 s) and is managed on its closing side, as today manages it on lastPrice. Only a failed read holds, as today.
  - **The loop has a dead-man.** The 300 s tick skips manage only while the loop's last completed pass is < 60 s old. If the loop stalls (beat lost, worker down), the next tick manages every row exactly as today and one staff alarm says so.
  - **The REST stores merge.** From here, the engine's cache and the feed's REST store are one compare-and-set store (§5.2), "no erasing" included, and the feed's held-instrument reads move to P3, replacing the engine's own mark reads for LIVE instruments.
- **Files**
  - `bot_program/asset_engine/base.py`: the manage path, `_mark_price`, `_confirm_mark`
  - `bot_program/position_care.py`: PATCH caps
  - `bot_program/venue_mark.py:384-432`
  - `bot_program/adjust_levels.py`
  - `brain/position_review.py`
  - `bot_program/engine/etoro_rates.py`: prefetch; the compare-and-set writer (moved here from F6), active only while the switch is ON
  - `bot_program/tasks.py` and `config/celery.py`: `manage-asset-positions` every 15 s; the tick skips manage while the switch is ON and the loop's dead-man is fresh
- **Shadow while OFF:** for each row and tick, both prices and both decisions go into `FeedShadowDecision`.
- **Tests first**
  - A long's stop decided on the bid, a short's on the ask.
  - A target touched by the mid but not the bid → no action.
  - An unconfirmed jump → confirm, then act by the protection rule.
  - An older REST answer cannot veto.
  - A failed confirmation read does not block.
  - P1 rows keep their wire reads when not LIVE; protected rows keep today's wire read and care when not LIVE (never a hold where today acts).
  - PATCH caps, ≥ 3 s apart.
  - The loop lock: no double close.
  - The dead-man: a stalled loop hands manage back to the 300 s tick within one tick.
  - The merged store keeps today's reader semantics: a "0" never makes a priced record look fresh.
  - T1-T24 on M1, M2, M9, M10 and M11.
  - Pins that change when ON: `tests/test_venue_mark_birth.py:221-238` and `:749-757` (map) become "never an outside quote for a real eToro row".
- **Money direction**
  - Decisions are made on eToro's closing side: a long's stop about half a spread sooner, a target half a spread later, as eToro's own would.
  - Every 15 s, on prices ≤ about 1 s old, instead of every 300 s on lastPrice.
  - Care moves: up to 5 per row in 5 min, instead of 1.
- **eToro requests**
  - Market marks for LIVE instruments → 0.
  - P1 rows: ≤ 1 wire read per 30 s when not LIVE.
  - P0 confirmations: ≤ 2 per suspect jump.
  - PATCH: ≤ 1 per row per 60 s, ≤ 6/min overall, ≥ 3 s apart (eToro's default pool; etbudget's execution family).
- **Switch:** `venue_marks_live` (PIN, OFF).
- **Needs:** F6 with ≥ 10 trading days of shadow; F2a ON.
- **Turn-on evidence**
  - ≥ 1,000 compared marks.
  - Zero cases of a LIVE store price disagreeing with a newer wire answer by more than one tick.
  - Zero would-be actions on a non-LIVE price.
  - "Behind" < 1 per instrument per day.
- **Acceptance on the server**
  - `feed_status --loop`: manage-loop run time p50/p95 and PATCH count a minute.
  - `feed_shadow_report --marks --days 10`.

---

#### F10: Entries, ticket and conversion on eToro's executable side

**Two pull requests, one switch each (§9.14): F10a (`venue_entries_live`) and F10b (`venue_conversion_live`).** Shadow while OFF: for each entry and each conversion read on an eToro row, `FeedShadowDecision` records both prices, both conversions, both sizes and both admit/refuse verdicts.

- **F10a scope, switch `venue_entries_live`**
  - Proposals, sizing, the entry gate and the ticket use the ask for a BUY and the bid for a SELL, from LIVE, fresh quotes (§5.8).
  - The last look keeps its P1 wire read: a newer eToro answer wins, and a failed read refuses the entry.
  - The ticket preview equals the button price.
  - "Price moved: preview again" once the move passes 0.25 R or the slippage budget.
  - `mark_delayed` is shown.
  - Suggested levels for eToro instruments are anchored on eToro's price (map `signals/fast_rules.py:373-377`).
- **F10b scope, switch `venue_conversion_live`**
  - `quote_ccy_usd_rate` (✓ `forex_bot.py:31-46`) and its Orcs copy (map `orcs/grading.py:136-165`) use eToro's conversion for eToro rows:
    - the conservative side for sizing and the cash gate's need;
    - the calibrated side for P&L.
- **Tests first**
  - Sizing on the executable side.
  - Refusals in RECENT, STALE, CLOSED and during the settle period.
  - The band, with qualifying outside quotes only.
  - No outside quote ever sizes an entry.
  - Risk at the executable side never exceeds the configured risk.
  - T1-T24 on M3, M4 and M12.
- **Money direction**
  - Sizes are computed on the side that fills, so they are slightly smaller when spreads are wide.
  - More refusals on degraded data.
  - The conversion comes from eToro instead of any feed.
- **eToro requests:** proposals make 0 market reads while LIVE (today about 4/min at P4); the last look is unchanged.
- **Switches:** `venue_entries_live` (F10a), `venue_conversion_live` (F10b) (PIN, OFF).
- **Needs:** F9 ON.
- **Turn-on evidence:** F10a: ≥ 20 shadow entries; zero sizes on a non-LIVE price; preview = button price in the shadow log. F10b: ≥ 20 shadow conversions, each within the conservative side of eToro's own `conversionRateBid/Ask`, and the size differences explained.

---

#### F11: One series for every remaining reader

Each item has its own switch and its own pull request (§9.14), with its shadow while OFF (both versions recorded):

| Item | Switch |
|---|---|
| Price alerts on eToro instruments fire on LIVE eToro prices only (map `alerts/models.py:493-540`) | component `alerts_venue_prices`, ON |
| Posture: eToro's index CFD daily candles plus eToro's live value; never a cash index spliced in (map `market_stress.py:101-119`) | `posture_venue_series_live` (PIN) |
| Rules for eToro-routed bots read eToro bars only, and a stale window is a gap (map `signals/smc/dataframe.py:39-45`, `bot_bars.py:852-889`) | `venue_bars_live` (PIN) |
| The Orcs' census, news-shock corroboration and wakes read the store; a gap is never a shock (map `drum_bus.py:174-180`, `:383-413`; `wake.py:245-264`) | `orcs_venue_prices` (in `ORC_MIND_SWITCHES`, PIN) |
| Paper rows of eToro instruments price from the store. Each row carries a source epoch, so promotion evidence never mixes sources (map `paper_trader.py:177-331`) | `paper_venue_prices_live` (PIN) |
| Book value: eToro rows from `/pnl` in `live_book_value` (map `services.py:866-1007`). The NL trader and legacy repricing refuse non-eToro prices for eToro instruments (map `nl_trader.py:174-212`, `views_command.py:155-156`, `portfolio/tasks.py:16-69`) | `venue_book_value_live` (PIN) |
| Morgul: G10 judges each instrument by its authority's store. G10v becomes the G10 for eToro instruments, with a severity set from the F6-F10 evidence (only from here can it apply the brake). G4 compares against eToro bars | `morgul_venue_guard_live` (PIN) |

Further changes come with F11:
- Yahoo polling of eToro instruments goes back to 600 s, as an outside quote only.
- The compose profile `etoro-feed` joins the default set after a clean week.
- **The last F11 pull request retires etbudget's interim LiveQuote writer (P-c)** and, in the same change, makes `write_quote` refuse `etoro*` sources (I2). It ships only once F2a, F9, F10b and every F11 switch above are ON with a clean week, because until then the interim writer is what keeps those readers on eToro's price for held instruments (harm 29). Its replay (T21) shows no reader of a held eToro instrument falling back to an outside quote.

- **Tests:** one module per switch, plus T7, T10 and T17 for each, and A14.
- **Money direction, per switch**
  - Posture can no longer see a false drawdown from a spliced series.
  - Paper evidence fills at eToro's prices.
  - Fewer false Orc wakes, so less AI spend.
  - Some rule signals change.
- **eToro requests:** none. If M1 proves v2, there is ≤ 1/min of REST v2 for watched breadth beyond the topic cap (P5).
- **Needs:** F9 ON.
- **Turn-on evidence:** a week of both versions' findings, alerts, samples and signals, per switch.

---

#### F12: Private stream as a hint

- **Scope, switch `private_stream_hints_live`:** `private:real` joins the feed's connection, and never `private` as well: a session holding both receives each real-account update once under each (S-a). Order and close updates trigger the existing P1 confirmation reads at once. A hint is never the only source of a booking, and duplicates are dropped by message id.
- **Tests:** fake private frames, including a failed update (ErrorCode ≠ 0); a missing or duplicate hint changes nothing.
- **Money direction:** confirmations and bookings come sooner.
- **eToro requests:** the same reads, earlier.
- **Needs:** M2 `--private-demo`; F8.
- **Turn-on evidence:** ≥ 10 demo closes where the hint arrived before the REST confirmation and matched it.

---

#### F13 (optional): The feed wakes the manage code for one row

- **Scope, switch `venue_wake_live`**
  - When the feed sees eToro's closing side cross a bot-side level of a row eToro holds no stop for, or reach a care threshold, it sends a wake for that row, by task name. It imports no order path.
  - The manage code then runs that one row under its lock and decides exactly as the 15 s loop would: the same `money_price`, the same jump rule.
  - At most one wake per row every 2 s for levels, and every 60 s for care.
  - The feed never decides and never sends anything to eToro.
- **Money direction:** bot-side levels and care act within about 1-2 s of eToro's price, instead of ≤ 15 s.
- **eToro requests:** none new.
- **Needs:** F9 ON for ≥ 10 trading days.
- **Turn-on evidence:** in the wake shadow, 95% of would-be actions within 2 s; zero actions on a non-LIVE price; no double close.

### 6.3 Order, dependencies and turn-on

**Dependencies**

| Phase | Starts after |
|---|---|
| F1 | nothing; it comes first |
| F2a, F2b, F3, F5 | F1 (these four can be built in parallel; one pull request each) |
| F4 | F3 (for M3a) and P-b merged |
| F6 | F3, M1 (after P-a), M2, M6, etbudget merged |
| F7 | F6, M3 (M5 only for the chart weld) |
| F8 | F2b and M4; better after F6, for the ring |
| F9 | F6 with ≥ 10 trading days of shadow, and F2a ON |
| F10a, F10b, F11 (one pull request per switch) | F9 ON |
| F11's last pull request (retire the interim writer) | F2a, F9, F10b and every F11 switch ON with a clean week |
| F12 | F8 and M2 `--private-demo` |
| F13 | F9 ON for ≥ 10 trading days |

F2a and F2b are the first PIN switches to turn ON, one at a time.

| Switch | Kind | On arrival | Turned ON when | OFF |
|---|---|---|---|---|
| `protective_unblock_live` (F2a) | PIN money | OFF | ≥ 7 days of shadow; every "unreadable → act" case read; tests green | any time, no PIN |
| `close_without_price_live` (F2b) | PIN money | OFF | ≥ 7 days of F1 counters; T23 green | any time, no PIN |
| `etoro_pnl_display` | component | ON | — | `manage.py component off` |
| `reference_truth_live` | PIN money | OFF | one week of counters and shadow | any time |
| `etoro_feed` + profile `etoro-feed` | component + profile | component ON, profile opt-in | M1, M2, M6 done | `./deploy/dc stop stream-etoro` |
| `venue_feed_display`, `venue_pnl_delta_display` | components | ON | — | `component off` |
| `venue_exit_booking_live` | PIN money | OFF | ≥ 20 shadow exits explained | any time |
| `venue_marks_live` | PIN money | OFF | ≥ 10 trading days, ≥ 1,000 marks, zero non-LIVE actions | any time |
| `venue_entries_live` (F10a), `venue_conversion_live` (F10b) | PIN money, one each | OFF | ≥ 20 shadow entries (F10a); ≥ 20 shadow conversions (F10b) | any time |
| `posture_venue_series_live`, `venue_bars_live`, `paper_venue_prices_live`, `venue_book_value_live`, `morgul_venue_guard_live` | PIN money, one pull request each | OFF | one week of both versions | any time |
| `orcs_venue_prices` | PIN Orc mind | OFF | one week of both versions | any time |
| `alerts_venue_prices` | component | ON | — | `component off` |
| `private_stream_hints_live` | PIN money | OFF | ≥ 10 demo closes matched | any time |
| `venue_wake_live` | PIN money | OFF | wake shadow 95% ≤ 2 s | any time |

- Every new `*_live` key is added to `LIVE_MONEY_SWITCHES` (✓ the cockpit test requires it), seeded OFF and excluded from "all on". The Wall's count of money switches rises accordingly.
- The display components are not money switches: they change words and cells only.

### 6.4 eToro requests by phase (per key pair, per rolling minute)

| Phase | Market | Account | Execution | Lookups | WebSocket |
|---|---|---|---|---|---|
| F1 | 0 | 0 | 0 | 0 | 0 |
| F2a, F2b | +≤ 2 P0 per suspect jump; +1 P0 per manual close that had no mark | 0 | closes as pressed; ≤ 3 resends per 429'd close | 0 | 0 |
| F3 | probes only (≤ 30 per run, P5) | probes only | 0 | probes only | 1 while a probe runs |
| F4 | 0 | ≤ 6 real (every 11 s) + ≤ 2 demo (P5), +1 per fill or close | 0 | 0 | 0 |
| F5 | 0 | 0 | 0 | 0 | 0 |
| F6 | the feed's REST ≤ 15 in all (P5), one batched GET per floor period (§4.5.6) | 0 | 0 | 0 | 1 connection; subscribe batches ≤ 1/s |
| F7 | 0 new | 0 new | 0 | 0 | 0 new |
| F8 | 0 | 0 | 0 | +1 per close (P1); history ≤ 1 per 5 min while pending (P5) | 0 |
| F9 | marks of LIVE instruments → 0 (the feed's held reads move to P3); rows not LIVE keep today's reads (P1 rows ≤ 2 each); P0 ≤ 2 per jump | 0 | 0 (PATCH is on the default pool: ≤ 1 per row per 60 s, ≤ 6 overall, ≥ 3 s apart) | 0 | 0 |
| F10 | proposals → 0 while LIVE | 0 | 0 | 0 | 0 |
| F11 | ≤ 1 v2 breadth (P5), if M1 proves v2 | 0 | 0 | 0 | 0 |
| F12 | 0 | 0 | 0 | the same lookups, earlier | the private topic on the same connection |
| F13 | P0 only for unconfirmed jumps | 0 | within F9's caps | 0 | 0 |

---

## 7. The bots' tick

**Today** (✓ `config/celery.py:470-472`):
- One 300 s pass reads one REST rate per held row (P1 or P3 on etbudget). It runs mark sanity, care, bot-side SL/TP, time stops and proposals.
- The drain runs every 300 s and the reconcile every 5 min.

**With F9 (`venue_marks_live`)**

1. **Manage loop `manage-asset-positions`, every 15 s.** It holds a run lock and never stacks; if its p95 run time exceeds 5 s, it moves to 30 s. For each row:
   1. the vanished-stop net and the time stop run first (F2a);
   2. it takes the closing side from `money_price` when LIVE;
   3. otherwise today's wire read applies to every row, at today's cadence and priority: P1 rows at most once per 30 s, protected rows as today's tick reads them (P3). Care and trailing then act on that read's closing side, as today they act on lastPrice. Only a failed read holds, as today (I13);
   4. then care, trailing and bot-side SL/TP.

   While LIVE it costs 0 market reads.
2. **`tick-asset-bots` stays at 300 s, for proposals only.**
   - It skips manage while the loop is on and the loop's last completed pass is < 60 s old. Otherwise it manages every row as today and one staff alarm says so (the dead-man).
   - The bars that proposals read refresh every 600 s (✓ `config/celery.py:457-462`), so proposing faster would re-read the same bars.
   - From F10, proposals read the store's executable side when LIVE. The last look keeps its P1 wire read.
3. **eToro stop moves (PATCH)**
   - At most one per row per 60 s, and only for at least the minimum step (0.25 R, or care's own minimum if larger).
   - At most 6 a minute across the fleet, ≥ 3 s apart. Per the spec copies the PATCH sits on eToro's default 60/60 s pool, not on the 20/60 s execution pool of orders, closes and cancels [E16]; etbudget counts it as execution anyway, the stricter way. P0 is never refused by the budget, so the loop must limit itself.
4. **Reconcile (5 min) and drain (300 s) keep their cadence.** F8 changes what they book; F12 makes them act sooner on a hint.
5. **F13 (optional)** adds per-row wakes.
6. **Workers.** `worker-fast` stays at `-c 3` (map compose) unless M6 shows ≥ 300 MB free, in which case `-c 4`. The loop runs on `default`.

| | Today | F9 | F13 |
|---|---|---|---|
| Bot-side SL/TP on rows eToro holds no stop for | ≤ 300 s, on lastPrice | ≤ 15 s, on the closing side | about 1-2 s |
| Care (break-even, trail, soft stop, posture cut) | ≤ 300 s | ≤ 15 s; PATCH ≤ 1 per row per 60 s | about 1-2 s to see it; the same PATCH caps |
| Market REST for marks | 1 per held row per tick (plus etbudget's interim beat: held real instruments every 30 s, for LiveQuote) | 0 while LIVE (the interim beat runs until the end of F11) | 0 |
| Proposals | 300 s | 300 s (from the store when LIVE, F10) | 300 s |
| eToro-held stops | at eToro, instant | unchanged: never cancelled, loosened or delayed by any price state | unchanged |

---

## 8. Risks and unknowns

| # | Unknown or risk | Settled by | Why the design holds either way |
|---|---|---|---|
| U1 | Whether the stream works with his key: demo-key login, Cloudflare and the User-Agent [E34], caps [E9] | M2 | The REST-only path uses the same stores, arbiter and pages. "Same grade" is then not reached: prices refresh at the REST floor (§4.5.6: 30 s until lowered, a few seconds at best), and the ages show it |
| U2 | Whether the stream equals eToro's app and valuation price | M2 visual check; F6 parity; F7 closeRate check | If not, the stream is labelled, P&L shows eToro's own figure, and money stays on REST |
| U3 | Date format and meaning; whether PriceRateID only increases and is shared [E5] | M2 | Order by Date only until proven |
| U4 | Price-less and one-sided frames [E6-E7] | M2 | Liveness only; merge only once proven |
| U5 | Behaviour at the close; whether `IsMarketOpen` is reliable [E6, E27] | M2 Friday, Sunday and break runs | Clock plus eToro's flag, with the asymmetric rule |
| U6 | REST server cache [E30] | M1 | C_rest = 60 s until measured, so REST alone is never LIVE; an older REST answer can never veto |
| U7 | Batch encoding and id limit [E12-E13] | P-a, M1 | Single-id round-robin inside the same caps |
| U8 | Whether WS operations count against the REST quota; 60 vs 120 a minute; header names [E15, E17] | M1, M2 | Pacing from the measured `RateLimit-Policy`; conservative defaults; the etbudget priorities arbitrate |
| U9 | P&L formula, sides, pnlVersion, and whether fees are in the app's P/L [E19, E25] | M3 plus running calibration | eToro's own figure until calibrated; anchor plus change carries constants through |
| U10 | `netProfit` on `/portfolio` (pnltruth tier 1) [E20] | M3 | `/pnl` becomes tier 1 |
| U11 | The executed close price: lookup, history or private stream [E29, E11], against the 2026-09-23 finding ✓ | M4, M2 | Pending plus backfill; never a mark or an outside quote |
| U12 | Private stream shapes and latency [E10-E11] | M2 | A hint only (F12) |
| U13 | What eToro's candle close is | M5 | No weld and no candle-stamp side until measured |
| U14 | Memory on a 4 GB host | M6 | mem_limit, oom_score_adj and a self-exit; streamers can be dropped |
| U15 | Clock skew | M6 plus the running skew check | Print ages are skew-corrected; confirmation ages use Sauron's clock |
| U16 | The daily-loss gate with pending exits (✓ unpriced exits are skipped today) | F2b, U28 | The provisional rule is never positive; eToro's own `/pnl` figure comes first; a row with no figure, ring, print or stop stays "unmeasured", and the gate says so |
| U17 | Rows eToro holds no stop for (P1) | separate task: re-arm venue stops | They keep their wire reads, and their protection never depends on the feed |
| U18 | Watched instruments with no known eToro id | — | They show outside quotes labelled "no eToro id". The feed never calls /search; ids are learned through the engine's normal paths |
| U19 | Channels drops messages silently (100 per channel) | — | A full batch every 5 s; newest wins in the browser; the 60 s sweep stays |
| U20 | A bug writing the wrong instrument's price | — | Verified ids only; W1; the stream-vs-REST parity; money switches stay OFF until the shadow is clean |
| U21 | eToro's terms on request rates [E31] | — | One connection, batched REST, measured pacing, the stream preferred |
| U22 | Extended-hours stock prices at eToro | M2 on a US evening | Money follows the session rule; the screen says "after hours" |
| U23 | The feed as a single point of failure | — | The Celery takeover plus the engine's own reads: never worse than today |
| U24 | No streamer running on a 4 GB host means entries have no second opinion | M6 | The jump rule and the last look remain; the operator decides which streamers run |
| U25 | etbudget's uncommitted interim writes eToro into LiveQuote (harm 29); it may change before it lands | P-c; re-read etbudget before F1 starts | No phase depends on it; replays take today as it is; it retires only at the end of F11 |
| U26 | eToro's own skill gives 30-60 s for polling a live price; the terms ask for respect of polling intervals [E30, E31] | M1, M2 (C_rest); one generic question to eToro API support | The feed's REST floor is max(C_rest, 30 s) until lowered on that evidence; the stream is the fast path, as eToro advises |
| U27 | Forex hours and the daily break move with daylight saving and the sources conflict [E26] | M2 now (winter) and again after the March change | Break taken from New York 17:00; unmeasured windows refuse entries only, raise no alarm, and never touch protection |
| U28 | A pending exit with no eToro figure, no ring, no print and no stop stays unmeasured, and today's gate then fails open (✓ `risk_gate.py:782-788`) | F4 makes it rare (a `/pnl` figure ≤ 11 s old for every real eToro position) | From F8 ON, new real entries on that venue wait up to 1 hour for eToro's figure; then today's words and one staff warning |
| U29 | The WS `TooManyRequests` and topic caps are unpublished; probing them uses the operator's one key pair, which also trades | M2's `--batch` steps 60 s apart, stopping at the first refusal, with a REST control read after each | The probe runs on the demo world's topics only; a refusal stops it; nothing trades through the socket |

---

## 9. Not doing

1. **No new eToro writer into LiveQuote, under any rank** (I2, harm 29). The feed never writes it. etbudget's interim writer, the one exception, is retired at the end of F11 and never extended.
2. **No outside quote for money.** No outside quote, including a "close enough" OANDA mid, may value a real eToro row, size an entry, trigger or delay a stop, book an exit, raise an alarm or feed a series.
3. **No mid or last execution against a level.** None is compared with a stop or target, and no P&L is built from one. No rate is rebuilt from P&L fields [E23].
4. **No REST polling at 1 Hz or faster for "same grade"**, and none below the floor of §4.5.6 (max(C_rest, 30 s) until lowered on evidence). It breaks the published quotas and the etbudget caps, eToro says to stream [E31], eToro's own skill gives 30-60 s for a live price, and REST may be cached anyway [E30].
5. **No redirect-following WebSocket clients.** No `websockets.connect`, aiohttp `ws_connect`, websocket-client or curl_cffi for the stream: they follow redirects and are pinned offences ✓. The keys never go in a header.
6. **No browser User-Agent.** Never imitate a browser to get past eToro's edge.
7. **No community-client habits** [E32]: trusting "any instrument ticking" as liveness, resubscribing without a snapshot, giving up on reconnect.
8. **No unproven messages.** Do not build on the Builders tutorials' wire formats [E35], or on illustrative or template messages [E10], before they are observed. A v2 `delayed` quote is used for labelled display only [E14].
9. **No P&L in the browser, and none on `dashboard_live`.** The first would mean two formulas; the second would reach every socket.
10. **No /search from the feed.** The feed never imports an order path, never acts, and never runs inside daphne or a Celery worker.
11. **No faster 300 s tick while it still reads the wire for every row.** Proposals stay at 300 s.
12. **No retrying a trade after a timeout or 5xx** [E18]. Nothing here touches that rule.
13. **No mixed series.** Paper promotion evidence, the posture series and the Orcs census never mix sources without an epoch boundary.
14. **No money switch without its shadow report and the operator's PIN.** That includes the protective ones. No two money switches in one pull request: F2, F10 and F11 ship as one pull request per switch.
15. **No real-account probes.** Never probe a real-account endpoint, and never subscribe to `private:real`, before `private:demo` has been recorded.
16. **No merging into the in-flight pull requests**, beyond the asks in §6.0 (P-a 1-3, P-b, P-c).
17. **No observe-only phase touches a money input.** F6 and F7 write neither the etbudget cache nor LiveQuote, and their REST reads are P5 (I14).
18. **No close sent from a message.** Alarms link to the CLOSE button; they never carry a close.

---

## 10. Verification

*Adversarial pass, 2026-11-06. Read-only: no eToro, broker or model call, no credentials, nothing written into a git worktree. eToro sources were re-opened over the web (WebFetch, or curl piped into grep with nothing saved). Sauron's code was re-read at file:line in `mainread` (main `d81a035`), `etbudget` (HEAD `93fa656`, the same tree as `3cff385`, plus its uncommitted files) and `pnltruth` (`a08c87b`). One offline computation: requests 2.34.2 preparing a URL. Unreachable from this session: api-portal.etoro.com, help.etoro.com and www.etoro.com (DNS), github.com org pages (404) and the GitHub org API (session-bound).*

### 10.1 eToro claims, re-read

| Source | What was checked | Result |
|---|---|---|
| S-a (go-etoro v0.6.2, `ws/etorows.gen.go`) | "Source: etoro WebSocket API v1.413.0"; the URL; the envelope; `AuthenticateData{userKey, apiKey}`; the error-code list; `snapshot` default false; topic names; "Required before subscribing to `instrument:{instrumentId}`"; rate fields as strings, every field optional; obsolete USD fields; illustrative MarketStatus and Position.Opened; template text in Candle and Position.Closed; private topics; no heartbeat, idle or cap text | All as quoted. New: every rate field is optional; a session holding both `private` and `private:real` gets each update twice. Confidence lowered to likely: a third-party copy of the spec, not an official page |
| S-b (go-etoro `client.gen.go`) | v1 rates' shared quota | 120/60 s with 10 other endpoints: 11 ✓. v2 "max 1000" ✓. The Go copy cannot express maxItems, so its silence on v1's cap is no evidence |
| S-c (v1.408 JSON copy) | v1/v2 parameters, schemas, status codes, headers, quotas | v1 `maxItems: 100` ✓; v2 bid, ask **and date** nullable ✓; 206/404/401/422 ✓; RateLimit-* on 200 and 429, Retry-After on 429, no 429 body ✓; pnl/portfolio/breakdown 60 (demo apart) ✓; execution 20 per mode ✓. New: the close-order read's own 60/60 s pool; trade history and **`PATCH /api/v2/trading/positions/{id}` on the default pool**; open positions have `unrealizedPnL{pnL, pnlAssetCurrency, closeRate, closeConversionRate, timestamp, …}` and no `netProfit` ✓; the close POST's "a 200 means submitted… use the orderID returned under orderForClose" ✓; `fxValueImpact` worded differently for real and demo |
| S-d (eToro-Public rules) | comma rule; execution limit, 3 s spacing, 15/30/60 backoff; only 429 safe; P/L formula in USD; ~10 s cache; "Don't synthesize"; fees = actual fees − dividends | All ✓ word for word. The plugin calls itself "Official eToro plugin", author eToro, apisupport@etoro.com; the org's ownership could not be checked here |
| S-e (eToro agent skills) | 10 s rolling cache, no force-refresh; "not subject to this cache", "sub-second price-threshold triggers"; pending orders at a closed market; wait 10 s; only 429 safe | All ✓. New and material: conditional-rules gives **30-60 s** for polling a live price and 10-30 s for P&L |
| S-f (etoro-tui probe) | date; Snapshot fields; price-only and price-less deltas; BTC cadence; text-only frames; `\x00` keepalives; Cloudflare | All ✓ (2026-06-29). Its REST notes tie the 403 to another base path (`…/api/public`) |
| S-g (etoropy 0.1.7, the archive already in this folder) | price-less skip; 30 s/10 s; one reconnect per close event | ✓ (the PyPI page itself would not render) |
| S-h (shayhe-tr/etoro-sdk) | backoff 1 s × 2^n; 10 attempts; resubscribe without snapshot; README rows | ✓, but the "Filling/Executed" and "comma list returns 500" rows are in the master README only; the main README says 100 requests a minute |
| S-k (florinel-chis/etoro-mcp) | encoded commas ignored; browser-style User-Agent | ✓ |
| S-i, S-j, S-l, S-m | help centre, portal, builders pages, terms | Unreachable. A new search shows the forex-hours sources conflict (E26 now unverified) |

### 10.2 Sauron claims, re-read

- **Every ✓ claim of §2.2 holds at its cited lines**, with these precisions: `quotes.py:28-47` also ranks alpaca, oanda and binance at 70 and twelve_data and fmp at 30 (immaterial); `venue_mark.py:133` is `SPREAD_CARRY_MAX_S` (6 h), a closing-side threshold rather than a `resolve` age bound; the bars refresh every 600 s (`config/celery.py:457-462`, a "(map)" claim, now ✓).
- **"(map)" claims spot-checked and holding:** LiveQuote's `updated_at` is write time (`models.py:39`); the quote socket's `alive` flag is set on open and close and never read (`base.html:4052`, `:4627`, `:4638`); the dead `subscribe` handler (`consumers.py:71-81`); price alerts fire on LiveQuote's `last` with an age bound and only notify (no order path, `alerts/models.py:493-540`); `quote_facts` is display-only (two views); Fernet keys; market data carries no world; the O2a order-path pin covers `bot_program.engine`; the venue-exit crossing logic.
- **Found in code, not in the spec as first written:**
  1. etbudget's uncommitted `bot_program/etoro_quotes.py` writes eToro into LiveQuote every 30 s (rank 70); the same uncommitted celery file sets the sync to 60 s and forex to 300 s (§2.2, harm 29, P-c).
  2. etbudget's rates cache is a money input: `_mark_price` (≤ 30 s) and the time stop's booking read it; every client rates read writes it, `rates_raw` does not.
  3. A "0" answer is a sentinel every money reader skips.
  4. A close POST that meets a 429 raises and waits for the 300 s drain.
  5. The close answer's `orderForClose.orderID` is returned as `orderId`; only the demo short proofs store it on a row.
  6. The daily-loss gate fails open when every close in the window is unpriced (`risk_gate.py:782-788`).
  7. Sauron's REST session sends requests' default User-Agent and works.
  8. websockets' sans-I/O `ClientProtocol` adds no User-Agent.
  9. Stop moves are `PATCH /api/v2/trading/positions/{id}`.
  10. requests 2.34.2 prepares `params={"instrumentIds": "1,2,3"}` as `1%2C2%2C3` and keeps a pre-built `?instrumentIds=1,2,3` ✓ (re-run offline).

### 10.3 Money-safety findings and what changed

1. **F6 was not observe-only.** Its watchdog and fallback wrote the engine's rates cache, which `_mark_price` and the time stop's booking read, and it changed that cache's writer (compare-and-set, "no erasing") with no switch. Its REST at P3 could also crowd out the engine's own P3 marks. **Fix:** the feed has its own REST store `vq:rest:*`, reads the engine's cache read-only, runs at P5 within 15 GETs a minute, and the cache's compare-and-set moves to F9 behind `venue_marks_live`. P-a item 4 is withdrawn. A test pins that money inputs are byte-for-byte unchanged with the feed running (§4.5.6, §5.2, F6, F9, §9.17).
2. **Three phases bundled money switches**, against §9.14: F2 (two), F10 (two), F11 (six). **Fix:** F2a/F2b, F10a/F10b, F11 one pull request per switch, each with its shadow while OFF.
3. **F2 and F5 had no shadow while OFF** (I14). **Fix:** both now say what they record.
4. **"Never worse than today" broke with F9 ON and the stream down.** Protected rows held care and trailing where today's tick acts on a wire read. **Fix:** every row keeps today's wire read and care when not LIVE (§5.8, §7, F9). A dead-man also hands manage back to the 300 s tick if the 15 s loop stalls.
5. **A refuted glitch could act.** F2's "unconfirmable → act" did not separate "the reads failed" from "a newer answer refutes the print". **Fix:** refuted means nothing acts; only unreadable acts, and only on rows eToro holds no stop for, each case listed in the shadow (§5.3, F2a).
6. **Kill-switch bursts.** Sending every close at once can exceed eToro's 20-a-minute execution quota, and a 429'd close waits 5 minutes today. **Fix:** a 429 on a protective close is resent after Retry-After, at most 3 times, unprotected rows first; never a resend after a timeout or 5xx (F2b, T23).
7. **The daily-loss gate.** A pending exit with no stop stayed invisible, and the gate fails open. **Fix:** eToro's own `/pnl` figure is the first provisional source (min(0, x)). The residual case, from F8 on, holds new real entries up to 1 hour (F2b, U28).
8. **REST polling above eToro's own guidance.** The fallback polled every 3 s and the watchdog every 15 s (5 s when pulled forward); eToro's skill gives 30-60 s for a live price. **Fix:** a floor of max(C_rest, 30 s) per batched GET. It is lowered to max(C_rest, 4 s) only on a measured C_rest plus eToro support's answer or the operator's written decision (§4.5.6, U26). It equals today's interim level.
9. **C_rest = 0 overclaimed:** reads 3 s apart cannot prove a cache shorter than 3 s. **Fix:** at best 3 s from M1; measured directly in M2 as REST's lag behind the stream (§5.4).
10. **Cross-channel Dates were compared before they were proven comparable.** **Fix:** M2 and F6 must show that the same PriceRateID carries the same Date on both channels before the comparison is used (§5.2).
11. **Screen steps backwards.** A P&L cell dropping from tier 1 to eToro's last figure stepped back up to 10 s in time (against I4), and the badge hid degradation for 2 s (against H7). **Fix:** newest-by-time across tiers; badges degrade at once (§4.7.4, §5.6, T24).
12. **Latency "skew-corrected" by its own median** would read about 0 by construction. **Fix:** raw latency on an NTP-synced host; skew checked against eToro's HTTP Date header (§5.3).
13. **The forex break was a fixed 22:00-22:05 GMT**, and M2's Sunday run (21:00-21:40 UTC) would miss the winter reopen (22:05 per the current tables). **Fix:** the break follows New York 17:00; the M2 windows are moved; a summer re-run is added; unmeasured windows refuse entries only and raise no alarm (§5.5, M2, T22).
14. **M4 could not work as written:** a hand close in the app yields no order id. **Fix:** history for the hand close, and the close-order read with an id Sauron kept from its own demo close (M4, F8 stores the id from now on).
15. **"One-tap close" in an alarm** would be a new money path from a message. **Fix:** alarms link to the CLOSE button (§5.8, §5.9, §9.18).
16. **The etbudget interim writer conflicts with I2.** Retiring it early would bring harms 1, 6, 17-20 back for held instruments. **Fix:** P-c; I2 holds from the end of F11; `write_quote` refuses `etoro*` only then; T21 (§2.2, harm 29, F11).
17. **Smaller fixes:** the `/pnl` anchor runs every 11 s, not 10 (cache edge); calibration is keyed by world; F12 subscribes `private:real` only; PATCHes are ≥ 3 s apart and counted on eToro's default pool; trade history needs a budget family; F7's fault test now expects degraded cells, not "live prices paused" (that chip is the browser's own socket).

### 10.4 The French summary

These claims were stronger than the spec and are corrected in `plan_fr.md`:
- sub-second prices "like the app's buttons" (a target, and whether they equal the app is unmeasured, U2);
- "eToro does not recompute faster" (only the API caches);
- "the reported gap disappears" (fees may remain, M3);
- "you see it at once" when the live feed is cut (the age grows and the badge turns at the grade threshold; "paused" is the browser's own socket);
- "the worst outside sources can do is make Sauron look again" (they can also refuse an entry);
- the end-state guarantees written as if already true;
- "the loss limit counts it as a prudent loss" (except the residual case);
- "never worse than today / exactly as today" (now true by the F9 fix, and said with its conditions);
- "no size on a stale exchange rate" (the 6 h bar fallback remains until F10b);
- three M1 runs (there are five);
- M4's order id;
- "un peu moins rapide" without the stream (much slower: the REST floor).

### 10.5 Still unverified

- That `etoro-public` is eToro's own GitHub organisation (self-declared only; org pages unreachable).
- Everything only seen through search extracts: the portal's rate-limit guide (60 reads a minute, per user key), the builders pages, the terms, and the help centre (P/L sides, CFD fee model and date, forex hours and break).
- Whether ws.etoro.com accepts an honest User-Agent, and every other §2.3 unknown (M1-M6).
- Whether eToro's API support accepts sub-30 s batched polling during stream outages (U26).
- etbudget's interim writer is uncommitted and may change before it lands (U25). This pass read it as it stood at 10:43 on 2026-11-06.
- pnltruth was read at `a08c87b`; if the branch has moved since (a later fix commit), its line numbers in §2.2 and P-b need a re-read.
- The "(map)" claims not spot-checked above, which keep their "(map)" mark.

### 10.6 Does the plan stand?

Yes. Design 2's skeleton holds: protection first, one authority, separate stores, one money door, and shadow before every PIN. The corrections make it hold by construction where it did not:
- F6 and F7 are now truly observe-only.
- Every money switch ships and turns on alone, after its own shadow.
- No switch can make Sauron hold where today acts.
- No REST cadence goes below eToro's own guidance without evidence.
- The in-flight interim writer has a defined, late exit.

Nothing found refutes the core eToro facts the design rests on (WS envelope and topics, REST rates and quotas, the `/pnl` 10 s cache, at-most-once trading). Their confidence is lower where the source is a third-party copy of eToro's spec.
