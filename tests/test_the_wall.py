"""The Wall's 2026-09-12 sections: the desk, the allocator, Horizon, the
personalities and the evidence spine.

tests/test_landing_page.py already guards the page as it stood before this
chantier — the anchors, the ticker, the absence of invented quotes. This
module guards the five sections added on 2026-09-12 and, more importantly,
the two rules they had to be written under:

  1. EVERY NUMBER IS COUNTED. A new claim on this page is either a value
     out of ``core.wall_facts`` or a sentence with no number in it. The
     tests below render the page against a seeded database and demand the
     counted value back, then render it against an empty one and demand it
     still serve — because a landing page that 500s when a table is empty
     is worse than a landing page that says nothing.

  2. NOTHING OVERCLAIMS. The capital desk and the share allocator are in
     SHADOW: they propose, they grade themselves against the counterfactual,
     and they have never moved money. The page is allowed to be impressive
     about that and is not allowed to be impressive about anything else, so
     the word SHADOW is pinned in the desk section and the phrases that
     would sell autonomy are pinned as absent.

The "existing headings survive" test is the one that makes this module
worth its runtime: five sections were spliced into a 4,138-line template by
anchor, and a mis-anchored splice that swallowed a neighbouring section
would otherwise pass every other assertion in this file.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import TestCase

from core import wall_facts as wf


# The exact keys the 2026-09-12 sections render. Each one must reach the
# page as its counted value — not a literal, not a rounded "over N".
NEW_WALL_KEYS = [
    "desk_plans",
    "desk_decisions_graded",
    "share_plans",
    "agent_calls_graded",
    "components",
    "shell_commands",
    "rules_governed",
]

# Headings that existed BEFORE this chantier, by their exact rendered text.
# If a splice ate one of them, this is what says so.
PRE_EXISTING_HEADINGS = [
    "A Closed-Loop Intelligence Engine",
    "From Tick to Trade to Truth",
    "Feel the Orchestrator",
    "One Screen. Everything Moving.",
    "Decay Is the Trigger.",
    "One Adapter Pattern.<br>One Venue per Class.",
    "Interrogate Your<br>Own Machine.",
    "Production-Hardened",
]

# Sentences this page must never be able to say. The platform's character
# is that it refuses to flatter itself; these are the flattering versions
# of exactly what the new sections describe.
FORBIDDEN_CLAIMS = [
    "allocates your capital",
    "trades your account",
    "in real time across markets",
    "fully autonomous",
    "no human needed",
    "hands-free",
]


def _clear_cache():
    """wall_facts() caches for five minutes — a test that seeds rows after
    another test warmed the cache would otherwise assert against the other
    test's numbers."""
    from django.core.cache import cache
    cache.delete(wf.CACHE_KEY)


class WallNewSectionsRenderTests(TestCase):
    """The five sections are on the page, in the page's own idiom."""

    def setUp(self):
        _clear_cache()
        self.response = self.client.get("/wall/")
        self.body = self.response.content.decode("utf-8", errors="ignore")

    def test_the_wall_still_serves_anonymously(self):
        self.assertEqual(self.response.status_code, 200)

    def test_every_new_section_has_its_anchor(self):
        for anchor in ('id="personas"', 'id="desk"', 'id="shares"',
                       'id="horizon"', 'id="spine"'):
            self.assertIn(anchor, self.body, f"missing section {anchor}")

    def test_every_new_section_has_its_heading(self):
        for heading in ("Three Ways to Hold a Thesis.",
                        "Every Candidate Seen",
                        "Re-Split on Evidence.",
                        "The Only Agent",
                        "Nothing Here Grades"):
            self.assertIn(heading, self.body, f"missing heading {heading!r}")

    def test_the_desk_section_names_what_it_does(self):
        self.assertIn("CAPITAL_DESK", self.body)
        self.assertIn("marginal", self.body.lower())
        self.assertIn("Candidate Ladder", self.body)
        self.assertIn("DISPLACED", self.body)
        self.assertIn("TAKEN", self.body)

    def test_the_allocator_section_names_what_it_does(self):
        self.assertIn("SHARE_ALLOCATOR", self.body)
        self.assertIn("drawdown governor", self.body)
        self.assertIn("share-bar", self.body)

    def test_the_horizon_section_dates_its_own_grading(self):
        """Its calls are graded at six and twelve months, and the first of
        them resolve in 2027 — which is the whole of what this page is
        allowed to say about how right Horizon has been."""
        self.assertIn("six and twelve months", self.body)
        self.assertIn("2027", self.body)
        self.assertIn("SECTOR HORIZON", self.body)

    def test_the_personalities_section_is_the_three_presets(self):
        for label in ("Scalp", "Swing", "Position"):
            self.assertIn(label, self.body)
        # The preset is a preset, not a new engine — and never a loan.
        self.assertIn("not a new engine", self.body)
        self.assertIn("No personality borrows to fund a position", self.body)

    def test_the_spine_section_ties_the_engines_together(self):
        self.assertIn("The Evidence Spine", self.body)
        self.assertIn("gradable call", self.body)
        self.assertIn("counterfactual", self.body)

    def test_new_sections_reuse_the_pages_own_shell(self):
        """A section that looks foreign to this page is a failure even when
        every word in it is true. Each new one uses the existing section
        shell, the existing reveal system and the existing panel frame."""
        for anchor in ('id="personas"', 'id="desk"', 'id="shares"',
                       'id="horizon"', 'id="spine"'):
            idx = self.body.index(anchor)
            head = self.body[idx - 200:idx]
            self.assertIn('class="wall-section"', head,
                          f"{anchor} is not a .wall-section")
        for marker in ("section-label", "section-title", "reveal delay-1",
                       "pillar-row", "ops-frame", "new-pill", "check-list"):
            self.assertIn(marker, self.body)

    def test_new_sections_invent_no_twenty_first_animation(self):
        """They animate on keyframes the file already owned."""
        for kf in ("@keyframes logRowIn", "@keyframes themeFill",
                   "@keyframes pipeFlow", "@keyframes liveBlink",
                   "@keyframes pillarFlow"):
            self.assertIn(kf, self.body)
        # Exactly the animation names the page had, plus nothing.
        for invented in ("@keyframes deskFill", "@keyframes shareSplit",
                         "@keyframes horizonDrift", "@keyframes personaPulse"):
            self.assertNotIn(invented, self.body)

    def test_the_added_motion_honours_reduced_motion(self):
        idx = self.body.index("@media (prefers-reduced-motion: reduce)")
        block = self.body[idx:self.body.index("</style>", idx)]
        for sel in (".desk-row", ".desk-budget-fill", ".share-seg"):
            self.assertIn(sel, block,
                          f"{sel} animates with no reduced-motion guard")

    def test_stilling_the_desk_ladder_does_not_erase_it(self):
        """The bug this test exists for (2026-09-12 review).

        `.desk-row` ENTERS on logRowIn from `opacity: 0`, so listing it in
        the reduced-motion block under a bare `animation: none` left all
        five candidate rows — the entire visual of the desk section, the
        one picture of the thing the section is about — permanently
        invisible to every visitor who had asked for less motion. The
        markup was there, so every other assertion in this file passed.
        The guard has to restore the animation's END STATE by hand; that
        is also why `.demo-log-row`, which rides the same keyframe, was
        never added to that block in the first place.
        """
        idx = self.body.index("@media (prefers-reduced-motion: reduce)")
        block = self.body[idx:self.body.index("</style>", idx)]
        # The selector WITH its brace: the explanatory comment beside the
        # rule also contains the bare string ".desk-row".
        rule_at = block.index(".desk-row {")
        rule = block[rule_at:block.index("}", rule_at)]
        self.assertIn("opacity: 1", rule,
                      ".desk-row is stilled at opacity 0 — the ladder is "
                      "invisible under prefers-reduced-motion")
        self.assertIn("transform: none", rule,
                      ".desk-row is stilled mid-slide under "
                      "prefers-reduced-motion")

    def test_the_new_anchors_are_reachable(self):
        """Two in the nav; the rest through in-copy links, which is how
        #evolution has always been reached."""
        self.assertIn('href="#desk"', self.body)
        self.assertIn('href="#horizon"', self.body)
        self.assertIn('href="#shares"', self.body)
        self.assertIn('href="#spine"', self.body)

    def test_no_new_section_pulls_an_external_asset(self):
        """The page loads exactly one third-party thing — the Google font
        link that was already in <head>. Nothing added on 2026-09-12 may
        reach off this deployment: the wall is the login gateway, and a CDN
        on it is a third party watching every visitor arrive."""
        for anchor in ('id="personas"', 'id="desk"', 'id="shares"',
                       'id="horizon"', 'id="spine"'):
            start = self.body.index(anchor)
            end = self.body.index("</section>", start)
            block = self.body[start:end]
            for scheme in ("http://", "https://", "//cdn", "src=\"//"):
                self.assertNotIn(
                    scheme, block,
                    f"section {anchor} reaches an external host")

    def test_the_pre_existing_sections_all_survived_the_splice(self):
        for heading in PRE_EXISTING_HEADINGS:
            self.assertIn(heading, self.body,
                          f"a pre-existing heading vanished: {heading!r}")
        for anchor in ('id="platform"', 'id="signals"', 'id="agents"',
                       'id="pipeline"', 'id="demo"', 'id="operations"',
                       'id="fleet"', 'id="evolution"', 'id="mind"',
                       'id="research"', 'id="brokers"', 'id="trust"',
                       'id="technology"'):
            self.assertIn(anchor, self.body,
                          f"a pre-existing section vanished: {anchor}")

    def test_the_template_still_parses_as_one_document(self):
        self.assertEqual(self.body.count("<section"),
                         self.body.count("</section>"))
        self.assertTrue(self.body.rstrip().endswith("</html>"))
        # An unrendered tag means a typo'd variable name reached the page.
        self.assertNotIn("{{", self.body)
        self.assertNotIn("{%", self.body)


