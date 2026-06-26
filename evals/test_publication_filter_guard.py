"""Guard: the publication filter must import and expose its gate API.

The publication evals (test_no_internal_ids / test_som_threshold /
test_translation_friendly / test_portfolio_slate) load pipeline.template_filter
via ``pytest.importorskip``, which SKIPS silently if the module breaks -- a dark
gate that reports green while not actually running. This test HARD-imports the
filter at module top (a break fails collection, loud) and asserts the public
surface those evals depend on. It is the cheap, low-blast-radius version of
"replace importorskip with a hard import" -- it makes a broken/removed filter
fail loud without forcing a type-cleanup of the four importorskip call sites.
"""

from __future__ import annotations

import pipeline.template_filter as tf

_REQUIRED_CALLABLES = ("scan_for_internal_ids", "check_translation_friendly", "parse_som")


def test_publication_filter_exposes_gate_api() -> None:
    missing = [name for name in _REQUIRED_CALLABLES if not callable(getattr(tf, name, None))]
    assert not missing, f"pipeline.template_filter lost gate callables: {missing}"
    assert isinstance(tf.FK_GRADE_MAX, (int, float)), "FK_GRADE_MAX must be numeric"
