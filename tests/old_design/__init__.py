"""The zero-old-design guard's machinery (B0 of the old-design redo,
2026-11-13), read by tests/test_zero_old_design.py:

  rules.py    the source half's census: the old markers of a sheet, a
              script, a template and the Python that paints;
  owners.py   the file:line -> batch map (who empties what);
  budget.py   tests/old_design_budget.json: the ratchet, its frozen
              ceiling, STRICT, the comparisons and the lowering;
  measure.py  the measured half's driver: Chromium over its DevTools pipe,
              the synthetic book, the scenes, the held clock;
  routes.py   every routed page of the URL conf, against the scenes.

Tests only. Synthetic data; no network, no broker, no model.
"""