class WallNewNumbersAreCountedTests(TestCase):
    """Every number the new sections show is a count from the database (or
    an in-process registry), handed over in the `wall` context. None of them
    is typed into the template — that is the failure this whole contract
    exists to prevent."""

    def setUp(self):
        _clear_cache()
        self.response = self.client.get("/wall/")
        self.body = self.response.content.decode("utf-8", errors="ignore")

    def test_the_view_hands_over_every_new_key(self):
        wall = self.response.context["wall"]
        for key in NEW_WALL_KEYS:
            self.assertIn(key, wall, f"wall context is missing {key!r}")
            self.assertIsInstance(
                wall[key], int,
                f"wall.{key} must be an aggregate count, got {wall[key]!r}")
            self.assertGreaterEqual(wall[key], 0)

    def test_every_new_key_reaches_the_page_as_its_counted_value(self):
        wall = self.response.context["wall"]
        for key in NEW_WALL_KEYS:
            self.assertIn(
                f'data-target="{wall[key]}"', self.body,
                f"wall.{key} is not rendered anywhere on the page")

    def test_no_count_up_target_is_a_literal_or_empty(self):
        """Every count-up on the page — old and new — resolves to a number.
        An empty one means a context key was dropped and the counter would
        animate to NaN in front of a visitor."""
        import re
        targets = re.findall(r'data-target="([^"]*)"', self.body)
        self.assertTrue(targets)
        for t in targets:
            self.assertRegex(t, r"^\d+$")

    def test_seeded_rows_show_up_on_the_page(self):
        """The counted-ness of these numbers, demonstrated rather than
        asserted: seed one row of something the new sections count, and the
        rendered page moves."""
        from core.platform_control import PlatformComponent

        before = self.response.context["wall"]["components"]
        PlatformComponent.objects.create(
            name="wall_probe_component", is_enabled=True)
        _clear_cache()
        r = self.client.get("/wall/")
        body = r.content.decode("utf-8", errors="ignore")
        after = r.context["wall"]["components"]
        self.assertEqual(after, before + 1)
        self.assertIn(f'data-target="{after}"', body)

    def test_the_shell_command_count_is_the_registry_length(self):
        """Not a number typed beside the cockpit copy: the catalogue's own
        length, so it cannot drift from the commands that actually exist."""
        wall = self.response.context["wall"]
        try:
            from core.ops_commands import COMMANDS
        except Exception:  # noqa: BLE001 — fenced exactly like _count_shell_commands
            self.skipTest("core.ops_commands not importable in this tree")
        self.assertEqual(wall["shell_commands"], len(COMMANDS))
        self.assertIn(f'data-target="{len(COMMANDS)}"', self.body)


class WallSurvivesAnEmptyDatabaseTests(TestCase):
    """A fresh install has no desk plans, no share plans and no graded agent
    calls. The page must still serve, and must not dress the zeros up as
    anything."""

    def setUp(self):
        _clear_cache()
        # Belt and braces: this class runs on the empty per-test database,
        # but a counter that silently found rows would make the assertions
        # below meaningless rather than failing them.
        from bot_program.desk_models import DeskDecision, DeskPlan
        from bot_program.share_models import SharePlan
        DeskDecision.objects.all().delete()
        DeskPlan.objects.all().delete()
        SharePlan.objects.all().delete()
        _clear_cache()
        self.response = self.client.get("/wall/")
        self.body = self.response.content.decode("utf-8", errors="ignore")

    def test_it_renders_200_with_nothing_to_count(self):
        self.assertEqual(self.response.status_code, 200)

    def test_the_engine_counts_are_zero_and_rendered_as_zero(self):
        wall = self.response.context["wall"]
        for key in ("desk_plans", "desk_decisions_graded", "share_plans",
                    "agent_calls_graded"):
            self.assertEqual(wall[key], 0, f"wall.{key} counted something")
        self.assertIn('data-target="0"', self.body)

    def test_the_sections_still_stand_with_nothing_counted(self):
        """The copy carries the sections; the numbers only decorate them. A
        zero must never take a heading down with it."""
        for anchor in ('id="personas"', 'id="desk"', 'id="shares"',
                       'id="horizon"', 'id="spine"'):
            self.assertIn(anchor, self.body)
        self.assertIn("SHADOW", self.body)

    def test_zero_is_never_narrated_as_a_result(self):
        """With nothing counted the page must not claim performance. These
        are the sentences a zero would turn into a lie."""
        low = self.body.lower()
        for claim in ("proven", "outperform", "profitable since",
                      "track record of returns", "beats the market"):
            self.assertNotIn(claim, low, f"the wall is claiming {claim!r}")


