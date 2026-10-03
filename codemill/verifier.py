from typing import Protocol

from .models import VerificationResult


class Verifier(Protocol):
    """Deterministic judge for a candidate repository state."""

    def verify(self) -> VerificationResult: ...
