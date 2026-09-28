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
    "Six Brokers. One Adapter Pattern.",
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