class WallDoesNotOverclaimTests(TestCase):
    """The one rule that outranks the rest of this chantier. The desk and
    the allocator propose, grade themselves, and have never moved money;
    the page says exactly that and never more."""

    def setUp(self):
        _clear_cache()
        self.body = self.client.get("/wall/").content.decode(
            "utf-8", errors="ignore")

    def test_the_word_shadow_is_in_the_desk_section(self):
        start = self.body.index('id="desk"')
        end = self.body.index("</section>", start)
        self.assertIn("SHADOW", self.body[start:end],
                      "the desk section does not say it is in shadow")

    def test_the_page_says_the_engines_are_not_trusted_with_the_account(self):
        # Matched on the fragments that sit within one source line: the
        # template wraps its prose, so asserting a whole sentence here would
        # fail on a reflow that changed nothing a visitor can see.
        #
        # These are the PERMANENT forms (2026-09-12 review). "The desk has
        # never placed an order" was a claim about history; "the desk places
        # no orders" is a claim about the module, which capital_desk.py backs
        # in both modes: nothing there calls a broker, and `size_mult` is
        # never above 1.0. The history half is now counted — see
        # WallShadowClaimsAreCountedNotTypedTests below.
        self.assertIn("places no orders", self.body)
        self.assertIn("moves no share by", self.body)
        self.assertIn("has been trusted with the account", self.body)

    def test_the_allocator_section_says_a_plan_moves_nothing(self):
        start = self.body.index('id="shares"')
        end = self.body.index("</section>", start)
        block = self.body[start:end]
        self.assertIn("Nothing Moves", block)
        self.assertIn("PIN", block)

    def test_none_of_the_flattering_versions_appear(self):
        low = self.body.lower()
        for claim in FORBIDDEN_CLAIMS:
            self.assertNotIn(claim, low,
                             f"the wall overclaims: {claim!r}")

    def test_the_comments_in_the_new_sections_ship_to_the_reader_too(self):
        """Django does not strip HTML comments, so a note left for the next
        maintainer is served to every visitor. The first draft of the
        personalities comment quoted the retired "667 tests green" literal to
        explain what it was avoiding — and put that exact string back on the
        public page, where tests/test_landing_page caught it. The lesson is
        pinned here, beside the sections that learned it (2026-09-12)."""
        self.assertNotIn("667", self.body)

    def test_no_persona_claim_outruns_what_personas_py_actually_sets(self):
        """Found in review, 2026-09-12.

        The page said the long-horizon personality was "the only personality
        the five-to-ten-year view is allowed to lean on" — three inches below
        its own swing card, which correctly lists a "light" horizon prior.
        `personas.SWING.horizon_weight` is 0.5: a real, half-strength prior.
        The page was contradicting itself on one screen, and the stronger of
        the two statements was the false one.
        """
        try:
            from bot_program.personas import PERSONAS
        except Exception:  # noqa: BLE001 — the section is written either way
            self.skipTest("bot_program.personas not importable in this tree")

        self.assertNotIn("only personality", self.body.lower())
        self.assertNotIn("only the long-horizon personality", self.body.lower())
        # And the claim the page makes instead is the one the module backs:
        # position leads, swing feels it at half weight, scalp not at all.
        self.assertGreater(PERSONAS["position"].horizon_weight,
                           PERSONAS["swing"].horizon_weight)
        self.assertGreater(PERSONAS["swing"].horizon_weight, 0.0)
        self.assertEqual(PERSONAS["scalp"].horizon_weight, 0.0)
        self.assertIn("half weight", self.body)

    def test_the_page_does_not_claim_the_codebase_has_no_margin_knob(self):
        """Found in review, 2026-09-12 — the flattest falsifiable sentence
        this chantier put on the page.

        It read: "There is no margin knob anywhere in this code and no config
        field that asks for one." `bot_program.models.BotConfig` carries BOTH
        `leverage` and `margin_mode` (choices: isolated / cross);
        `bot_program/engine/risk.py` multiplies the position dollars by
        `self.c.leverage`; `engine/runner.py` pushes `cfg.leverage` and
        `cfg.margin_mode` at the Binance futures venue through
        `ensure_config`, which POSTs /fapi/v1/leverage and
        /fapi/v1/marginType. The sentence was lifted from personas.py's own
        docstring, where it is scoped to what a PERSONA sets — true there,
        false the moment it is generalised to "this code" on a public page.

        The true claim, and the one the page makes now: no persona sets
        either knob. That is not a hedge, it is stronger — the configs a
        personality can be worn by (`AssetBotConfig`) do not carry the
        fields at all.
        """
        from bot_program.models import AssetBotConfig, BotConfig

        knobs = {"leverage", "margin_mode"}
        self.assertTrue(
            knobs & {f.name for f in BotConfig._meta.get_fields()},
            "if these fields are gone, revisit this test AND the wall's "
            "wording — do not just delete the assertion")
        self.assertFalse(
            knobs & {f.name for f in AssetBotConfig._meta.get_fields()},
            "a personality-wearing config grew a leverage knob — the wall "
            "now says no personality has one")
        low = self.body.lower()
        self.assertNotIn("no margin knob anywhere", low)
        self.assertNotIn("no config field that asks for one", low)
        self.assertNotIn("this platform never borrows", low)
        # Scoped to the personalities, which is where it is true.
        self.assertIn("No personality borrows to fund a position", self.body)
        try:
            from bot_program.personas import PERSONAS
        except Exception:  # noqa: BLE001
            return
        for persona in PERSONAS.values():
            for knob in ("leverage", "margin_mode", "margin"):
                self.assertIsNone(
                    persona.knob(knob),
                    f"persona {persona.key} sets {knob!r} — the wall now "
                    f"says no personality does")

    def test_no_engine_is_described_as_already_running_everywhere(self):
        """Found in review, 2026-09-12.

        `PlatformComponent.is_enabled` defaults to False and none of
        `pipeline_capital_desk`, `pipeline_share_allocator` or
        `agent_horizon` ships enabled — with the desk pass off,
        `run_all_asset_bots` is the legacy config-after-config loop and the
        desk never sees a candidate. The page nonetheless said the entry
        path IS cut in two, that the allocator proposes several times a day,
        that Horizon writes a view once a month, and — worst — that both
        engines "run on every tick and every schedule". That is the "AI
        allocates your capital in real time" failure in a quieter voice.
        """
        from core.platform_control import DEFAULT_COMPONENTS

        shipped_on = [c["key"] for c in DEFAULT_COMPONENTS
                      if c.get("is_enabled")]
        self.assertEqual(
            shipped_on, [],
            "a component now ships enabled — the wall's 'switch it on' "
            "wording may need to change with it")
        self.assertNotIn("Both run on every tick", self.body)
        # Each of the three sections names the switch rather than assuming it.
        self.assertIn("it ships off", self.body)
        self.assertIn("that switch ships off too", self.body)
        self.assertIn("behind switches that ship off", self.body)
        self.assertIn("Switched on", self.body)  # Horizon's own hedge

    def test_the_duplicate_population_is_declared_not_hidden(self):
        """`rules_governed` and `strategies` count the same table. Rendering
        them as two independent numbers would read as twice the coverage,
        so the page says out loud that they are one population."""
        wall = self.client.get("/wall/").context["wall"]
        self.assertEqual(wall["rules_governed"], wall["strategies"])
        self.assertIn("one population", self.body)


