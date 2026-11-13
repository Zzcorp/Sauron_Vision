"""The CI's tag filter can read every test (2026-11-13).

The suite's CI job runs ``manage.py test tests --exclude-tag=old_design_measured``
(B0: the measured old-design guard has a job of its own). With a tag filter,
Django reads ``tags`` on every test it found, so a test class whose body
defines anything named ``tags`` (a helper method, a list) stops the whole
run before its first test. That happened on B0's first CI run, from a
``tags(html, cls)`` helper in tests/test_marquee.py: "TypeError: 'function'
object is not iterable". Django's own ``@tag`` decorator is the one way to
give a test its tags. Read from the source, so this costs no import.
"""
import ast
import pathlib
import unittest

TESTS = pathlib.Path(__file__).resolve().parent


def _class_body_names(item):
    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [item.name]
    if isinstance(item, ast.Assign):
        return [t.id for t in item.targets if isinstance(t, ast.Name)]
    if isinstance(item, (ast.AnnAssign, ast.AugAssign)) and isinstance(item.target, ast.Name):
        return [item.target.id]
    return []


class TheTagFilterCanReadEveryTestTests(unittest.TestCase):

    def test_no_class_in_the_tests_defines_tags(self):
        found = []
        for path in sorted(TESTS.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                for item in node.body:
                    if "tags" in _class_body_names(item):
                        found.append("%s:%d %s.tags" % (
                            path.relative_to(TESTS.parent), item.lineno, node.name))
        self.assertEqual(
            found, [],
            "a filtered run (the CI's --exclude-tag) reads `tags` on every test: "
            "name this otherwise, or tag the test with django.test.tag")

    def test_the_check_finds_a_helper_named_tags(self):
        """The check bites: a class body with a `tags` helper is found."""
        tree = ast.parse("class T:\n    @staticmethod\n    def tags(html, cls):\n        return []\n")
        cls = tree.body[0]
        self.assertEqual([n for item in cls.body for n in _class_body_names(item)], ["tags"])
