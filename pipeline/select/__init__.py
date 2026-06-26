"""pipeline.select -- selection / ranking utilities (ADR-0012).

Pure-Python algorithms that turn a candidate population produced by the
v5 evolutionary search into a small, diverse, quality-floored survivor
set.  No LLM imports.  No network I/O.
"""

from pipeline.select.diversity_select import SelectCandidate, select_top_k

__all__ = ["SelectCandidate", "select_top_k"]
