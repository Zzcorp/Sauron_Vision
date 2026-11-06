"""T1, N1 BY CONSTRUCTION (the O2 spec §0 N1 test items a-h, A.3, A.45b and
§1.0 item 5; 2026-11-05): nothing an Orc decides can reach an order, a
stop, a size or a close, judged from the source.

What it scans: every .py of bot_program/orcs/ and
bot_program/management/commands/orcs.py. "O2 code" is a module O2 adds
(O2_MODULES) and each definition O2 adds to an O1 module (O2_CODE); the
definitions O1 left at ccc824d are frozen below (O1_DEFS), so a definition
that is neither O1's nor named here fails at once. Every later commit
extends O2_MODULES and O2_CODE; the O1 functions O2 must leave alone are
pinned by their source's hash (item h).

- (a) no order path, by name over the whole package (the two FORBIDDEN
  sets of O1, one allow-listed use) and, in O2 code, by structure: no call
  rooted at the tick's bot, a broker client or a value read from the
  tick's cache, and no import of or attribute reference to any callable of
  the order-path modules (found by introspection, so a mutator added later
  is forbidden on arrival);
- (b) the model is reached from mind_gateway.py only;
- (c) no trade-row write but the stamp's two O1 writers;
- (d) in O2 code, nothing with power written, judged by receiver;
- (e) the importers outside the package are frozen, and the order-path
  files import exactly their hooks, at exactly their sites;
- (f) OrcIntent, scheduler, mandate, validator, mind and mind_gateway are
  imported by the surfaces only;
- (g) no reverse-accessor read outside the surfaces;
- (h) the frozen O1 functions, as O2a leaves them (after N8's lock);
- A.45b: in O2 code, no write into the tick's own objects;
- A.3: `pending` is written by scheduler.py only, and so is `merged`
  (A.7: the merge is scheduler.absorb's, which the render pass calls);
- §1.0 item 5: every journal kind and author written is in
  JOURNAL_KINDS and AUTHORS (and O2 code names them as constants).

Each rule is also run on a planted violation (TheRulesCanFailTests), so a
green rule is one that can go red (P36, P37).

Run with:  python manage.py test tests.orcs.test_orc_o2a_shadow_pins
"""
import ast
import fnmatch
import hashlib
import importlib
import inspect
import pkgutil
from functools import lru_cache
from pathlib import Path

from django.conf import settings

from tests.orcs import test_orc_source_pins_o1b as o1b_pins
from tests.orcs import test_orc_switch_off as o1a_pins
from tests.orcs.helpers_o2 import ORC_BINDING, SEAT_BINDING, MindTestCase

BASE = Path(settings.BASE_DIR)
PKG = BASE / "bot_program" / "orcs"
COMMAND = BASE / "bot_program" / "management" / "commands" / "orcs.py"

# ── O2 code ───────────────────────────────────────────────────────────────

#: The modules O2 adds, whole (§1.1.3, §1.2.3, §1.3.3, §1.4.3). Each
#: commit adds its own. O2a's mind (2026-11-05): the gateway, the
#: doctrine, the validator, the officer, the evidence, the mind and the
#: scheduler's settle; O2a's queue grows the scheduler (admission, the
#: merge, the claim, the watchdogs, the breaker, the Orc's states); O2a's
#: arm (2026-11-05) adds the queued intents at the tick (intents.py) and
#: the scheduler's tickets. O2a's light (2026-11-05) adds no module: it
#: wires the render pass to the scheduler and rewrites the words. O2b's
#: route in shadow (2026-11-06) adds the pure router (router.py).
O2_MODULES = ("mind_gateway", "doctrine", "validator", "mandate", "evidence",
              "mind", "scheduler", "intents", "router")
#: Each definition O2 adds to an O1 module, by module and qualified name.
O2_CODE = {
    "journal": ("lock_budget", "orc_lock"),
    "models": ("OrcIntent", "OrcIntent.Meta", "OrcIntent.__str__"),
    # O2a's mind (2026-11-05)
    "switches": ("_component_on", "gate_code", "minds_on",
                 # O2a's queue (2026-11-05)
                 "minds_switch_on"),
    "dossier": ("cost_fraction", "decision_bars", "events_of", "vctx"),
    "dossier_position": ("event_words", "_decisions", "_ps3",
                         "_last_expectation", "_realized_loss",
                         "ps5_notes"),
    "grading": ("_usd_per", "mind_counts", "mind_tags",
                # completing O2a (2026-11-05): the grade's arm:would tag
                "graded_would"),
    "wake": ("_minds_on", "_evidence", "_render",
             # O2a's queue (2026-11-05): the facts hash v2, the plan's
             # watches, the army's metronome, F6's reference, the render
             # pass's admitted count
             "_print_band", "_watch_refs", "watch_key", "metronome_h",
             "_minds_switch_on", "RenderPass", "RenderPass.__new__",
             # O2a's light (2026-11-05): the gates read once per render, a
             # render pass that could not finish a wake (A.7)
             "_gate_code", "_render_failed",
             # O2b's route in shadow (2026-11-06): the route's money world
             # (the budget's) and the route recorded on every render
             "_route_world", "_route"),
    # O2a's light (2026-11-05): the words (A.4, A.62): a wake's status in
    # words, the card's intents and intellect, the plan on the line
    "notes": ("wake_status_t", "_intents", "intellect_after", "_has_plan",
              "_plan_short"),
    # O2a's light (2026-11-05): /orc reads the minds once, and the Orc's
    # model calls today
    "surfaces": ("_minds", "_model_calls"),
    # O2a's queue (2026-11-05): the minds' worker, its ticket, its watchdog
    "tasks": ("_think_ticket", "orc_think", "orc_minds_watch"),
    # O2a's arm (2026-11-05): the O arm's would mode, the intents taken at
    # the tick and expired at the close (A.42-A.45b)
    "ghost": ("_faith", "_take_intents", "_to_would", "arm_effective",
              "apply_intent", "_same_moment", "_would_ctx",
              "would_hand_line", "_step_would", "_expire_arm_closed",
              "_expire_after_close", "_tail_events"),
    # O2a's arm (2026-11-05): A.59's status and replay, the smoke (A.60),
    # its verdicts and the count of S (A.61)
    "command:orcs": ("Command._mind_replay", "Command._validation_words",
                     "Command._officer_words", "Command._minds_status",
                     "Command._smoke", "Command._smoke_wake",
                     "Command._smoke_answer", "Command._orc_of",
                     "Command._gates_words", "Command._smoke_verdict",
                     "Command._tokens"),
}

