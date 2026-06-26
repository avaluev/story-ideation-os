"""Provenance record for a verified claim.

Captures everything needed to defend a number to a hostile investor: the URL
that was fetched, the HTTP status it returned, when it was fetched, a SHA-256 of
the payload (so the evidence is tamper-evident), the direct quote that supports
the claim, and whether the fetched content actually supports the claimed value.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Provenance:
    """Tamper-evident evidence record for one claim."""

    url: str
    http_status: int | None
    fetched_at: str
    content_sha256: str | None
    quote: str
    supports_claim: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def empty(cls) -> Provenance:
        """A null provenance — used when no source was fetched at all."""
        return cls(
            url="",
            http_status=None,
            fetched_at="",
            content_sha256=None,
            quote="",
            supports_claim=False,
        )
