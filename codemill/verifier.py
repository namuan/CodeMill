from typing import Protocol

from .models import VerificationPurpose, VerificationResult, VerificationTarget


class Verifier(Protocol):
    """Deterministic judge for a candidate repository state."""

    def verify(
        self,
        purpose: VerificationPurpose,
        target: VerificationTarget | None = None,
    ) -> VerificationResult: ...