class WallShadowClaimsAreCountedNotTypedTests(TestCase):
    """The review's central repair (2026-09-12).

    The chantier put three sentences on the public page asserting that the
    capital desk has only ever run in shadow, and two SHADOW pills that no
    code could ever take off it:

        "SHADOW is the default and so far the only mode any plan has been
         written in."
        "Orders sent — NONE"
        "The desk has never placed an order."

    Every one of those is a claim about what this deployment has DONE,
    typed into a template. `DeskPlan.mode` records LIVE the moment an
    operator flips `capital_desk_mode_live`, and the page would have gone
    on saying otherwise — which is the "667 tests green" failure exactly,
    with a subject that costs more than a stale number. Same for the
    allocator: `SharePlan.applied_at` is stamped the moment a human applies
    a plan behind the PIN.

    So the sentences now hang off two counts. The tests below seed the
    OTHER side of each switch and demand the page change its mind.
    """

    def setUp(self):
        _clear_cache()

    def _body(self):
        _clear_cache()
        return self.client.get("/wall/").content.decode("utf-8", errors="ignore")

    def _user(self):
        from django.contrib.auth.models import User
        return User.objects.create_user(username="wall_shadow_probe",
                                        password="x")

    # ── The desk ────────────────────────────────────────────────────────

    def test_with_no_live_pass_the_page_says_shadow(self):
        body = self._body()
        start = body.index('id="desk"')
        block = body[start:body.index("</section>", start)]
        self.assertIn("SHADOW", block)
        self.assertIn("Every pass above was written in SHADOW", block)
        self.assertNotIn("obeying the plan", block)

    def test_a_single_live_pass_takes_the_shadow_wording_off_the_page(self):
        """The assertion that would have failed before this repair: seed one
        obeyed pass and the public page must stop claiming there were none."""
        from bot_program.desk_models import DeskPlan

        DeskPlan.objects.create(user=self._user(), venue="live",
                                mode=DeskPlan.MODE_LIVE)

        body = self._body()
        start = body.index('id="desk"')
        block = body[start:body.index("</section>", start)]
        self.assertNotIn("Every pass above was written in SHADOW", block)
        self.assertIn("obeying the plan", block)
        self.assertIn('data-target="1"', block)
        # And the pill stops saying a thing that is no longer so.
        self.assertIn("OBEYED", block)

    def test_the_permanent_desk_claims_survive_a_live_pass(self):
        """What stays true in BOTH modes, because capital_desk.py makes it
        true: the module calls no broker, and `size_mult` is never above
        1.0. These are claims about the code, so they are allowed to be
        typed — and they must not be collateral damage of the repair."""
        from bot_program.desk_models import DeskPlan

        DeskPlan.objects.create(user=self._user(), venue="live",
                                mode=DeskPlan.MODE_LIVE)

        body = self._body()
        self.assertIn("places no orders", body)
        self.assertIn("Orders the desk sends", body)
        self.assertIn("ONLY SHRINK", body)

    def test_the_venue_named_live_is_not_mistaken_for_live_mode(self):
        """`venue` is which book the candidates belong to; `mode` is whether
        the fleet obeyed the plan. An ordinary shadow pass over the live
        book must not read as the desk being let off the leash."""
        from bot_program.desk_models import DeskPlan

        DeskPlan.objects.create(user=self._user(), venue="live",
                                mode=DeskPlan.MODE_SHADOW)

        body = self._body()
        self.assertIn("Every pass above was written in SHADOW", body)

    # ── The allocator ───────────────────────────────────────────────────

    def test_with_no_applied_plan_the_page_says_none_was_applied(self):
        body = self._body()
        start = body.index('id="shares"')
        block = body[start:body.index("</section>", start)]
        self.assertIn("None has ever been applied here", block)
        self.assertIn("SHADOW", block)

    def test_an_applied_plan_takes_that_sentence_off_the_page(self):
        from django.utils import timezone

        from bot_program.share_models import SharePlan

        SharePlan.objects.create(user=self._user(),
                                 state=SharePlan.STATE_APPLIED,
                                 applied_at=timezone.now())

        body = self._body()
        start = body.index('id="shares"')
        block = body[start:body.index("</section>", start)]
        self.assertNotIn("None has ever been applied here", block)
        self.assertIn("have been applied", block)
        self.assertIn("APPLIED", block)

    # ── The spine's closing paragraph ───────────────────────────────────

    def test_the_closing_paragraph_stops_claiming_an_untouched_account(self):
        """The page's single strongest sentence. It must not survive the
        switch it describes being turned on."""
        from bot_program.desk_models import DeskPlan

        before = self._body()
        self.assertIn("has been trusted with the account on this deployment",
                      before)

        DeskPlan.objects.create(user=self._user(), venue="live",
                                mode=DeskPlan.MODE_LIVE)

        after = self._body()
        self.assertNotIn("has been trusted with the account on this deployment",
                         after)
        self.assertIn("turned on by a person who had read", after)

    def test_a_dead_counter_falls_back_to_the_modest_sentence(self):
        """The fence points the safe way. If `desk_live_plans` cannot be
        counted it degrades to 0, which renders SHADOW — the claim that
        under-sells. A fence that degraded toward "the desk is live" would
        be worse than no fence at all."""
        from unittest.mock import patch

        with patch("core.wall_facts._count_desk_live_plans",
                   side_effect=RuntimeError("table gone")):
            body = self._body()

        self.assertEqual(self.client.get("/wall/").status_code, 200)
        self.assertIn("Every pass above was written in SHADOW", body)


class WallClaimsFollowTheCodeTests(TestCase):
    """The 2026-10-08 correction: every claim the page typed that the code
    had since outgrown, pinned by the fragment that replaced it.

    Each sentence a visitor reads here is held to the module that makes it
    true: the broker count to core.wall_facts, the cadences to the beat,
    the debate to trade_debate.py's own shadow-then-binding rule, the
    fleet's sizing to the proving ground, the router's fallback to
    broker_router. Every fragment asserted present or missing sits on ONE
    source line of the template (the reflow rule), so a wrapped paragraph
    cannot make a negative test pass by accident. A typed literal that is
    stale is looked for in the template's source, never in the answer: the
    answer prints the counted value, and a registry that came to hold
    exactly 12 or 6 entries would make the right page fail.
    """

    def setUp(self):
        _clear_cache()
        self.response = self.client.get("/wall/")
        self.body = self.response.content.decode("utf-8", errors="ignore")
        self.wall = self.response.context["wall"]
        self.src = (Path(settings.BASE_DIR) / "templates" / "landing"
                    / "the_wall.html").read_text(encoding="utf-8")

    def _section(self, anchor):
        start = self.body.index(anchor)
        return self.body[start:self.body.index("</section>", start)]

    def test_the_broker_count_is_the_facts_never_a_word(self):
        low = self.src.lower()
        for stale in ("six brokers", "six broker adapters", "6 broker adapters"):
            self.assertNotIn(stale, low, stale)
        self.assertIn("{{ wall.broker_adapters }} broker adapters", self.src)
        self.assertIn(f'{self.wall["broker_adapters"]} broker adapters', self.body)

    def test_the_evaluator_count_is_the_facts_never_a_digit(self):
        self.assertNotIn("12 Evaluators", self.src)
        self.assertNotIn("12 evaluators", self.src)
        self.assertIn(f'{self.wall["evaluators"]} Evaluators.', self.body)

    def test_the_broker_grid_names_the_live_venue_and_the_retired_one(self):
        import re
        self.assertRegex(
            self.body,
            r'<div class="broker-tile live">\s*<div class="broker-name">ETORO</div>')
        self.assertIn("SAXO", self.body)
        self.assertRegex(
            self.body,
            r'<div class="broker-tile">\s*<div class="broker-name">IBKR</div>')
        self.assertNotIn("28 pairs", self.body)
        self.assertIsNone(re.search(r'broker-tile live">\s*<div class="broker-name">IBKR', self.body))

    def test_the_debate_is_not_called_advice(self):
        self.assertNotIn("never gates execution", self.body)
        self.assertNotIn("Four autonomy levels", self.body)
        agents = self._section('id="agents"')
        self.assertIn("Executioner", agents)
        self.assertIn("never raise it", agents)

    def test_the_fleet_promises_only_what_size_by_proof_does(self):
        self.assertNotIn("Nothing Reaches Live", self.body)
        self.assertNotIn("still under the gate", self.body)
        self.assertIn("Full Size Is Earned.", self.body)
        self.assertIn("enters at a quarter", self.body)
        # The quarter is typed twice on this page (#fleet, #safeguards):
        # held here to the size the code gives an unproven rule.
        from backtester.proving import proof
        from signals.promotion_pipeline import SIZE_FACTORS
        self.assertEqual(SIZE_FACTORS["live_small"], 0.25,
                         "rewrite 'enters at a quarter' in #fleet and #safeguards")
        self.assertEqual(proof.REDUCED, SIZE_FACTORS["live_small"])

    def test_the_spine_says_what_this_page_shows_for_a_dead_counter(self):
        self.assertNotIn("with an audit row to show for it", self.body)
        self.assertIn("shows 0, by design", self.body)

    def test_the_shares_pillar_names_the_shock_switch(self):
        shares = self._section('id="shares"')
        self.assertNotIn("each one by a person", shares)
        self.assertIn("shock plan", shares)
        self.assertIn("explicit confirmation", shares)

    def test_the_cadences_typed_here_are_the_beats(self):
        from config.celery import app
        from core.day_of_sauron import schedule_words
        beat = app.conf.beat_schedule
        self.assertEqual(schedule_words(beat["sauron-mind-synthesize"]["schedule"])[0], "1 h")
        self.assertIn("Every hour a structured world snapshot", self.body)
        self.assertEqual(schedule_words(beat["reconcile-asset-bot-trades"]["schedule"])[0],
                         "every 15 min")
        self.assertIn("every 15 min, around the clock", self.body)

    def test_no_retired_source_or_server_is_advertised(self):
        for stale in ("Reddit / StockTwits", "IBKR / Twelve Data",
                      "gunicorn + uvicorn", "taxable-account live deployment"):
            self.assertNotIn(stale, self.body, stale)

    def test_the_leverage_paragraph_says_what_the_ticket_offers(self):
        """A live ticket lists the venue's multipliers only while the
        leverage switch is on: off, every multiplier above 1 is refused
        (judge_order_leverage) and the ticket offers 1x alone. The switch
        ships off, so the page names it (review, 2026-10-08)."""
        import inspect
        from bot_program.asset_engine import base
        from core.platform_control import DEFAULT_COMPONENTS, LIVE_MONEY_SWITCHES
        self.assertNotIn("as a fact at the confirm step", self.body)
        self.assertIn("the highest by default", self.body)
        self.assertIn("with the leverage switch on, a live ticket offers the multipliers "
                      "the venue lists, the highest by default", self.body)
        self.assertEqual(base.LEVERAGE_SWITCH_KEY, "etoro_leverage_live")
        self.assertIn("LEVERAGE_SWITCH_KEY", inspect.getsource(base.judge_order_leverage),
                      "a typed multiplier no longer needs the switch: rewrite #personas")
        self.assertIn(base.LEVERAGE_SWITCH_KEY, LIVE_MONEY_SWITCHES)
        row = [c for c in DEFAULT_COMPONENTS if c["key"] == base.LEVERAGE_SWITCH_KEY][0]
        self.assertFalse(row.get("is_enabled"))

    def test_the_closed_loop_paragraph_is_the_demotion_rule(self):
        self.assertNotIn("then drifts negative", self.body)
        self.assertIn("drops straight to paper", self.body)
        self.assertIn("with the ladder's switch on", self.body)

    def test_take_trade_names_the_live_ticket(self):
        self.assertNotIn("Executes on the paper venue", self.body)
        self.assertIn("behind the trading PIN", self.body)
        # It warns OF conditions, and the last word is the visitor's.
        self.assertNotIn("warns before a reward", self.src)
        self.assertIn("and warns of a reward under the risk, a trade no signal backs, "
                      "a shut market, a bad entry hour or a sick venue", self.body)
        self.assertIn("then leaves the last word to you.", self.body)

    def test_the_hand_ticket_is_never_promised_a_bots_hold(self):
        """The last look, the sick venue and the quote check hold a bot's
        entry; the ticket placed by hand is only warned (manual_trade.py),
        so every hold on this page names the bot (review, 2026-10-08)."""
        self.assertNotIn("A crossed, stale or frozen quote is not traded on", self.src)
        self.assertIn("No bot enters on a crossed, stale or frozen quote", self.body)
        self.assertIn("every live bot order takes a last look", self.body)
        self.assertIn("new real-money bot entries wait for quiet", self.body)
        self.assertIn("No bot opens a real-money trade in a share", self.body)

    def test_the_second_gate_names_its_gestures(self):
        # The old sentence wrapped after "capital": the phrase below was the
        # whole of its first source line, so this check can fail (the
        # reflow rule).
        self.assertNotIn("Every action that can move capital", self.src)
        self.assertIn("unticking the demo box", self.body)

    def test_the_router_says_where_an_unflagged_class_goes(self):
        from pathlib import Path

        from django.conf import settings
        self.assertNotIn("Routing per-symbol via the broker_router", self.body)
        self.assertIn("otherwise nothing real is sent", self.body)
        js = (Path(settings.BASE_DIR) / "static" / "js"
              / "sv-day-scheme.js").read_text(encoding="utf-8")
        self.assertIn("otherwise nothing real is sent", js)

    def test_the_eur_preset_still_trips_a_cap(self):
        """Replacing the dollar pair in the EUR preset left it with no leg
        the demo's caps could read; the classify() line below maps a EUR
        leg onto the sector bar, so "Pile into EUR" can still be refused."""
        self.assertIn("if (base === 'EUR' || quote === 'EUR') c.sector = 'EUR';",
                      self.body)
        self.assertIn('data-preset="eur-cross"', self.body)


