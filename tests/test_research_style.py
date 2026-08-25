"""Ask Sauron wears its own clothes — the answer, not the transcript.

The /research/ page printed Sauron's answers raw: the renderer's
[label →](url) links showed as brackets, **emphasis** as asterisks,
lists as dashes, code as backticks. research_md dresses an assistant
turn and NOTHING else — the operator's words and error turns stay
verbatim — and because it runs on LLM output it escapes everything
first and honours only same-site and https links. The XHR answer path
carries the same rendering, so a turn painted in place looks like the
same turn after a reload.

Run with:  python manage.py test tests.test_research_style
"""
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase


def _md(text):
    from core.templatetags.sauron_tags import research_md
    return str(research_md(text))


class ResearchMdSafetyTests(TestCase):

    def test_llm_markup_is_escaped_never_executed(self):
        html = _md("<script>alert(1)</script> **<b>x</b>**")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("<strong>&lt;b&gt;x&lt;/b&gt;</strong>", html)

    def test_a_javascript_link_is_neutralised_to_its_label(self):
        html = _md("see [here](javascript:alert(1)) and [d](data:text/html,x)")
        self.assertNotIn("javascript:", html)
        self.assertNotIn("data:", html)
        self.assertNotIn("<a", html)
        self.assertIn("see here and d", html)

    def test_a_protocol_relative_link_is_refused(self):
        html = _md("[evil](//evil.example/x)")
        self.assertNotIn("<a", html)
        self.assertNotIn("//evil.example", html)
        self.assertIn("evil", html)

    def test_an_https_link_becomes_an_anchor(self):
        html = _md("[docs](https://example.com/a?b=1)")
        self.assertIn('<a class="rs-link" href="https://example.com/a?b=1">'
                      "docs</a>", html)

    def test_a_same_site_path_becomes_an_anchor(self):
        """The marker renderer's own shape: [label →](/path/)."""
        html = _md("[Rule 3 →](/brain/rules/3/)")
        self.assertIn('<a class="rs-link" href="/brain/rules/3/">Rule 3 →</a>',
                      html)


class ResearchMdRenderingTests(TestCase):

    def test_bold_code_and_headings_render(self):
        html = _md("## Read\n\n**loud** and `quiet`")
        self.assertIn('<h4 class="rs-h">Read</h4>', html)
        self.assertIn("<strong>loud</strong>", html)
        self.assertIn('<code class="rs-code">quiet</code>', html)
        self.assertNotIn("**", html)
        self.assertNotIn("##", html)

    def test_bullets_and_numbers_become_lists(self):
        html = _md("- one\n* two\n• three\n\n1. a\n2) b")
        self.assertIn('<ul class="rs-list"><li>one</li><li>two</li>'
                      "<li>three</li></ul>", html)
        self.assertIn('<ol class="rs-list"><li>a</li><li>b</li></ol>', html)

    def test_paragraphs_lead_and_fenced_code(self):
        html = _md("Lead line\nsecond line\n\nNext.\n\n```json\n"
                   '{"a": **1**}\n```')
        self.assertIn('<p class="rs-p rs-lead">Lead line<br>second line</p>',
                      html)
        self.assertIn('<p class="rs-p">Next.</p>', html)
        # Inside a fence nothing is markdown: the asterisks survive.
        self.assertIn('<pre class="rs-pre"><code>{&quot;a&quot;: **1**}'
                      "</code></pre>", html)


def _stub_provider(answer_text):
    usage = {"input_tokens": 4500, "output_tokens": 700, "cost_usd": 0.18}

    def patched_init(self, *a, **kw):
        self.agent_name = "research"
        self.provider_name = "stub"
        self.model = "claude-stub"
        self.provider = MagicMock()
        self.provider.complete = MagicMock(return_value=(answer_text, usage))
    return patch("brain.research_agent.ResearchAgent.__init__", patched_init)


class ResearchPageTests(TestCase):

    def setUp(self):
        from brain.research_agent import get_or_create_active_conversation
        self.user = User.objects.create_user(username="rs_u", password="x")
        self.conv = get_or_create_active_conversation(self.user)
        self.client.force_login(self.user)

    def _msg(self, role, content, **kw):
        from brain.research_models import ResearchMessage
        return ResearchMessage.objects.create(
            conversation=self.conv, role=role, content=content, **kw)

    def test_the_page_dresses_a_sauron_turn_and_leaves_the_operator_alone(self):
        self._msg("user", "What is **your** read? <b>hi</b>")
        self._msg("assistant", "**Bearish.**\n\n- USD soft\n- gold bid",
                  model_used="claude-stub", tokens_in=4500, tokens_out=700,
                  cost_usd="0.18")
        html = self.client.get("/research/").content.decode()
        self.assertIn("<strong>Bearish.</strong>", html)
        self.assertIn('<ul class="rs-list"><li>USD soft</li>', html)
        self.assertIn('class="rs-chip"', html)
        # The operator's own words: verbatim, escaped, no rs-* markup.
        self.assertIn("What is **your** read? &lt;b&gt;hi&lt;/b&gt;", html)
        user_turn = html.split('class="turn turn--user')[1].split("</article>")[0]
        self.assertNotIn("rs-", user_turn)
        self.assertNotIn("<strong>", user_turn)

    def test_the_xhr_answer_carries_the_same_rendering(self):
        with _stub_provider("**Bearish** [Rule 3 →](/brain/rules/3/)"):
            r = self.client.post("/research/ask-ajax/", {"question": "USD?"})
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertTrue(d["ok"])
        self.assertIn("<strong>Bearish</strong>", d["assistant_html"])
        self.assertIn('<a class="rs-link" href="/brain/rules/3/">',
                      d["assistant_html"])
        # The banner preview quotes text: the plain twin has no tags.
        self.assertNotIn("<", d["assistant_text"])
        self.assertIn("Bearish", d["assistant_text"])