#: Every definition (function, class, method) of the package and of the
#: orcs command at ccc824d, the commit O2a starts from, read from the tree
#: of that commit. A definition outside this list is O2 code.
O1_DEFS = {
    "__init__": "",
    "army": (
        "ArmyType ArmyType.vector _base _ratio _uruk_bar assign "
        "corsair_overlay name_of register"
    ),
    "bars": (
        "Frame Frame.atr Frame.label Frame.last_close Frame.venue "
        "_daily_from_4h _instrument _load _newest_other_source _swings _utc "
        "complete_bars_after final_bar final_df final_end frame fresh "
        "open_seconds source_label span_of"
    ),
    "birth": (
        "_compact _create _ensure_quietly _existing _leg_orc _seat "
        "adoption_line ensure ensure_on_commit fail_toward_manual "
        "menu_at_birth menu_line notify_adopted paper_cap paper_left "
        "paper_room r_money skip_reason ticked world"
    ),
    "census": "_births _restamp _seed_late run",
    "complexity": (
        "_c _decision _disagreement _f _gap _news _prints _rank _raw "
        "_regime _reversibility _size _stop _stress _vol band components "
        "day_class day_score f5 f6 floors piecewise score stakes"
    ),
    "constants": "",
    "dossier": (
        "_contradiction_atr _currencies _f _mark _tokens_of block "
        "context_for decision_tf dumps estimate_tokens family_of find "
        "hash_of render text_for text_of token_factor trim"
    ),
    "dossier_instrument": (
        "_cot _frame_block _gaps _in_slow_body _levels _mk_tokens "
        "_positioning _print_gap _px _read_in_slow _rows _structure "
        "_tape_slot _utc build_in_slow floor_pivots in12 in_slow in_today "
        "tape_rows"
    ),
    "dossier_market": (
        "_class_today _clusters _hm _key _mk1 _mk5 _mk6 _mk9 _regimes "
        "_session_body _window build_day build_mk0 build_session day_hashes "
        "mk0 mk_e mk_now mk_session"
    ),
    "dossier_position": (
        "_debate_view _f _headline _operator_view _ps1 _ps2 _ps4 _ps5 _ps6 "
        "_ps7 _ps8 _r _recovery _thesis_check held_symbols ps ps12"
    ),
    "drum_bus": (
        "_atr1h _care_stop_hit _f _factor_map _last _level_breaks _living "
        "_news_shocks _now _print_surprises _px _reach _ring _sweeps "
        "_urgent_for _why_of census_market corroborated drums_on "
        "hourly_market median_surprise number on_close on_close_quietly "
        "on_tick publish route sample_ring"
    ),
    "drums": (
        "_factors _hhmm _legs _rho _x line payload_level_break payload_lock "
        "payload_news_shock payload_print payload_stop_hit payload_sweep "
        "payload_thesis reach wave_of"
    ),
    "facts": (
        "_bucket _care_state _f _hhmm _latest_review_id _open_legs "
        "_part_words _sentence _venue_news _when army_line baseline "
        "birth_line close_how close_line initial_stop is_hand_close "
        "observe_pending observe_reviews observe_tick overlay_line px r_at "
        "with_r"
    ),
    "fence": (
        "_content band_of fact_kind quarantine sanitize untrusted "
        "v10_satisfied view withheld_in"
    ),
    "gaps": (
        "Gap _currencies _hourly _key _memo _shut_pairs in_r measured "
        "next_shut_gap overnight_gap p90 print_gap range_gap waiver_check "
        "weekend_gap"
    ),
    "ghost": (
        "RealExit ShadowRow ShadowRow.id _Env _Env.__init__ _Env.frame "
        "_arm_stop _bank _basis_sample _best_on_bar _cap_mark _care_step "
        "_ceiling _cf _close_past_cap _close_track _closed_end _common "
        "_crossings _dec _engine_knobs _events_between _exit _f _iso "
        "_journal_exits _k_draw _knobs _last_edit_at _mirror _missed "
        "_note_source _parse _playbook_bars _policy_bar _policy_walk "
        "_recovered_mark _resting _root_mark _rx_source _same _seed_orc "
        "_seed_playbook _seed_policy _shares _step_care _step_orc "
        "_step_playbook _step_policy _tail_bar _tail_k_draw _tail_tstruct "
        "_tail_x_thesis _take_care _tick_dict _tick_from _tighter "
        "_to_shadow _upgraded add_market_hours arm_r compare_line exit_line "
        "faith_line faithfulness hand_line price_real_exit real_exit_of "
        "seed_care_like seed_tracks shadow_of step_bars step_tick tail_cap "
        "tick_of upgrade_old"
    ),
    "grading": (
        "_f _first_divergence _level_at_birth _rr bar_source grade "
        "grade_line numbers shadow_audit"
    ),
    "integrity": "_utc allowed_actions_l0 shrink verdict words",
    "journal": (
        "_merge add_keys add_reasons append consume_reasons merge_seen "
        "remember"
    ),
    "lifecycle": (
        "_close_leg _closed_quietly _leg_saved _reentry_open kill_all "
        "on_leg_closed sweep"
    ),
    "menu": (
        "Level Menu Menu.as_dict _f _frame_levels _kind_of _ranked "
        "_round_levels _snap _stop_for basis_stable for_idea level_by_id "
        "symbol_levels"
    ),
    "models": (
        "Orc Orc.Meta Orc.__str__ Orc.label OrcDayBaseline "
        "OrcDayBaseline.Meta OrcDossierBlock OrcDrum OrcDrum.Meta OrcGrade "
        "OrcJournal OrcJournal.Meta OrcJournal.__str__ OrcLeg OrcLeg.Meta "
        "OrcLeg.__str__ OrcSeat OrcSeat.Meta OrcSeat.__str__ OrcSetting "
        "OrcSetting.__str__ OrcSetting.get OrcTrack OrcTrack.Meta OrcWake "
        "OrcWake.Meta"
    ),
    "notes": (
        "_army_names _as_dict _drum _drums _f _first_invalidation "
        "_integrity _intellect _iso _j_line _journal _line _lineage "
        "_note_short _original_qty _plain_voice _preds _px _sentence "
        "_thesis _thesis_operator _when army_words close_note "
        "close_note_for compare day_hhmm effective_level for_classes "
        "for_rows for_trades held_stop hhmm invalidation_t is_open "
        "is_reserved last_fact line line_dict next_wake_t plan_line r_words "
        "refresh risk_line risk_r slot stamped"
    ),
    "observe": (
        "_check_predicates _detect_wakes _drums_tick _now_of _observe_tick "
        "_snapshot_seen _step_ghosts after_care"
    ),
    "plain": "row_marks voice",
    "playbook": "Candidate _d _f candidates k_draw t_struct trail_tf x_thesis",
    "predicates": (
        "Result Result.as_dict _closed_bars _closed_end _f _hhmm "
        "_nearest_inside _stale check code_invalidation decision_tf "
        "evaluate frames_for key_of met_line unchecked_line"
    ),
    "pricing": (
        "Tick _pos closing_mark d half_spread level_exit_px market_exit_px "
        "one_way r_of spread_of stop_exit_px target_exit_px"
    ),
    "ranks": "_level badge holds level_t name",
    "sessions": (
        "_at_ny _kind _ny closed_sessions current_session day_bounds "
        "final_sessions next_shut session_spans session_windows "
        "shuts_within trading_day"
    ),
    "situation": (
        "_crypto_weekend _f _instrument _prints _spread atr_of currencies "
        "exotic_legs gap_p90_r situation_for"
    ),
    "sources": (
        "_atr_until _bars_between _crisis_on _f _hhmm _instrument "
        "_live_book _paper_book _pct _po3_at _source_in _utc _world_live "
        "actuals_measurement analyst_blind board_session book brief "
        "calendar calendar_rows correlation dash fred headlines horizon "
        "mind news_ratio ok posture posture_changed_h quote quotes shown "
        "vix_term"
    ),
    "surfaces": (
        "_carrier _class_of _closed_line _f _grade_line _inner _number "
        "_r_line _side _stops_line _tracks _world help_lines names_orcs "
        "orc_card orc_reply orcs_reply parse_quoted resolve"
    ),
    "switches": "orcs_on",
    "tasks": (
        "_living_classes grade_closed orc_census orc_day_roll orc_hourly "
        "orc_render_wakes orc_session_close shadow_audit track_ghosts"
    ),
    "thesis": (
        "_clean _debate _memory_rule _moves _persona_hold _plain_killer "
        "build complete_provenance horizon invalidation provenance "
        "reconstructed_from setup_memory"
    ),
    "tracks": "_f seed_at_birth seed_care",
    "tribunal": "IdeaFacts Verdict block_faults block_stats classify",
    "wake": (
        "_atr_ratio _closing_mark _components _detect _done_keys "
        "_earnings_of _f _iso _kind_of _living _one_shot _parse _pend "
        "_position_inputs _queue _reading _reason _snapshot _symbol_flip "
        "_w10 _w11 _w2 _w3 _w4 _w6_w8_w9 _world census_book census_clock "
        "census_pending detect facts_hash reasons_words record "
        "render_queued render_wake"
    ),
    "weather": (
        "_cheap_stamp _class_currencies _compute _market _stamp caps_for "
        "current hourly market_inputs"
    ),
    "command:orcs": (
        "Command Command._actuals Command._adopt Command._audit "
        "Command._dossier Command._status Command.add_arguments "
        "Command.handle"
    ),
}

# ── the names and the writes O1 already bans ──────────────────────────────

FORBIDDEN = set(o1b_pins.FORBIDDEN) | set(o1a_pins.TheSourcePinTests.FORBIDDEN)
#: (module, enclosing definition, name): birth.notify_adopted tells the
#: operator of an adopted real-money row (K-R12), O1's one notice.
FORBIDDEN_ALLOWED = {("birth", "notify_adopted", "dispatch_notification")}
WRITES = set(o1b_pins.WRITES)
#: The stamp's two O1 writers, each under the row's lock: the birth's
#: (birth._create, in the Orc's own transaction) and the census's restamp.
TRADE_WRITERS = {("birth", "_create"), ("census", "_restamp")}

#: The one module that may name the provider (A.22).
GATEWAY = "mind_gateway"
MODEL_WORDS = ("ai_agents", "anthropic")
MODEL_IDENTIFIERS = {"ClaudeProvider", "BaseAgent", "can_spend",
                     "count_tokens", "total_only"}

# ── the order path ────────────────────────────────────────────────────────

#: The packages and modules whose callables O2 code never references
#: (N1.3, test item a).
ORDER_PATH_PACKAGES = ("bot_program.asset_engine", "bot_program.engine")
ORDER_PATH_MODULES = ("bot_program.position_care", "bot_program.manual_close",
                      "bot_program.venue_exit", "bot_program.adjust_levels")
#: The pinned reads: the care's plan (the care ghost's arithmetic).
ORDER_PATH_READS = {("bot_program.position_care", "plan")}
#: The tick's objects a call must never be rooted at, and the reads allowed.
TICK_ROOTS = {"bot", "client", "broker", "broker_client"}
TICK_CACHES = ("_tick_broker_cache", "_last_ticks")
TICK_READS = {"cfg", "user", "asset_class", "_tick_broker_cache",
              "_last_ticks"}