class WallSafeguardsSectionTests(TestCase):
    """The safeguards section (2026-10-08): what stands around a trade,
    counted off the registries the code runs on, every sentence hedged
    the way the code is.

    The guards, the real-money switches, the proving ground's verdicts and
    the classes with a venue proof are wall_facts keys, never typed. The
    section names the switch before the mechanism, because every one of
    those mechanisms ships off (core.platform_control.DEFAULT_COMPONENTS)
    and a page that said "the guards watch" of a watchdog nobody turned on
    would be the overclaim this file exists to refuse. Every fragment
    pinned here sits on ONE source line of the template (the reflow rule).
    """

    def setUp(self):
        _clear_cache()
        self.response = self.client.get("/wall/")
        self.body = self.response.content.decode("utf-8", errors="ignore")
        self.wall = self.response.context["wall"]

    def _block(self, anchor):
        start = self.body.index(anchor)
        return self.body[start:self.body.index("</section>", start)]

    def _pillar_target(self, body, label):
        """The count-up target of the pillar labelled `label`. Served
        already printed since 2026-10-08: the text is the target."""
        m = re.search(
            r'data-target="(\d+)">\1</span></div>\s*<div class="pillar-lbl">'
            + re.escape(label), body)
        self.assertIsNotNone(m, f"no pillar labelled {label!r}")
        return int(m.group(1))

    def test_the_section_stands_in_the_pages_shell(self):
        idx = self.body.index('id="safeguards"')
        self.assertIn('class="wall-section"', self.body[idx - 200:idx],
                      "#safeguards is not a .wall-section")
        self.assertIn("Before, During,", self.body)
        self.assertIn('href="#safeguards"', self.body)
        nav = re.search(r'<nav class="wall-nav" id="wallNav">(.*?)</nav>',
                        self.body, re.S).group(1)
        self.assertLess(nav.index('href="#fleet"'), nav.index('href="#safeguards"'))
        self.assertLess(nav.index('href="#safeguards"'), nav.index('href="#desk"'))
        block = self._block('id="safeguards"')
        for marker in ("section-label", "new-pill", "section-title",
                       "features-grid", "feature-card", "feature-icon",
                       "pillar-row", "reveal delay-1"):
            self.assertIn(marker, block, marker)
        self.assertEqual(block.count('class="feature-card'), 6)
        self.assertEqual(block.count('class="pillar"'), 4)

    def test_every_count_in_it_is_the_facts(self):
        block = self._block('id="safeguards"')
        for key in ("guards", "money_switches", "proving_verdicts",
                    "proof_classes"):
            self.assertIn(f'data-target="{self.wall[key]}"', block, key)
            self.assertIsInstance(self.wall[key], int)
        self.assertEqual(block.count("data-target="), 4)
        self.assertEqual(self._pillar_target(block, "Guards in the Watchdog"),
                         self.wall["guards"])
        self.assertEqual(self._pillar_target(block, "Real-Money Switches"),
                         self.wall["money_switches"])
        self.assertEqual(self._pillar_target(block, "Proving Verdicts Written"),
                         self.wall["proving_verdicts"])
        self.assertEqual(self._pillar_target(block, "Classes Through the Venue"),
                         self.wall["proof_classes"])
        # The counts the prose carries are the same keys, in the same block.
        self.assertIn(f"none of the {self.wall['money_switches']} switches", block)
        self.assertIn(f"&mdash; {self.wall['proof_classes']} have &mdash;", block)
        self.assertIn(f"{self.wall['short_classes']} have one", block)
        # The spine's closing paragraph carries the count since 2026-10-08.
        spine = self._block('id="spine"')
        self.assertIn(f"the {self.wall['money_switches']} switches the platform "
                      "marks as real-money decisions", spine)
        self.assertNotIn("the ones the platform marks", spine)
        # Never a word or a digit typed beside the count.
        low = block.lower()
        for literal in ("eleven guards", "ten guards", "twelve switches",
                        "seven switches", "six classes", "two classes"):
            self.assertNotIn(literal, low, literal)

    def test_it_names_the_switch_before_the_mechanism(self):
        from core.platform_control import DEFAULT_COMPONENTS
        self.assertEqual(
            [c["key"] for c in DEFAULT_COMPONENTS if c.get("is_enabled")], [],
            "a component now ships enabled — the section's 'with its switch "
            "on' hedges may need to change with it")
        block = self._block('id="safeguards"')
        self.assertGreaterEqual(block.lower().count("with its switch on"), 2)
        self.assertIn("with their switch on", block)
        self.assertIn("ships switched off", block)
        self.assertIn("Every one ships off", block)
        # The dead man's switch pings only once a URL is set: hedged too.
        self.assertIn("Once it is set up", block)
        # The brake is a switch of its own, which acts only while the
        # guards' is on (bot_program/morgul.py BRAKE_KEY).
        from bot_program import morgul
        self.assertEqual(morgul.BRAKE_KEY, "morgul_brake")
        self.assertIn("With a second switch on as well, a few of them may brake", block)

    def test_the_care_card_says_the_thresholds_it_cuts_and_locks_at(self):
        """The care cuts a real-money loser only from WEEKEND_CUT_LEVERAGE
        times leverage (the event window's cut is the weekend's), and locks
        a winner only from WEEKEND_LOCK_AT_R on the mark. The card once said
        "a levered real-money loser is cut", of any multiplier (final check,
        2026-10-08). The Book's three sentences are held the same way in
        tests/test_the_book.py."""
        from bot_program import position_care as care
        rewrite = ("rewrite the Wall's 'Care of the Open Trade' card, and the Book's "
                   "'The care', 'The care of an open trade' and 'The event window'")
        self.assertEqual(care.WEEKEND_CUT_LEVERAGE, 5,
                         "the weekend cut moved: %s ('five times leverage or more')" % rewrite)
        self.assertEqual(care.EVENT_CUT_LEVERAGE, care.WEEKEND_CUT_LEVERAGE,
                         "the event cut left the weekend's: %s" % rewrite)
        self.assertEqual(care.WEEKEND_LOCK_AT_R, 0.5,
                         "the weekend lock moved: %s ('half an R or more')" % rewrite)
        self.assertEqual(care.EVENT_LOCK_AT_R, care.WEEKEND_LOCK_AT_R,
                         "the event lock left the weekend's: %s" % rewrite)
        block = self._block('id="safeguards"')
        start = block.index("Care of the Open Trade")
        card = block[start:block.index("</div>", block.index('class="feature-text"', start))]
        self.assertIn("a real-money loser at five times leverage or more is cut", card, rewrite)
        self.assertIn("a winner up half an R or more is locked at break-even", card, rewrite)
        # The cuts are a bot's: a hand-opened row returns before every cut
        # (position_care: the manual branch comes before the weekend, event
        # and no-progress cuts), so the card says so in the same breath.
        self.assertIn("A trade opened by hand keeps the locks and is never cut by a rule.",
                      card, "the manual lane's exemption left the card: %s" % rewrite)
        src = (Path(settings.BASE_DIR) / "templates" / "landing"
               / "the_wall.html").read_text(encoding="utf-8")
        self.assertNotIn("levered real-money loser", src, rewrite)

    def test_its_cadence_is_the_beats(self):
        from config.celery import app
        from core.day_of_sauron import schedule_words
        beat = app.conf.beat_schedule
        self.assertEqual(schedule_words(beat["run-morgul-guards"]["schedule"])[0],
                         "5 min")
        block = self._block('id="safeguards"')
        self.assertIn("Every five minutes", block)
        self.assertIn("every five minutes", block)
        # "Each night": the proving ground's rules run is one cron a day.
        words, period, kind, _minute = schedule_words(
            beat["proving-ground-rules"]["schedule"])
        self.assertEqual((kind, period), ("cron", 86400.0), words)
        self.assertIn("Each night", block)

    def test_it_reaches_no_external_host(self):
        for anchor in ('id="safeguards"', 'id="latest"'):
            block = self._block(anchor)
            for scheme in ("http://", "https://", "//cdn", 'src="//'):
                self.assertNotIn(scheme, block,
                                 f"section {anchor} reaches an external host")

    def test_it_moves_when_a_verdict_is_saved(self):
        """The counted-ness of the proving verdicts, demonstrated: one
        saved verdict, whatever it says, and the pillar moves."""
        from backtester.models_proving import ProvingVerdict

        self.assertEqual(self.wall["proving_verdicts"], 0)
        self.assertEqual(self._pillar_target(
            self._block('id="safeguards"'), "Proving Verdicts Written"), 0)
        ProvingVerdict.objects.create(run_id="t", family="f", direction="long",
                                      asset_class="forex", verdict="failed")
        _clear_cache()
        r = self.client.get("/wall/")
        self.assertEqual(r.context["wall"]["proving_verdicts"], 1)
        body = r.content.decode("utf-8", errors="ignore")
        start = body.index('id="safeguards"')
        block = body[start:body.index("</section>", start)]
        self.assertEqual(self._pillar_target(block, "Proving Verdicts Written"), 1)


