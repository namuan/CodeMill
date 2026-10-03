from typing import Protocol

from .models import VerificationPurpose, VerificationResult


class Verifier(Protocol):
    """Deterministic judge for a candidate repository state."""

    def verify(self, purpose: VerificationPurpose) -> VerificationResult: ...
