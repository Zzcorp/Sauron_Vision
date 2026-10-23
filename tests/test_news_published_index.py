"""NewsArticle.published_at IS INDEXED (spec §5.2a item 6, O1c): every
reader of the day's news filters and orders on it (the dossier's MK12 and
IN9, news_risk, the brain), and the table had ordering only. One AddIndex,
reversible, no data moved. The Orcs' own O1c migration is reversible too.

Run with:  python manage.py test tests.test_news_published_index
"""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TransactionTestCase

INDEX = "newsarticle_published_idx"


def _indexes(table):
    with connection.cursor() as cur:
        return connection.introspection.get_constraints(cur, table)


class TheMetaTests(SimpleTestCase):

    def test_the_model_declares_the_index(self):
        from scraping.models import NewsArticle
        idx = {i.name: i.fields for i in NewsArticle._meta.indexes}
        self.assertEqual(idx[INDEX], ["published_at"])
        self.assertEqual(NewsArticle._meta.ordering, ["-published_at"])

    def test_the_migrations_are_one_operation_each_and_reversible(self):
        import importlib
        m = importlib.import_module(
            "scraping.migrations.0004_newsarticle_published_at_idx")
        ops = m.Migration.operations
        self.assertEqual(len(ops), 1)
        self.assertEqual(type(ops[0]).__name__, "AddIndex")
        self.assertTrue(ops[0].reversible)
        o1c = importlib.import_module(
            "bot_program.migrations.0045_orcs_dossier_drums")
        self.assertIn(("bot_program", "0044_orcs"),
                      o1c.Migration.dependencies)
        for op in o1c.Migration.operations:
            self.assertTrue(op.reversible, op)
            self.assertNotIn(type(op).__name__, ("RunPython", "RunSQL"))


class TheReversalTests(TransactionTestCase):

    def test_the_index_goes_and_comes_back(self):
        executor = MigrationExecutor(connection)
        before = [("scraping", "0003_alter_institutionalfiling_instrument_"
                               "and_more")]
        after = [("scraping", "0004_newsarticle_published_at_idx")]
        self.assertIn(INDEX, _indexes("scraping_newsarticle"))
        executor.migrate(before)
        self.assertNotIn(INDEX, _indexes("scraping_newsarticle"))
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(after)
        self.assertIn(INDEX, _indexes("scraping_newsarticle"))