class WallLatestStepsTests(TestCase):
    """The latest steps (2026-10-08): the Book's newest four milestones on
    the Wall, each a link to its own line in the Book, read off
    core.views_book.latest_steps at render time — never a hash, never a
    typed date — and a road the view cannot read leaves the Wall standing.
    """

    def setUp(self):
        _clear_cache()
        self.response = self.client.get("/wall/")
        self.body = self.response.content.decode("utf-8", errors="ignore")

    def _block(self, body=None):
        body = self.body if body is None else body
        start = body.index('id="latest"')
        return body[start:body.index("</section>", start)]

    def test_the_latest_steps_are_the_books_last(self):
        from django.utils.html import escape

        from core import book_content as book
        from core.views_book import day_words, latest_steps

        block = self._block()
        self.assertIn("The Latest Steps", block)
        self.assertIn("The Road So Far", block)
        last = list(book.MILESTONES)[-4:]
        self.assertEqual(len(last), 4)
        at = []
        for day, _era, title, _text, _commit in reversed(last):
            self.assertIn(escape(title), block, title)
            self.assertIn(day_words(day), block, day)
            self.assertIn(f'datetime="{day}"', block)
            at.append(block.index(escape(title)))
        self.assertEqual(at, sorted(at), "the steps are not newest first")
        self.assertEqual(block.count("<li>"), 4)
        self.assertEqual(self.response.context["latest"], latest_steps(4))
        # No commit hash reaches the Wall through the road.
        for _day, _era, _title, _text, commit in book.MILESTONES:
            self.assertNotRegex(block, r"(?<![0-9a-f])%s(?![0-9a-f])" % commit)

    def test_each_step_links_to_its_line_in_the_book(self):
        from core.views_book import latest_steps

        block = self._block()
        steps = latest_steps(4)
        self.assertEqual(len(steps), 4)
        for step in steps:
            self.assertRegex(step["anchor"], r"^m-[a-z0-9-]+$")
            self.assertIn(f'href="/book/#{step["anchor"]}"', block)
        self.assertIn('href="/book/#road"', block)
        # 'href="/book/#…"' is not 'href="/book/"': the two doors of
        # tests/test_the_book.py and test_wall_book_link.py stay two.
        self.assertEqual(self.body.count('href="/book/"'), 2)
        # And every link lands: the Book carries each anchor and the road.
        book = self.client.get("/book/").content.decode("utf-8")
        self.assertIn('id="road"', book)
        for step in steps:
            self.assertIn('id="%s"' % step["anchor"], book)

    def test_a_broken_road_still_serves_the_wall(self):
        """A milestone the view cannot read (a day that is not a day) must
        not take the front door down with it: the list is empty, the door
        to the Book stands, and the broken row never reaches the page."""
        from unittest.mock import patch

        with patch("core.book_content.MILESTONES",
                   [("not-a-day", "x", "t", "w.", "abcdef0")]):
            _clear_cache()
            r = self.client.get("/wall/")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode("utf-8", errors="ignore")
        self.assertEqual(r.context["latest"], [])
        block = self._block(body)
        self.assertIn('id="latest"', body)
        self.assertIn('href="/book/#road"', block)
        self.assertNotIn("not-a-day", body)
        self.assertNotIn("abcdef0", body)
        self.assertNotIn("<li>", block)


