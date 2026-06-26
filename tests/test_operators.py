"""Tests for pipeline/operators/ scaffold (PIPE-12).

Verifies:
- Operator is a runtime-checkable Protocol (not ABC)
- All 5 stub classes are importable without error
- Calling stub(thoughts=[]) raises NotImplementedError
- isinstance(stub, Operator) is True (structural duck-typing, no inheritance)
"""

from __future__ import annotations

import pytest

from pipeline.operators.base import Operator
from pipeline.operators.generate import Generate
from pipeline.operators.improve import Improve
from pipeline.operators.keep_best import KeepBest
from pipeline.operators.score import Score
from pipeline.operators.validate import Validate


def test_operator_protocol_is_runtime_checkable() -> None:
    """Operator must be runtime_checkable so isinstance() works in tests."""
    g = Generate(k=3)
    assert isinstance(g, Operator)


def test_generate_call_raises() -> None:
    """Generate.__call__ must raise NotImplementedError (Phase 7 fills body)."""
    g = Generate(k=3)
    with pytest.raises(NotImplementedError):
        g(thoughts=[])


def test_keep_best_call_raises() -> None:
    """KeepBest.__call__ must raise NotImplementedError (Phase 7 fills body)."""
    kb = KeepBest()
    with pytest.raises(NotImplementedError):
        kb(thoughts=[])


def test_improve_call_raises() -> None:
    """Improve.__call__ must raise NotImplementedError (Phase 7 fills body)."""
    imp = Improve()
    with pytest.raises(NotImplementedError):
        imp(thoughts=[])


def test_validate_call_raises() -> None:
    """Validate.__call__ must raise NotImplementedError (Phase 7 fills body)."""
    val = Validate()
    with pytest.raises(NotImplementedError):
        val(thoughts=[])


def test_score_call_raises() -> None:
    """Score.__call__ must raise NotImplementedError (Phase 7 fills body)."""
    sc = Score()
    with pytest.raises(NotImplementedError):
        sc(thoughts=[])


def test_import_does_not_raise() -> None:
    """All 5 operator classes must import cleanly with no side effects."""
    # If we got here, all imports at module top succeeded.
    assert Generate is not None
    assert KeepBest is not None
    assert Improve is not None
    assert Validate is not None
    assert Score is not None


def test_generate_stores_k() -> None:
    """Generate.__init__ must store k parameter."""
    g = Generate(k=5)
    assert g.k == 5


def test_isinstance_all_operators() -> None:
    """All 5 stubs satisfy isinstance(x, Operator) via structural duck-typing."""
    ops = [Generate(k=3), KeepBest(), Improve(), Validate(), Score()]
    for op in ops:
        assert isinstance(op, Operator), f"{type(op).__name__} does not satisfy Operator protocol"