#: The order-path files (test item e) and the hooks they hold: (file, the
#: definition the import sits in, module, name). Nothing else of the
#: package may be imported there.
ORDER_PATH_FILES = (
    "bot_program/asset_engine/*.py", "bot_program/engine/*.py",
    "bot_program/manual_trade.py", "bot_program/manual_close.py",
    "bot_program/paper_exits.py", "bot_program/position_care.py",
    "bot_program/morgul.py", "bot_program/aragorn*.py",
    "bot_program/smart_money.py", "bot_program/share_allocator.py")
HOOKS = {
    ("bot_program/asset_engine/base.py", "AssetBot.manage_positions",
     "bot_program.orcs.observe", "after_care"),
    ("bot_program/asset_engine/base.py", "AssetBot.execute_entry",
     "bot_program.orcs.birth", "ensure_on_commit"),
    ("bot_program/asset_engine/base.py", "AssetBot._finish_working_entry",
     "bot_program.orcs.birth", "ensure_on_commit"),
    ("bot_program/manual_trade.py", "_execute._book_row",
     "bot_program.orcs.birth", "ensure_on_commit"),
    ("bot_program/asset_engine/runner.py", "_stamp_desk_keys",
     "bot_program.orcs.thesis", "complete_provenance"),
    ("bot_program/engine/kill_switch.py", "execute_kill_switch",
     "bot_program.orcs.lifecycle", "kill_all"),
}
#: The receiver is no import of the order path: bot_program/apps.py loads
#: lifecycle, whose _leg_saved is connected to every trade-row save.
RECEIVER = ("bot_program/apps.py", "BotProgramConfig.ready",
            "bot_program.orcs", "lifecycle")

#: The files outside the package that import it, computed from the import
#: nodes at ccc824d (never the comments). Grows only by the files the spec
#: names (NAMED_BY_THE_SPEC, extended by the commit that adds one).
FROZEN_IMPORTERS = {
    "bot_program/apps.py", "bot_program/asset_engine/base.py",
    "bot_program/asset_engine/runner.py", "bot_program/engine/kill_switch.py",
    "bot_program/management/commands/orcs.py",
    "bot_program/management/commands/scorecard.py",
    "bot_program/manual_trade.py", "bot_program/models.py",
    "bot_program/scorecard.py", "bot_program/telegram_eye.py",
    "dashboard/horde.py", "dashboard/views.py", "dashboard/views_close.py",
    "dashboard/views_orcs.py", "market_data/bot_bars.py",
    "market_data/candle_headroom.py",
}
NAMED_BY_THE_SPEC = {
    # O2a's light (2026-11-05, the O2 spec A.62): the band's sentence under
    # THE TRADERS counts the living Orcs (switches, constants, models)
    "dashboard/council_band.py",
}

#: The surfaces that show what a model wrote (N1.6, test items f and g).
SURFACES = {
    "dashboard/views_orcs.py", "dashboard/horde.py", "dashboard/views.py",
    "dashboard/views_close.py", "bot_program/telegram_eye.py",
    "bot_program/scorecard.py", "bot_program/management/commands/orcs.py",
    "bot_program/management/commands/scorecard.py",
}
#: What only the surfaces import (test item f). bot_program/models.py
#: re-exports every Orc table for the app's model registry, OrcIntent
#: included, and is allowed that one name.
SURFACE_ONLY = {"OrcIntent", "scheduler", "mandate", "validator", "mind",
                "mind_gateway"}
REGISTRY = ("bot_program/models.py", "OrcIntent")
#: The reverse accessors from the platform's rows to the Orcs (test g).
REVERSE = {"orc", "orc_leg", "orcs"}

# ── the frozen O1 functions (test item h) ─────────────────────────────────

#: sha256 of inspect.getsource, as O2a leaves them: after N8's lock
#: (lifecycle's _closed_quietly, _close_leg and kill_all take the Orc's
#: lock through journal.orc_lock, under the money paths' lock budget). A
#: change to one is a deliberate pin change in the same commit, with its
#: reason in the commit message.
FROZEN_SOURCES = {
    ("birth", "_create"):
        "201d02f6758d08a6d004029a39098585899db0c30806fbd295952f3321d691f8",
    ("lifecycle", "_leg_saved"):
        "1e9361620745e7d12c0eb6a2747021cd711331d9047764279de753c3590246b4",
    ("lifecycle", "_closed_quietly"):
        "365f02d8e9996d0871610371d079396ebd4bfcf091c19154e18268bd83ee30e7",
    ("lifecycle", "on_leg_closed"):
        "7ef3521a6f673ec685c3b9573df747c305edd1df51d7b476f370ad5b42973ccc",
    ("lifecycle", "_close_leg"):
        "545e324a49de6df30d6deee66f6b8b193723edbee6347357cbb60282e18832c2",
    ("lifecycle", "kill_all"):
        "83e3b5262cc00d86b7a8b8431bec493ecf45324109476202e48f037ef0ae9bb9",
    ("drum_bus", "on_close"):
        "85f4ed15e6711e3c263e976e84f35c24ffd5a7890460727981f565df12a6f4ee",
}

# ── A.45b, A.3 and §1.0 item 5 ────────────────────────────────────────────

#: The tick's objects (A.45b): the real row, its metadata and context, the
#: bot. O2 code reads them and never writes into them.
TICK_OBJECTS = {"trade", "row", "root_trade", "bot"}
ENV_OBJECTS = {"row", "meta", "ctx", "bot"}
MUTATORS = {"update", "setdefault", "pop", "popitem", "clear", "append",
            "extend", "insert", "remove", "save", "delete", "refresh_from_db"}
#: Calls whose result is a new object, never the tick's own.
COPIES = {"dict", "list", "set", "tuple", "frozenset", "deepcopy", "copy",
          "str", "int", "float", "bool", "Decimal", "len", "sorted", "loads",
          "dumps", "round", "abs", "max", "min", "sum", "any", "all",
          "isinstance", "hasattr", "format_price", "_f"}
#: The one module that may write a `pending` wake (A.3).
PENDING_WRITER = "scheduler"
#: Calls that read with a status keyword, never write it.
READS = {"filter", "exclude", "get", "Q", "count", "exists", "first",
         "last", "values", "values_list", "annotate", "aggregate",
         "order_by", "only", "defer", "select_related", "in_bulk"}


# ── reading the tree ──────────────────────────────────────────────────────

def package_files():
    """(module key, path) of every .py of the package and the command."""
    out = [(p.stem, p) for p in sorted(PKG.glob("*.py"))]
    out.append(("command:orcs", COMMAND))
    return out


@lru_cache(maxsize=None)
def tree_of(path):
    return ast.parse(Path(path).read_text(encoding="utf-8"))


def defs_of(tree) -> dict:
    """qualified name -> node, for every def and class (methods
    included, nested functions not)."""
    out = {}

    def walk(body, prefix):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                out[prefix + node.name] = node
                if isinstance(node, ast.ClassDef):
                    walk(node.body, prefix + node.name + ".")
    walk(tree.body, "")
    return out


def scoped(tree):
    """(node, the innermost enclosing def's qualified name) for every
    node; "" at module level."""
    todo = [(tree, "")]
    while todo:
        node, scope = todo.pop()
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef)):
                yield child, scope
                todo.append((child, f"{scope}.{child.name}" if scope
                             else child.name))
            else:
                yield child, scope
                todo.append((child, scope))


def docstrings(tree) -> set:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef,
                             ast.AsyncFunctionDef, ast.ClassDef)) \
                and node.body and isinstance(node.body[0], ast.Expr) \
                and isinstance(node.body[0].value, ast.Constant) \
                and isinstance(node.body[0].value.value, str):
            out.add(id(node.body[0].value))
    return out


def chain_of(node) -> list:
    """The dotted parts of an expression, outermost last, walking through
    calls and subscripts; the root is "" when it is not a name."""
    parts = []
    while True:
        if isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        elif isinstance(node, ast.Call):
            node = node.func
        elif isinstance(node, ast.Subscript):
            node = node.value
        else:
            break
    parts.append(node.id if isinstance(node, ast.Name) else "")
    return list(reversed(parts))