class TheWallStaysOpenTests(TestCase):
    """The front door after 2026-10-08: rendered without the request's
    context processors (core/views_wall.py), every reader it calls fenced
    on its own, and the login forms still carrying a token the middleware
    accepts.

    Through `render()` the Wall paid for every panel of the dashboard's
    shell: forty-odd queries on a warm visit, most of them on live quotes
    an anonymous visitor is never shown, and a dashboard panel that broke
    broke the login page with it. The Book has rendered the other way
    since 2026-09-27; these tests hold the Wall to the same bargain and to
    the one thing it needs that the Book does not: the CSRF token.
    """

    def setUp(self):
        _clear_cache()

    def test_an_unreadable_schedule_still_serves_the_wall(self):
        """A Celery app that will not read, or a beat entry these words
        cannot describe, draws an empty ring; it does not take the front
        door down, and the warning names the exception's class alone."""
        from unittest.mock import patch

        from tests.test_wall_day import _json_on

        with patch("core.day_of_sauron.read_schedule",
                   side_effect=RuntimeError("the beat is unreadable")), \
             self.assertLogs("core.day_of_sauron", level="WARNING") as logs:
            r = self.client.get("/wall/")
        self.assertEqual(r.status_code, 200)
        day = _json_on(r.content.decode())
        self.assertEqual(day["total"], 0)
        self.assertEqual(day["stages"], [])
        self.assertEqual(r.context["day"]["total"], 0)
        self.assertIn("RuntimeError", logs.output[0])
        self.assertNotIn("unreadable", logs.output[0])

    def test_a_broken_session_clock_still_serves_the_wall(self):
        """The session pills are clock arithmetic and the one reader the
        view used to call bare: a clock that throws leaves the row empty
        and the page standing."""
        from unittest.mock import patch

        with patch("core.views_wall.market_sessions",
                   side_effect=RuntimeError("no clock")), \
             self.assertLogs("core.views_wall", level="WARNING") as logs:
            r = self.client.get("/wall/")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode("utf-8", errors="ignore")
        self.assertIn('class="sess-row"', body)
        self.assertEqual(r.context["sessions"], [])
        row = body.split('class="sess-row"')[1].split("</div>")[0]
        self.assertNotIn('<span class="sess-pill', row)
        self.assertIn("RuntimeError", logs.output[0])
        self.assertNotIn("no clock", logs.output[0])

    def test_a_warm_wall_reads_nothing(self):
        """The facts are cached, the sessions are arithmetic, the ring is
        the beat and the road is the Book's own list: a warm visit opens
        no connection at all. Through the context processors it opened
        forty-three (2026-10-07, measured)."""
        self.client.get("/wall/")  # warm
        with self.assertNumQueries(0):
            r = self.client.get("/wall/")
        self.assertEqual(r.status_code, 200)

    def test_the_page_pays_none_of_a_dashboards_reads(self):
        """No context processor ran: no permissions, no messages. What the
        login forms need is passed by name, and get_token() is what
        makes the middleware set the cookie the token is checked against."""
        r = self.client.get("/wall/")
        self.assertEqual(r.status_code, 200)
        for name in ("perms", "messages"):
            self.assertNotIn(name, r.context)
        for name in ("wall", "sessions", "day", "latest", "csrf_token"):
            self.assertIn(name, r.context)
        self.assertIn("csrftoken", r.cookies)
        body = r.content.decode("utf-8", errors="ignore")
        self.assertEqual(body.count('name="csrfmiddlewaretoken"'), 3)
        self.assertNotIn('value=""', body.split('name="csrfmiddlewaretoken"')[1][:40])

    def test_the_login_still_posts_from_the_wall(self):
        """With the checks the browser meets (not the test client's
        default, which skips them): the token the Wall printed, posted
        back with bad credentials, is refused as bad credentials and
        never as a missing token."""
        from django.test import Client

        from core import security

        security._login_attempts.clear()
        client = Client(enforce_csrf_checks=True)
        page = client.get("/wall/").content.decode("utf-8", errors="ignore")
        token = re.search(
            r'name="csrfmiddlewaretoken" value="([^"]+)"', page).group(1)
        r = client.post("/login/", {"csrfmiddlewaretoken": token,
                                    "username": "nobody_on_the_wall",
                                    "password": "not-the-password"})
        self.assertNotEqual(r.status_code, 403)
        self.assertIn(r.status_code, (200, 400))


class MotionIsOptionalOnTheWallTests(TestCase):
    """Progressive enhancement on the Wall (2026-10-08), on the Book's
    model: the page is readable exactly as served, and the motion is laid
    on top only where it can run and is welcome.

    Before, every block began at opacity 0 and waited for a script to
    reveal it, and left the page again when scrolled out of view; a
    visitor without script, a script that threw, a print and a reader who
    asked for less motion all read a blank page. Now a head switch marks
    the root `.wall-js` only where the reveal observer exists and motion
    is welcome, with a three-second failsafe; every counter is served
    already printed; reduced motion stops everything and shows
    everything; print is dark ink on white with everything shown; the
    five decorative layers are hidden from assistive technology.

    The stylesheet is parsed the way tests/test_the_book.py parses it.
    """

    #: Rules that hide something outside the reveal system, enumerated
    #: from the page on 2026-10-08: the login and PIN overlays (shown by a
    #: body class the login flow sets) and the two ladders that enter on
    #: logRowIn (restored under reduced motion and in print).
    HIDDEN_BY_DESIGN = {
        "body.login-mode .wall-content", "body.login-mode .wall-nav",
        ".login-overlay", ".login-anim",
        "body.login-mode.pin-mode .login-overlay",
        "body.login-mode.pin-mode .login-overlay .login-anim",
        ".pin-overlay", ".pin-anim", ".demo-log-row", ".desk-row",
    }

    @classmethod
    def setUpTestData(cls):
        from pathlib import Path

        from django.conf import settings
        cls.src = (Path(settings.BASE_DIR) / "templates" / "landing"
                   / "the_wall.html").read_text(encoding="utf-8")

    def setUp(self):
        _clear_cache()
        self.body = self.client.get("/wall/").content.decode("utf-8", errors="ignore")

    def _css(self):
        from tests.test_the_book import _css
        return _css(self.body)

    def _head(self):
        return self.body[:self.body.index("<style>")]

    def _main_script(self):
        return self.body[self.body.rindex("<script>"):]

    def test_nothing_is_hidden_unless_the_reveal_can_run(self):
        from tests.test_the_book import _drop_blocks, _rules

        css = self._css()
        css = _drop_blocks(css, r"@keyframes [\w-]+\s*")
        css = _drop_blocks(css, r"@media \(prefers-reduced-motion: reduce\)\s*")
        css = _drop_blocks(css, r"@media print\s*")
        hidden = []
        for selector, rules in _rules(css):
            flat = re.sub(r"\s+", "", rules)
            if re.search(r"opacity:0(?![.\d])", flat) or "visibility:hidden" in flat:
                hidden.append(" ".join(selector.split()))
        self.assertTrue(hidden)
        for selector in hidden:
            with self.subTest(selector=selector):
                self.assertTrue(
                    selector.startswith(".wall-js ")
                    or "::before" in selector or "::after" in selector
                    or selector in self.HIDDEN_BY_DESIGN,
                    "%r is hidden before any script runs" % selector)
        # The reveal rules are the ones behind the switch, all four of them.
        for kind in (".reveal", ".reveal-left", ".reveal-right", ".reveal-scale"):
            self.assertIn(".wall-js " + kind, hidden)
            self.assertNotIn(kind, hidden)
            self.assertIn(".wall-js %s.visible { opacity: 1;" % kind, self.body)

    def test_the_head_switch_has_a_failsafe(self):
        head = self._head()
        for word in ("wall-js", "IntersectionObserver",
                     "prefers-reduced-motion: reduce", "setTimeout",
                     "wallAwake", 'classList.remove("wall-js")'):
            self.assertIn(word, head, word)
        # It runs before the stylesheet, so no block is ever hidden and
        # then shown: the class is on the root before the first rule.
        self.assertLess(head.index("wall-js"), self.body.index("<style>"))
        self.assertIn("window.wallAwake = true", self._main_script())
        # Plain JavaScript in the source: no template tag, so
        # tests.test_inline_js_parses reads it.
        src_head = self.src[:self.src.index("<style>")]
        switch = src_head[src_head.index("<script>"):src_head.index("</script>")]
        self.assertNotIn("{{", switch)
        self.assertNotIn("{%", switch)

    def test_reduced_motion_stops_everything_and_shows_everything(self):
        from tests.test_the_book import _block

        block = _block(self._css(), r"@media \(prefers-reduced-motion: reduce\)")
        for rule in ("animation: none !important", "transition: none !important",
                     "scroll-behavior: auto"):
            self.assertIn(rule, block, rule)
        rule_at = block.index(".desk-row {")
        rule = block[rule_at:block.index("}", rule_at)]
        self.assertIn("opacity: 1", rule)
        self.assertIn("transform: none", rule)
        self.assertIn(".demo-log-row { opacity: 1 !important; transform: none !important; }", block)
        # And the easing of the page's own scroll is asked for only where
        # motion is welcome.
        self.assertIn("@media (prefers-reduced-motion: no-preference) { html { scroll-behavior: smooth; } }",
                      self.body)
        self.assertNotIn("html { scroll-behavior: smooth; overflow-x: hidden; }", self.body)

    def test_print_shows_everything_in_dark_ink(self):
        from tests.test_the_book import _block, _rules

        css = self._css()
        self.assertIn("@media print", css)
        block = _block(css, r"@media print")
        rules = dict(_rules(block))
        restore = next(v for k, v in rules.items() if ".desk-row" in k and ".demo-log-row" in k)
        self.assertIn("opacity: 1 !important", restore)
        for kind in (".reveal", ".reveal-left", ".reveal-right", ".reveal-scale"):
            self.assertTrue(any(kind in k and "opacity: 1 !important" in v
                                for k, v in rules.items()), kind)
        self.assertIn("--text: #111", block)
        self.assertIn("--bg: #fff", block)
        hidden = next(v for k, v in rules.items() if "#bgCanvas" in k and ".login-overlay" in k)
        self.assertIn("display: none !important", hidden)
        for layer in (".grid-bg", ".scan-line", ".eye-glow-shadow",
                      ".globe-eye-fixed", ".wall-nav", ".pin-overlay"):
            self.assertTrue(any(layer in k and "display: none !important" in v
                                for k, v in rules.items()), layer)
        self.assertIn("animation: none !important", block)
        # The gradient-clipped counts print as plain ink: with background
        # graphics left out, the browser default, a clipped gradient paints
        # nothing and the transparent letters printed as an empty slot (the
        # four pillars of the safeguards among them, measured 2026-10-08).
        for clipped in (".pillar-num", ".hash-block .hash-shimmer"):
            with self.subTest(selector=clipped):
                on_screen = [v for k, v in _rules(css) if k == clipped]
                self.assertTrue(any("background-clip: text" in v and "color: transparent" in v
                                    for v in on_screen), clipped)
        ink = [v for k, v in rules.items()
               if ".pillar-num" in k and ".hash-block .hash-shimmer" in k]
        self.assertEqual(len(ink), 1, "no print rule gives the clipped counts plain ink")
        ink = ink[0]
        self.assertIn("background: none !important", ink)
        self.assertIn("background-clip: border-box !important", ink)
        self.assertIn("-webkit-text-fill-color: var(--accent) !important", ink)
        self.assertRegex(ink, r"(?<![-\w])color: var\(--accent\) !important")
        # The page's own :root stays the first one: the Book copies it.
        self.assertLess(self.body.index(":root {"), self.body.index("@media print"))

    def test_every_count_is_printed_before_any_script(self):
        pairs = re.findall(r'data-target="(\d+)">([^<]*)<', self.body)
        self.assertGreaterEqual(len(pairs), 15)
        for target, text in pairs:
            with self.subTest(target=target):
                self.assertEqual(text, target)
        # In the source too: the same wall key on both sides, never a zero.
        self.assertNotIn('">0</span>', self.src.split("<section")[0])
        self.assertEqual(
            re.findall(r'data-target="\{\{ wall\.([a-z0-9_]+) \}\}">0</span>', self.src), [])
        for key, printed in re.findall(
                r'data-target="\{\{ wall\.([a-z0-9_]+) \}\}">\{\{ wall\.([a-z0-9_]+) \}\}</span>',
                self.src):
            self.assertEqual(key, printed)

    def test_the_particles_and_the_svg_clocks_rest_when_motion_is_not_welcome(self):
        script = self._main_script()
        particles = script[script.index("function drawParticles"):script.index("drawParticles();")]
        self.assertIn("requestAnimationFrame", particles)
        self.assertLess(particles.index("prefersReducedMotion"),
                        particles.index("requestAnimationFrame"))
        self.assertIn("if (prefersReducedMotion) {", script)
        pause = script[script.index("if (prefersReducedMotion) {"):]
        self.assertIn("pauseAnimations", pause[:pause.index("}")])
        # There is something to pause: the inline SMIL clocks.
        self.assertGreaterEqual(self.body.count("<animateMotion"), 4)
        self.assertIn("<animate ", self.body)
        self.assertIn("prefersReducedMotion ? 'auto' : 'smooth'", script)

    def test_what_was_read_stays_read_and_counts_once(self):
        script = self._main_script()
        self.assertNotIn("classList.remove('visible')", script)
        self.assertIn("observer.unobserve(entry.target)", script)
        self.assertIn("countObserver.unobserve(el)", script)
        # The observer is armed before the counters, the ticker and the
        # particles, so a throw further down never leaves a block hidden.
        self.assertLess(script.index("window.wallAwake = true"), script.index("var WALL = {"))
        self.assertLess(script.index("observer.observe(el)"), script.index("window.wallAwake = true"))

    def test_the_reduced_motion_frame_survives_a_resize(self):
        """Setting the canvas size clears it, and under reduced motion no
        next frame is scheduled: measured on 2026-10-08, the one frame was
        gone after the first resize (2198 painted pixels, then 0)."""
        script = self._main_script()
        first = script.index("drawParticles();")
        listener = script[script.index("window.addEventListener('resize'"):]
        listener = listener[:listener.index("});")]
        self.assertLess(script.index("function drawParticles"), first)
        self.assertLess(first, script.index("window.addEventListener('resize'"))
        self.assertIn("resize();", listener)
        self.assertIn("if (prefersReducedMotion) { drawParticles(); }", listener)
        self.assertNotIn("window.addEventListener('resize', resize)", script)

    def test_an_engine_without_the_observer_still_runs_the_page(self):
        """The head switch leaves every block visible where there is no
        IntersectionObserver; the scripts then built one unconditionally and
        died at it, before the ticker, the counts, the eye and the door
        (measured 2026-10-08). Every observer is now behind the same test,
        and without one the counts are grouped at once."""
        for m in re.finditer(r"new IntersectionObserver", self.body):
            before = self.body[max(0, m.start() - 400):m.start()]
            with self.subTest(at=m.start()):
                self.assertTrue("canObserve" in before
                                or "typeof window.IntersectionObserver" in before,
                                "an observer built without asking whether the engine has one")
        script = self._main_script()
        self.assertLess(script.index("var canObserve = typeof window.IntersectionObserver === 'function';"),
                        script.index("new IntersectionObserver"))
        self.assertIn("if (observer) { observer.observe(el); } else { el.classList.add('visible'); }",
                      script)
        self.assertIn("if (!canObserve) {", script[script.index("var countEls"):])
        self.assertIn("window.wallAwake = true", script)

    def test_the_demo_prints_its_sector_tally_to_one_decimal(self):
        """The sector tally decays by 0.4 every 1.5 s, so it is a float;
        the decision log read "EUR sector 3.200000000000001 > 3" before
        the readouts were rounded (measured 2026-10-08)."""
        self.assertIn("reason = contrib.sector + ' sector ' + afterSec.toFixed(1) + ' > ' + secCap;",
                      self.body)
        self.assertIn("expSecEl.textContent = s[0] + ' ' + s[1].toFixed(1);", self.body)
        self.assertNotIn("' sector ' + afterSec + ", self.body)
        # The tally itself is kept to a tenth: a sum that only printed as
        # one decimal read "EUR sector 3.0 > 3" (measured 2026-10-08).
        self.assertIn("exp.sectors[k] = Math.round(Math.max(0, exp.sectors[k] - 0.4) * 10) / 10;",
                      self.body)

    def test_the_decorative_layers_are_hidden_from_assistive_tech(self):
        for opener in ('<div class="grid-bg"', '<canvas id="bgCanvas"',
                       '<div class="scan-line"', '<div class="eye-glow-shadow"',
                       '<svg class="globe-eye-fixed"'):
            start = self.body.index(opener)
            tag = self.body[start:self.body.index(">", start)]
            self.assertIn('aria-hidden="true"', tag, opener)