def identifiers(node):
    """(name, node) for every name the source spells: names, attributes,
    imported modules and aliases."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            yield sub.id, sub
        elif isinstance(sub, ast.Attribute):
            yield sub.attr, sub
        elif isinstance(sub, ast.alias):
            for part in sub.name.split("."):
                yield part, sub
            if sub.asname:
                yield sub.asname, sub
        elif isinstance(sub, ast.ImportFrom) and sub.module:
            for part in sub.module.split("."):
                yield part, sub


def _strs(node) -> list:
    """The string constants of a list, tuple or set literal."""
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [e.value for e in node.elts if isinstance(e, ast.Constant)
                and isinstance(e.value, str)]
    return []


def _dict_keys(node) -> list:
    if isinstance(node, ast.Dict):
        return [k.value for k in node.keys if isinstance(k, ast.Constant)
                and isinstance(k.value, str)]
    return []


def o2_units():
    """(module, qualified name, node) of every unit of O2 code."""
    units = []
    for mod, path in package_files():
        tree = tree_of(path)
        if mod in O2_MODULES:
            units.append((mod, "*", tree))
            continue
        found = defs_of(tree)
        for qual in O2_CODE.get(mod, ()):
            if qual in found:
                units.append((mod, qual, found[qual]))
    return units


# ── the rules, each a function of a tree (the planted tests run them) ─────

def forbidden_names(tree, mod) -> list:
    """(a) The FORBIDDEN names anywhere but their one allowed use; the
    model's names are (b)'s, and the gateway's own."""
    banned = FORBIDDEN - (set(MODEL_WORDS) if mod == GATEWAY else set())
    out = []
    for node, scope in scoped(tree):
        for name, _sub in identifiers(node) if isinstance(
                node, (ast.Name, ast.Attribute, ast.Import,
                       ast.ImportFrom)) else ():
            if name in banned and (mod, scope, name) not in FORBIDDEN_ALLOWED:
                out.append(f"{mod}:{getattr(node, 'lineno', '?')} {name}")
    return sorted(set(out))


def _tainted(fn, seed) -> set:
    """Names bound in `fn` from an expression that names one of `seed`
    (or a name already tainted), to a fixed point."""
    names = set()
    for _ in range(4):
        before = set(names)
        for sub in ast.walk(fn):
            if isinstance(sub, (ast.Assign, ast.AnnAssign)) and sub.value \
                    is not None:
                spelled = {n for n, _ in identifiers(sub.value)}
                consts = {c.value for c in ast.walk(sub.value)
                          if isinstance(c, ast.Constant)}
                if spelled & (seed | names) or consts & seed:
                    targets = sub.targets if isinstance(sub, ast.Assign) \
                        else [sub.target]
                    for t in targets:
                        for n in ast.walk(t):
                            if isinstance(n, ast.Name):
                                names.add(n.id)
        if names == before:
            break
    return names


def tick_calls(fn) -> list:
    """(a) Calls rooted at the tick's bot, a broker client or a value read
    from the tick's cache; reads of the cache's `get` and of cfg, user and
    asset_class are allowed."""
    cached = _tainted(fn, set(TICK_CACHES))
    out = []
    for sub in ast.walk(fn):
        if not isinstance(sub, ast.Call):
            continue
        chain = chain_of(sub.func)
        if chain[0] in ("env", "self") and len(chain) > 1 and \
                chain[1] == "bot":
            chain = chain[1:]
        if chain[0] in ("getattr", "setattr", "delattr") and sub.args:
            target = chain_of(sub.args[0])
            attr = sub.args[1].value if len(sub.args) > 1 and isinstance(
                sub.args[1], ast.Constant) else None
            if (target[0] in TICK_ROOTS or target[0] in cached) and not (
                    chain[0] == "getattr" and attr in TICK_READS):
                out.append(ast.unparse(sub)[:80])
            continue
        through_cache = any(p in TICK_CACHES for p in chain[:-1])
        if not (chain[0] in TICK_ROOTS or chain[0] in cached
                or through_cache):
            continue
        if chain[-1] == "get" and (through_cache or chain[0] in cached):
            continue
        out.append(".".join(p for p in chain if p))
    return out


@lru_cache(maxsize=1)
def order_path_callables() -> dict:
    """name -> where, for every function and method the order-path
    modules define, found by introspection."""
    mods = []
    for pkg_name in ORDER_PATH_PACKAGES:
        pkg = importlib.import_module(pkg_name)
        for info in pkgutil.iter_modules(pkg.__path__):
            mods.append(importlib.import_module(f"{pkg_name}.{info.name}"))
    mods += [importlib.import_module(m) for m in ORDER_PATH_MODULES]
    out = {}
    for mod in mods:
        for name, obj in vars(mod).items():
            if inspect.isfunction(obj) and obj.__module__ == mod.__name__:
                out.setdefault(name, mod.__name__)
            elif inspect.isclass(obj) and obj.__module__ == mod.__name__:
                for mname, mobj in vars(obj).items():
                    if inspect.isfunction(mobj) or isinstance(
                            mobj, (staticmethod, classmethod)):
                        out.setdefault(mname, f"{mod.__name__}.{name}")
    return out


@lru_cache(maxsize=1)
def package_names() -> set:
    """Every name the Orcs package defines or binds at module level."""
    out = set()
    for _mod, path in package_files():
        tree = tree_of(path)
        out |= {q.rsplit(".", 1)[-1] for q in defs_of(tree)}
        for node in tree.body:
            for t in (node.targets if isinstance(node, ast.Assign) else []):
                out |= {n.id for n in ast.walk(t) if isinstance(n, ast.Name)}
    return out


@lru_cache(maxsize=1)
def order_path_names() -> set:
    """The callables of the order path that O2 code may not reference:
    less the generic names Python's and Django's own types carry, the
    package's own names, and the pinned reads."""
    from django.db import models
    from django.db.models.query import QuerySet
    generic = set()
    for t in (dict, list, str, set, tuple, object, int, float, Exception,
              models.Model, QuerySet, models.Manager):
        generic |= set(dir(t))
    reads = {name for _m, name in ORDER_PATH_READS}
    return {n for n in order_path_callables()
            if not (n.startswith("__") and n.endswith("__"))
            and n not in generic and n not in package_names()
            and n not in reads}


def _order_path_module(name) -> bool:
    return any(name == p or name.startswith(p + ".")
               for p in ORDER_PATH_PACKAGES + ORDER_PATH_MODULES)


def order_path_refs(node) -> list:
    """(a) In O2 code: no import of the order path (but its pinned reads)
    and no attribute reference to one of its callables."""
    names = order_path_names()
    leaves = {m.rsplit(".", 1)[-1]
              for m in ORDER_PATH_PACKAGES + ORDER_PATH_MODULES}
    out = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.ImportFrom) and sub.module:
            if _order_path_module(sub.module):
                out += [f"import {sub.module}.{a.name}" for a in sub.names
                        if (sub.module, a.name) not in ORDER_PATH_READS]
            elif sub.module == "bot_program":
                out += [f"import bot_program.{a.name}" for a in sub.names
                        if a.name in leaves]
        elif isinstance(sub, ast.Import):
            out += [f"import {a.name}" for a in sub.names
                    if _order_path_module(a.name)]
        elif isinstance(sub, ast.Attribute) and sub.attr in names:
            where = order_path_callables()[sub.attr]
            out.append(f"{ast.unparse(sub)[:60]} ({where})")
    return out


def model_reach(tree, mod) -> list:
    """(b) Outside the gateway: the provider's names, a string naming it
    (docstrings aside), a dynamic import of it, its identifiers."""
    if mod == GATEWAY:
        return []
    docs = docstrings(tree)
    out = []
    for name, sub in identifiers(tree):
        if any(w in name for w in MODEL_WORDS) or name in MODEL_IDENTIFIERS:
            out.append(f"{mod}:{getattr(sub, 'lineno', '?')} {name}")
    for sub in ast.walk(tree):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) \
                and id(sub) not in docs \
                and any(w in sub.value for w in MODEL_WORDS):
            out.append(f"{mod}:{sub.lineno} string {sub.value[:40]!r}")
        if isinstance(sub, ast.Call) and chain_of(sub.func)[-1] in (
                "import_module", "__import__", "get_model"):
            args = [a.value for a in sub.args if isinstance(a, ast.Constant)
                    and isinstance(a.value, str)]
            if any("ai_agents" in a or "anthropic" in a for a in args):
                out.append(f"{mod}:{sub.lineno} {ast.unparse(sub)[:60]}")
    return out


def own_nodes(node):
    """The nodes of `node`'s body, never those of a def nested in it."""
    todo = list(ast.iter_child_nodes(node))
    while todo:
        sub = todo.pop()
        yield sub
        if not isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef,
                                ast.ClassDef, ast.Lambda)):
            todo.extend(ast.iter_child_nodes(sub))


QUERYSET = {"objects", "filter", "exclude", "all", "select_related",
            "prefetch_related", "select_for_update", "only", "defer",
            "order_by", "first", "last", "get", "latest", "earliest",
            "using"}


def _rows_of(fn) -> set:
    """Names bound in `fn` to trade rows: assigned from a chain rooted at
    AssetBotTrade's manager, or at such a name through queryset steps."""
    rows = set()
    for _ in range(3):
        before = set(rows)
        for sub in own_nodes(fn):
            if isinstance(sub, ast.Assign):
                chain = chain_of(sub.value)
                if (chain[:2] == ["AssetBotTrade", "objects"]
                        or chain[0] in rows) and set(chain[1:]) <= QUERYSET:
                    rows |= {t.id for t in sub.targets
                             if isinstance(t, ast.Name)}
        if rows == before:
            break
    return rows


def trade_row_writes(tree, mod) -> list:
    """(c) A call chain that names AssetBotTrade, or a name bound to its
    rows, ending in a write; but inside the stamp's two O1 writers."""
    units = [("", tree)]
    for node, scope in scoped(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            units.append((f"{scope}.{node.name}" if scope else node.name,
                          node))
    out = []
    for qual, node in units:
        if any(m == mod and (qual == q or qual.startswith(q + "."))
               for m, q in TRADE_WRITERS):
            continue
        rows = _rows_of(node) if qual else set()
        for sub in own_nodes(node):
            if isinstance(sub, ast.Call):
                chain = chain_of(sub.func)
                named = "AssetBotTrade" in chain or chain[0] in rows
                if named and set(chain) & WRITES:
                    out.append(f"{mod}.{qual or 'module'}:{sub.lineno} "
                               f"{'.'.join(chain)}")
    return sorted(set(out))


def _receivers(fn, base, seeds):
    """Names in `fn` bound to an `base` row: the seeds, and every name
    assigned from `base.objects` or from orc_lock (for an Orc)."""
    found = set(seeds)
    for sub in ast.walk(fn):
        if isinstance(sub, (ast.Assign, ast.AnnAssign)) and sub.value \
                is not None:
            chain = chain_of(sub.value)
            spelled = ".".join(chain)
            if f"{base}.objects" in spelled or (
                    base == "Orc" and chain[-1] == "orc_lock"):
                targets = sub.targets if isinstance(sub, ast.Assign) \
                    else [sub.target]
                for t in targets:
                    found |= {n.id for n in ast.walk(t)
                              if isinstance(n, ast.Name)}
    return found


def _on(chain, base, names, extra=()) -> bool:
    return (chain[:2] == [base, "objects"] or chain[0] in names
            or any(chain[:len(e)] == list(e) for e in extra))


def power_writes(fn) -> list:
    """(d) In O2 code, by receiver: a binding Orc column, an OrcSeat's
    level, status or pinned, a DROP_META key or "orc_exit" in a trade's
    metadata, written by a store, setattr, update(), create(),
    bulk_update(), update_fields= or journal.append(fields=...)."""
    from bot_program.orcs.ghost import DROP_META
    meta_keys = set(DROP_META) | {"orc_exit"}
    orcs = _receivers(fn, "Orc", {"orc", "locked"})
    seats = _receivers(fn, "OrcSeat", {"seat"})
    targets = (("Orc", orcs, set(ORC_BINDING), ()),
               ("OrcSeat", seats, set(SEAT_BINDING), (("orc", "seat"),)))
    out = []
    for sub in ast.walk(fn):
        stores = []
        if isinstance(sub, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            stores = sub.targets if isinstance(sub, ast.Assign) \
                else [sub.target]
        for t in stores:
            if isinstance(t, ast.Attribute):
                chain = chain_of(t.value)
                for base, names, cols, extra in targets:
                    if t.attr in cols and _on(chain, base, names, extra):
                        out.append(f"{sub.lineno} {ast.unparse(t)}")
                if t.attr == "metadata" and set(_dict_keys(
                        getattr(sub, "value", None))) & meta_keys:
                    out.append(f"{sub.lineno} {ast.unparse(t)} = {{...}}")
            if isinstance(t, ast.Subscript):
                holder = chain_of(t.value)
                key = t.slice.value if isinstance(t.slice, ast.Constant) \
                    else None
                if (holder[-1] == "metadata" or holder == ["meta"]) and \
                        key in meta_keys:
                    out.append(f"{sub.lineno} {ast.unparse(t)}")
        if not isinstance(sub, ast.Call):
            continue
        chain = chain_of(sub.func)
        last = chain[-1]
        kw = {k.arg: k.value for k in sub.keywords if k.arg}
        if last in ("setattr", "delattr") and len(sub.args) > 1 and \
                isinstance(sub.args[1], ast.Constant):
            holder = chain_of(sub.args[0])
            for base, names, cols, extra in targets:
                if sub.args[1].value in cols and _on(holder, base, names,
                                                     extra):
                    out.append(f"{sub.lineno} {ast.unparse(sub)[:60]}")
        for base, names, cols, extra in targets:
            if not _on(chain[:-1] or [""], base, names, extra):
                continue
            if last in ("update", "create", "update_or_create",
                        "get_or_create", "bulk_create"):
                hit = set(kw) & cols
                hit |= set(_dict_keys(kw.get("defaults"))) & cols
                if hit:
                    out.append(f"{sub.lineno} {'.'.join(chain)} {sorted(hit)}")
            if last == "bulk_update":
                fields = kw.get("fields") or (sub.args[1] if len(sub.args) > 1
                                              else None)
                if set(_strs(fields)) & cols:
                    out.append(f"{sub.lineno} {'.'.join(chain)}")
            if last == "save" and set(_strs(kw.get("update_fields"))) & cols:
                out.append(f"{sub.lineno} {'.'.join(chain)} update_fields")
        if last in ("append", "remember") and (
                chain[0] == "journal" or chain == [last]):
            if set(_dict_keys(kw.get("fields"))) & set(ORC_BINDING):
                out.append(f"{sub.lineno} journal.{last}(fields=...)")
        if last in ("update", "setdefault") and (
                chain[-2:-1] == ["metadata"] or chain[:-1] == ["meta"]):
            keys = set(kw)
            for a in sub.args:
                keys |= set(_dict_keys(a))
            if last == "setdefault" and sub.args and isinstance(
                    sub.args[0], ast.Constant):
                keys.add(sub.args[0].value)
            if keys & meta_keys:
                out.append(f"{sub.lineno} {'.'.join(chain)}")
        if "AssetBotTrade" in chain and set(_dict_keys(
                kw.get("metadata"))) & meta_keys:
            out.append(f"{sub.lineno} {'.'.join(chain)}(metadata=...)")
    return out


def _rooted(expr, aliases) -> bool:
    """True when `expr` is one of the tick's objects, or reads into one
    without copying it."""
    if isinstance(expr, ast.IfExp):
        return _rooted(expr.body, aliases) or _rooted(expr.orelse, aliases)
    if isinstance(expr, ast.BoolOp):
        return any(_rooted(v, aliases) for v in expr.values)
    if isinstance(expr, ast.NamedExpr):
        return _rooted(expr.value, aliases)
    if isinstance(expr, ast.Call):
        if isinstance(expr.func, ast.Name) and expr.func.id == "getattr":
            # getattr(trade, "metadata") is the row's own dict
            return bool(expr.args) and _rooted(expr.args[0], aliases)
        if not isinstance(expr.func, ast.Attribute) or expr.func.attr in (
                "copy", "deepcopy") or chain_of(expr.func)[-1] in COPIES:
            return False
        return _rooted(expr.func.value, aliases)
    if not isinstance(expr, (ast.Name, ast.Attribute, ast.Subscript)):
        return False
    chain = chain_of(expr)
    return (chain[0] in TICK_OBJECTS or chain[0] in aliases
            or (chain[0] == "env" and len(chain) > 1
                and chain[1] in ENV_OBJECTS))


def tick_object_writes(fn) -> list:
    """A.45b: in O2 code, no store, delete, setattr or mutating call into
    the tick's objects or a name bound to them without a copy."""
    aliases = set()
    for _ in range(4):
        before = set(aliases)
        for sub in ast.walk(fn):
            if isinstance(sub, (ast.Assign, ast.AnnAssign)) and \
                    sub.value is not None and _rooted(sub.value, aliases):
                targets = sub.targets if isinstance(sub, ast.Assign) \
                    else [sub.target]
                aliases |= {t.id for t in targets if isinstance(t, ast.Name)}
            if isinstance(sub, (ast.For, ast.comprehension)) and \
                    _rooted(sub.iter, aliases):
                aliases |= {n.id for n in ast.walk(sub.target)
                            if isinstance(n, ast.Name)}
        if aliases == before:
            break
    aliases -= {"self"}
    out = []
    for sub in ast.walk(fn):
        stores = []
        if isinstance(sub, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            stores = sub.targets if isinstance(sub, ast.Assign) \
                else [sub.target]
        elif isinstance(sub, ast.Delete):
            stores = sub.targets
        for t in stores:
            for part in (t.elts if isinstance(t, ast.Tuple) else [t]):
                if isinstance(part, (ast.Attribute, ast.Subscript)) and \
                        _rooted(part.value, aliases):
                    out.append(f"{sub.lineno} {ast.unparse(part)[:60]}")
        if isinstance(sub, ast.Call):
            chain = chain_of(sub.func)
            if chain[-1] in ("setattr", "delattr") and len(chain) == 1 and \
                    sub.args and _rooted(sub.args[0], aliases):
                out.append(f"{sub.lineno} {ast.unparse(sub)[:60]}")
            elif isinstance(sub.func, ast.Attribute) and \
                    sub.func.attr in MUTATORS and \
                    _rooted(sub.func.value, aliases):
                out.append(f"{sub.lineno} {ast.unparse(sub)[:60]}")
    return out


def pending_values() -> set:
    from bot_program.orcs import constants as C
    return {"pending"} | {n for n, v in vars(C).items()
                          if isinstance(v, str) and v == "pending"}


def _is_pending(node, values) -> bool:
    if isinstance(node, ast.Constant):
        return node.value in values
    return chain_of(node)[-1] in values if isinstance(
        node, (ast.Name, ast.Attribute)) else False


def pending_writes(tree, mod, *, word="pending") -> list:
    """A.3: a `pending` status written, or an OrcWake created without a
    status of its own (the model's default is pending); outside
    scheduler.py. With `word` "merged" (A.7): the merge's status written
    outside scheduler.py (its absorb)."""
    if mod == PENDING_WRITER:
        return []
    from bot_program.orcs import constants as C
    values = (pending_values() if word == "pending" else
              {word} | {n for n, v in vars(C).items()
                        if isinstance(v, str) and v == word})
    out = []
    for sub in ast.walk(tree):
        if isinstance(sub, (ast.Assign, ast.AnnAssign)) and \
                sub.value is not None:
            targets = sub.targets if isinstance(sub, ast.Assign) \
                else [sub.target]
            for t in targets:
                # `w.status, w.skipped_reason = X, ""` pairs each target
                pairs = (zip(t.elts, sub.value.elts)
                         if isinstance(t, ast.Tuple)
                         and isinstance(sub.value, ast.Tuple)
                         else [(t, sub.value)])
                out += [f"{mod}:{sub.lineno} {ast.unparse(tt)}"
                        for tt, vv in pairs
                        if isinstance(tt, ast.Attribute)
                        and tt.attr == "status" and _is_pending(vv, values)]
        if not isinstance(sub, ast.Call):
            continue
        chain = chain_of(sub.func)
        kw = {k.arg: k.value for k in sub.keywords if k.arg}
        if chain[-1] == "setattr" and len(sub.args) > 2 and isinstance(
                sub.args[1], ast.Constant) and sub.args[1].value == "status" \
                and _is_pending(sub.args[2], values):
            out.append(f"{mod}:{sub.lineno} setattr")
        if chain[-1] in READS:
            continue
        if "status" in kw and _is_pending(kw["status"], values):
            out.append(f"{mod}:{sub.lineno} {'.'.join(chain)}(status=pending)")
        defaults = kw.get("defaults")
        if isinstance(defaults, ast.Dict):
            for k, v in zip(defaults.keys, defaults.values):
                if isinstance(k, ast.Constant) and k.value == "status" and \
                        _is_pending(v, values):
                    out.append(f"{mod}:{sub.lineno} defaults status=pending")
        if word == "pending" and (
                chain == ["OrcWake"] or chain[-3:] == ["OrcWake", "objects",
                                                       "create"]) \
                and "status" not in kw:
            out.append(f"{mod}:{sub.lineno} an OrcWake with the model's "
                       f"default status (pending)")
    return out


def _values(node):
    """The strings a kind or author expression can take; None when it is
    not a constant, a constants.py name, or a choice of those."""
    from bot_program.orcs import constants as C
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.IfExp):
        a, b = _values(node.body), _values(node.orelse)
        return None if a is None or b is None else a + b
    if isinstance(node, (ast.Name, ast.Attribute)):
        name = chain_of(node)[-1]
        value = getattr(C, name, None)
        if isinstance(value, str) and name.isupper():
            return [value]
    return None


def journal_writes(tree, mod, *, strict) -> list:
    """§1.0 item 5: every journal kind and author written is in
    JOURNAL_KINDS and AUTHORS; `strict` (O2 code): each one is a
    constant, so the check can see it."""
    from bot_program.orcs.constants import AUTHORS, JOURNAL_KINDS
    out = []
    for sub in ast.walk(tree):
        if not isinstance(sub, ast.Call):
            continue
        chain = chain_of(sub.func)
        kw = {k.arg: k.value for k in sub.keywords if k.arg}
        if chain[-2:] == ["journal", "append"] or (
                mod == "journal" and chain == ["append"]):
            kind = sub.args[1] if len(sub.args) > 1 else kw.get("kind")
            author = kw.get("author", ast.Constant("code"))
        elif chain[-3:] == ["OrcJournal", "objects", "create"] or \
                chain == ["OrcJournal"]:
            if mod == "journal" and not strict:
                continue        # append's own create: its caller's values
            kind, author = kw.get("kind"), kw.get("author",
                                                  ast.Constant("code"))
        else:
            continue
        for what, node, allowed in (("kind", kind, JOURNAL_KINDS),
                                    ("author", author, AUTHORS)):
            vals = _values(node) if node is not None else None
            if vals is None:
                if strict:
                    out.append(f"{mod}:{sub.lineno} a {what} the check "
                               f"cannot read")
                continue
            out += [f"{mod}:{sub.lineno} {what} {v!r}" for v in vals
                    if v not in allowed]
    return out


# ── outside the package ───────────────────────────────────────────────────

SKIP_DIRS = {"venv", ".venv", "env", ".git", "node_modules", "staticfiles",
             "__pycache__", ".claude", "tests", "media"}


@lru_cache(maxsize=1)
def outside_files() -> tuple:
    """Every non-test .py of the tree outside bot_program/orcs."""
    import os
    out = []
    for dirpath, dirs, files in os.walk(BASE):
        rel_dir = Path(dirpath).relative_to(BASE)
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS
                         and (rel_dir / d).parts != ("bot_program", "orcs"))
        for f in sorted(files):
            if f.endswith(".py") and not f.startswith("test"):
                out.append((rel_dir / f).as_posix())
    return tuple(out)


def _absolute(rel, node) -> str:
    """An ImportFrom's module as an absolute dotted path."""
    if not node.level:
        return node.module or ""
    pkg = rel.rsplit("/", 1)[0].split("/") if "/" in rel else []
    pkg = pkg[:len(pkg) - (node.level - 1)] if node.level > 1 else pkg
    return ".".join(pkg + ([node.module] if node.module else []))


def package_imports(rel, tree) -> list:
    """(file, definition, module, name) of every import of the package."""
    out = []
    for node, scope in scoped(tree):
        if isinstance(node, ast.ImportFrom):
            mod = _absolute(rel, node)
            for a in node.names:
                full = f"{mod}.{a.name}"
                if mod == "bot_program.orcs" or mod.startswith(
                        "bot_program.orcs.") or full == "bot_program.orcs":
                    out.append((rel, scope, mod, a.name))
                elif mod == "bot_program.models" and a.name == "OrcIntent":
                    out.append((rel, scope, mod, a.name))
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "bot_program.orcs" or a.name.startswith(
                        "bot_program.orcs."):
                    out.append((rel, scope, a.name, None))
    return out


@lru_cache(maxsize=1)
def all_package_imports() -> tuple:
    out = []
    for rel in outside_files():
        out += package_imports(rel, tree_of(BASE / rel))
    return tuple(out)


def is_order_path(rel) -> bool:
    return any(fnmatch.fnmatch(rel, pat) for pat in ORDER_PATH_FILES)


def reverse_reads(rel, tree) -> list:
    """(g) An attribute through .orc, .orc_leg or .orcs; a string that
    starts "orc__" or names an Orc table; apps.get_model of an Orc table."""
    out = []
    for sub in ast.walk(tree):
        if isinstance(sub, ast.Attribute) and sub.attr in REVERSE:
            out.append(f"{rel}:{sub.lineno} .{sub.attr}")
        elif isinstance(sub, ast.Constant) and isinstance(sub.value, str) and (
                sub.value.startswith("orc__") or "bot_program_orc"
                in sub.value):
            out.append(f"{rel}:{sub.lineno} {sub.value[:40]!r}")
        elif isinstance(sub, ast.Call) and chain_of(sub.func)[-1] == \
                "get_model":
            args = [a.value for a in sub.args if isinstance(a, ast.Constant)]
            if len(args) > 1 and str(args[1]).startswith("Orc"):
                out.append(f"{rel}:{sub.lineno} get_model {args[1]}")
    return out


def order_path_refs_strict(rel, tree, models) -> list:
    """(g) on the order-path files: no Orc reference at all but their
    hooks (the imports (e) checks) and G8's read of the stamp."""
    out = []
    docs = docstrings(tree)
    for node, scope in scoped(tree):
        if isinstance(node, (ast.Name, ast.Attribute)):
            name = node.id if isinstance(node, ast.Name) else node.attr
            if name in models or name in REVERSE:
                out.append(f"{rel}:{node.lineno} {name}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in docs:
            v = node.value
            if v == "orc" and (rel, scope) != ("bot_program/morgul.py",
                                               "_idea_of"):
                out.append(f"{rel}:{node.lineno} 'orc' in {scope or 'module'}")
            if v.startswith("orc__") or "bot_program_orc" in v or \
                    "bot_program.orcs" in v:
                out.append(f"{rel}:{node.lineno} {v[:40]!r}")
    return out + reverse_reads(rel, tree)


def source_hash(mod, name) -> str:
    obj = importlib.import_module(f"bot_program.orcs.{mod}")
    for part in name.split("."):
        obj = getattr(obj, part)
    return hashlib.sha256(inspect.getsource(obj).encode()).hexdigest()


# ── the tests ─────────────────────────────────────────────────────────────

class TheO2CodeIsNamedTests(MindTestCase):

    def test_every_definition_is_o1s_or_named_o2_code(self):
        """A definition the package did not have at ccc824d is O2 code,
        and is named here; every name here is a new definition."""
        for mod, path in package_files():
            now = set(defs_of(tree_of(path)))
            with self.subTest(module=mod):
                if mod in O2_MODULES:
                    self.assertNotIn(mod, O1_DEFS, "an O2 module is new")
                    continue
                self.assertIn(mod, O1_DEFS, "a new module is O2 code: add "
                              "it to O2_MODULES")
                o1 = set(O1_DEFS[mod].split())
                named = set(O2_CODE.get(mod, ()))
                self.assertEqual(now - o1, named,
                                 "every new definition is named O2 code")
                self.assertFalse(named & o1, "O2 code is new code")

    def test_every_named_unit_is_in_the_source(self):
        """Every unit of O2 code the lists name is found, so no rule below
        scans an empty set by mistake."""
        named = {(m, q) for m, qs in O2_CODE.items() for q in qs}
        named |= {(m, "*") for m in O2_MODULES}
        self.assertEqual({(m, q) for m, q, _n in o2_units()}, named)
        self.assertIn(("journal", "orc_lock"), named, "N8's lock is O2 code")


class NoOrderPathTests(MindTestCase):
    """Test item (a)."""

    def test_the_forbidden_names_appear_nowhere_but_their_one_use(self):
        self.assertLessEqual({"_close_trade", "market_order", "_commit",
                              "dispatch_notification", "ai_agents"},
                             FORBIDDEN, "both O1 sets are read")
        for mod, path in package_files():
            with self.subTest(module=mod):
                self.assertEqual(forbidden_names(tree_of(path), mod), [])

    def test_o2_code_calls_nothing_on_the_tick_or_a_broker(self):
        for mod, qual, node in o2_units():
            with self.subTest(unit=f"{mod}.{qual}"):
                self.assertEqual(tick_calls(node), [])

    def test_o2_code_references_no_callable_of_the_order_path(self):
        names = order_path_names()
        self.assertIn("_close_trade", names)
        self.assertIn("execute_kill_switch", names)
        self.assertIn("modify_protective", names)
        self.assertNotIn("plan", names, "the pinned read")
        for mod, qual, node in o2_units():
            with self.subTest(unit=f"{mod}.{qual}"):
                self.assertEqual(order_path_refs(node), [])


class TheModelIsReachedFromOneModuleTests(MindTestCase):
    """Test item (b): only mind_gateway.py names the provider."""

    def test_no_module_but_the_gateway_names_the_provider(self):
        for mod, path in package_files():
            with self.subTest(module=mod):
                self.assertEqual(model_reach(tree_of(path), mod), [])


class NoTradeRowWriteTests(MindTestCase):
    """Test item (c)."""

    def test_no_trade_row_write_but_the_stamps_two_writers(self):
        for mod, path in package_files():
            with self.subTest(module=mod):
                self.assertEqual(trade_row_writes(tree_of(path), mod), [])

    def test_the_stamps_writers_write_the_stamp_only(self):
        """Both sit under the row's lock and save metadata alone."""
        for mod, qual in TRADE_WRITERS:
            src = inspect.getsource(getattr(importlib.import_module(
                f"bot_program.orcs.{mod}"), qual))
            with self.subTest(f"{mod}.{qual}"):
                self.assertIn("AssetBotTrade.objects.select_for_update()", src)
                self.assertIn('save(update_fields=["metadata"])', src)
                self.assertIn('["orc"] = {', src)


class NothingWithPowerTests(MindTestCase):
    """Test item (d) and A.45b, in O2 code."""

    def test_o2_code_writes_nothing_with_power(self):
        for mod, qual, node in o2_units():
            with self.subTest(unit=f"{mod}.{qual}"):
                self.assertEqual(power_writes(node), [])

    def test_o2_code_never_writes_into_the_ticks_objects(self):
        for mod, qual, node in o2_units():
            with self.subTest(unit=f"{mod}.{qual}"):
                self.assertEqual(tick_object_writes(node), [])


class TheImportersAreFrozenTests(MindTestCase):
    """Test items (e) and (f)."""

    def test_the_importers_outside_the_package_are_frozen(self):
        importers = {rel for rel, *_ in all_package_imports()}
        self.assertGreater(len(outside_files()), 400, "the scan reads the "
                           "tree")
        self.assertEqual(importers - FROZEN_IMPORTERS - NAMED_BY_THE_SPEC,
                         set(), "a new importer of the Orcs")

    def test_the_order_path_imports_its_hooks_only_at_their_sites(self):
        found = {(rel, scope, mod, name)
                 for rel, scope, mod, name in all_package_imports()
                 if is_order_path(rel)}
        self.assertEqual(found, HOOKS)
        self.assertIn(RECEIVER, set(all_package_imports()))

    def test_the_receiver_is_tied_to_every_trade_row_save(self):
        from django.db.models.signals import post_save
        uids = [key[0] for key, *_rest in post_save.receivers]
        self.assertEqual(uids.count("orcs_leg_closed"), 1)
        from bot_program.models import AssetBotTrade
        from bot_program.orcs import lifecycle
        self.assertIn(lifecycle._leg_saved, [
            r for r in post_save._live_receivers(AssetBotTrade)[0]])

    def test_only_the_surfaces_import_what_a_model_wrote(self):
        for rel, scope, mod, name in all_package_imports():
            parts = set(mod.split(".")) | {name}
            if not parts & SURFACE_ONLY or rel in SURFACES:
                continue
            with self.subTest(f"{rel}: {mod}.{name}"):
                self.assertEqual((rel, name), REGISTRY)


class NoReverseAccessorTests(MindTestCase):
    """Test item (g)."""

    def test_no_reverse_accessor_read_outside_the_surfaces(self):
        hits = []
        for rel in outside_files():
            if rel in SURFACES or "/migrations/" in f"/{rel}":
                continue
            hits += reverse_reads(rel, tree_of(BASE / rel))
        self.assertEqual(hits, [])

    def test_the_order_path_has_no_orc_reference_but_its_hooks(self):
        from django.apps import apps
        models = {m.__name__ for m in apps.get_app_config(
            "bot_program").get_models()
            if m.__module__ == "bot_program.orcs.models"}
        self.assertIn("Orc", models)
        hits = []
        for rel in outside_files():
            if is_order_path(rel):
                hits += order_path_refs_strict(rel, tree_of(BASE / rel),
                                               models)
        self.assertEqual(hits, [])


class TheFrozenO1FunctionsTests(MindTestCase):
    """Test item (h)."""

    def test_the_frozen_functions_are_as_o2a_leaves_them(self):
        for (mod, name), digest in FROZEN_SOURCES.items():
            with self.subTest(f"{mod}.{name}"):
                self.assertEqual(source_hash(mod, name), digest)

    def test_the_lock_changes_are_the_only_ones(self):
        """O2a's change to the frozen functions is N8's lock and nothing
        else: the Orc's lock through journal.orc_lock, the close and the
        kill switch under the money paths' budget."""
        from bot_program.orcs import lifecycle
        close = inspect.getsource(lifecycle._close_leg)
        self.assertIn("orc = journal.orc_lock(leg.orc_id)", close)
        self.assertNotIn("select_for_update", close)
        kill = inspect.getsource(lifecycle.kill_all)
        self.assertIn("journal.lock_budget(ORC_LOCK_MONEY_MS)", kill)
        self.assertIn("locked = journal.orc_lock(orc.pk)", kill)
        quiet = inspect.getsource(lifecycle._closed_quietly)
        self.assertIn("journal.lock_budget(ORC_LOCK_MONEY_MS)", quiet)


class PendingAndJournalTests(MindTestCase):
    """A.3 and §1.0 item 5."""

    def test_pending_is_written_by_scheduler_py_only(self):
        for mod, path in package_files():
            with self.subTest(module=mod):
                self.assertEqual(pending_writes(tree_of(path), mod), [])

    def test_merged_is_written_by_scheduler_py_only(self):
        """A.7: the render pass merges through scheduler.absorb, which
        wake.py imports inside render_queued only."""
        for mod, path in package_files():
            with self.subTest(module=mod):
                self.assertEqual(pending_writes(tree_of(path), mod,
                                                word="merged"), [])
        writes = pending_writes(tree_of(PKG / "scheduler.py"), "absorb",
                                word="merged")
        self.assertTrue(writes, "the merge writes `merged` in scheduler.py")
        self.assertTrue(pending_writes(tree_of(PKG / "scheduler.py"),
                                       "admit"),
                        "admission writes `pending` in scheduler.py")

    def test_every_journal_kind_and_author_is_allowed(self):
        o2 = {mod for mod, _q, _n in o2_units()}
        for mod, path in package_files():
            with self.subTest(module=mod):
                self.assertEqual(journal_writes(tree_of(path), mod,
                                                strict=False), [])
        for mod, qual, node in o2_units():
            with self.subTest(unit=f"{mod}.{qual}"):
                self.assertEqual(journal_writes(node, mod, strict=True), [])
        self.assertTrue(o2, "O2 code exists to be checked")


class TheRulesCanFailTests(MindTestCase):
    """Each rule on a planted violation and on its clean twin."""

    def _fn(self, src):
        return ast.parse(inspect.cleandoc(src)).body[0]

    def test_a_forbidden_name_is_found(self):
        tree = ast.parse("def f(bot):\n    bot._close_trade(1)\n")
        self.assertEqual(len(forbidden_names(tree, "ghost")), 1)
        ok = ast.parse("def notify_adopted():\n    dispatch_notification()\n")
        self.assertEqual(forbidden_names(ok, "birth"), [])
        self.assertEqual(len(forbidden_names(ok, "wake")), 1)

    def test_a_call_on_the_tick_is_found(self):
        bad = self._fn("""
            def f(bot, env):
                bot.cfg
                cache = getattr(bot, "_tick_broker_cache", None)
                cache.get("x")
                cache["client"].market_order(1)
                env.bot.send()
                getattr(bot, "_close_trade")(1)
            """)
        self.assertEqual(len(tick_calls(bad)), 3, tick_calls(bad))
        ok = self._fn("""
            def f(bot):
                bot._tick_broker_cache.get("orcs:on")
                getattr(bot, "cfg", None)
            """)
        self.assertEqual(tick_calls(ok), [])

    def test_an_order_path_reference_is_found(self):
        bad = self._fn("""
            def f(x):
                from bot_program.engine import kill_switch
                from bot_program.position_care import care
                x._manage_broker_stop(1)
            """)
        self.assertEqual(len(order_path_refs(bad)), 3, order_path_refs(bad))
        ok = self._fn("""
            def f(x):
                from bot_program.position_care import plan
                x.get("a")
            """)
        self.assertEqual(order_path_refs(ok), [])

    def test_a_model_reach_is_found(self):
        for src in ("import ai_agents\n", "x = 'ai_agents.spend'\n",
                    "importlib.import_module('ai_agents')\n",
                    "can_spend(line='orcs')\n",
                    "def f():\n    count_tokens()\n"):
            with self.subTest(src):
                self.assertTrue(model_reach(ast.parse(src), "wake"))
        doc = ast.parse('"""This module names ai_agents in prose."""\n')
        self.assertEqual(model_reach(doc, "wake"), [])
        self.assertEqual(model_reach(ast.parse("import ai_agents\n"),
                                     GATEWAY), [])

    def test_a_trade_row_write_is_found(self):
        src = inspect.cleandoc("""
            def f(pk, row):
                rows = AssetBotTrade.objects.filter(pk=pk)
                rows.update(stop_loss=1)
                AssetBotTrade.objects.filter(pk=pk).update(qty=0)
                meta = dict(row.metadata or {})
                meta.update({"a": 1})
            """)
        self.assertEqual(len(trade_row_writes(ast.parse(src), "intents")), 2)
        exempt = ast.parse(src.replace("def f(", "def _restamp("))
        self.assertEqual(trade_row_writes(exempt, "census"), [])
        self.assertEqual(len(trade_row_writes(exempt, "intents")), 2)

    def test_a_power_write_is_found(self):
        bad = self._fn("""
            def f(pk, row):
                locked = journal.orc_lock(pk)
                locked.stop_level = 1
                Orc.objects.filter(pk=pk).update(commission="trail")
                orc.seat.level = 2
                OrcSeat.objects.filter(pk=pk).update(pinned=True)
                journal.append(orc, "fact", "x", fields={"stood_down": True})
                row.metadata["orc_exit"] = {}
                meta.update({"care": {}})
                orc.save(update_fields=["trail_owner"])
            """)
        self.assertEqual(len(power_writes(bad)), 8, power_writes(bad))
        ok = self._fn("""
            def f(pk, wake):
                locked = journal.orc_lock(pk)
                locked.plan = {}
                wake.status = "done"
                journal.append(orc, "plan", "x", fields={"plan_version": 2})
                track.state["orc_stop"] = 1
            """)
        self.assertEqual(power_writes(ok), [])

    def test_a_write_into_the_ticks_objects_is_found(self):
        bad = self._fn("""
            def f(trade, env, bot):
                trade.stop_loss = 1
                env.ctx["event"] = None
                meta = trade.metadata if trade.metadata else {}
                meta["x"] = 1
                care = meta.get("care")
                care.update({"a": 1})
                del trade.metadata["y"]
                setattr(bot, "x", 1)
                trade.save()
            """)
        self.assertEqual(len(tick_object_writes(bad)), 7,
                         tick_object_writes(bad))
        ok = self._fn("""
            def f(trade, env):
                meta = dict(trade.metadata or {})
                meta["x"] = 1
                ctx = dict(env.ctx)
                ctx.pop("event", None)
                seen = copy.deepcopy(trade.metadata)
                seen.update({"a": 1})
                price = trade.metadata.get("care", {}).get("peak")
            """)
        self.assertEqual(tick_object_writes(ok), [])

    def test_a_pending_write_is_found(self):
        bad = ast.parse(inspect.cleandoc("""
            def f(w, orc):
                w.status = "pending"
                OrcWake.objects.filter(pk=1).update(status="pending")
                OrcWake.objects.create(orc=orc, dedupe_key="k")
                w.status, w.skipped_reason = WAKE_STATUS_PENDING, ""
            """))
        self.assertEqual(len(pending_writes(bad, "wake")), 4)
        self.assertEqual(pending_writes(bad, PENDING_WRITER), [])
        ok = ast.parse("OrcWake.objects.filter(status='pending').count()\n")
        self.assertEqual(pending_writes(ok, "wake"), [])
        merged = ast.parse(inspect.cleandoc("""
            def f(w):
                w.status = WAKE_STATUS_MERGED
                OrcWake.objects.filter(pk=1).update(status="merged")
            """))
        self.assertEqual(len(pending_writes(merged, "wake", word="merged")),
                         2)
        self.assertEqual(pending_writes(merged, PENDING_WRITER,
                                        word="merged"), [])

    def test_a_journal_kind_outside_the_tuples_is_found(self):
        bad = ast.parse(inspect.cleandoc("""
            def f(orc, kind):
                journal.append(orc, "musing", "x")
                journal.append(orc, "fact", "x", author="model")
                journal.append(orc, kind, "x")
            """))
        self.assertEqual(len(journal_writes(bad, "wake", strict=False)), 2)
        self.assertEqual(len(journal_writes(bad, "wake", strict=True)), 3)
        ok = ast.parse("journal.append(orc, 'budget', 'x', author='code')\n")
        self.assertEqual(journal_writes(ok, "wake", strict=True), [])

    def test_a_new_importer_and_a_reverse_read_are_found(self):
        tree = ast.parse(inspect.cleandoc("""
            from bot_program.orcs.scheduler import admit
            from bot_program.models import OrcIntent
            def f(trade):
                return trade.orc.state, trade.orc_leg, "orc__state"
            """))
        found = package_imports("dashboard/new_page.py", tree)
        self.assertEqual({(m, n) for _r, _s, m, n in found},
                         {("bot_program.orcs.scheduler", "admit"),
                          ("bot_program.models", "OrcIntent")})
        self.assertEqual(len(reverse_reads("dashboard/new_page.py", tree)), 3)
        rel = package_imports("bot_program/x.py", ast.parse(
            "from .orcs import lifecycle\n"))
        self.assertEqual(rel, [("bot_program/x.py", "", "bot_program.orcs",
                                "lifecycle")])

    def test_a_changed_frozen_function_changes_its_hash(self):
        from bot_program.orcs import lifecycle
        src = inspect.getsource(lifecycle.kill_all)
        self.assertNotEqual(hashlib.sha256(src.encode()).hexdigest(),
                            hashlib.sha256((src + " ").encode()).hexdigest())
        self.assertEqual(source_hash("lifecycle", "kill_all"),
                         hashlib.sha256(src.encode()).hexdigest())
