from dataclasses import dataclass, field
from enum import Enum


class RunStatus(str, Enum):
    VERIFIED = "verified"
    EXHAUSTED = "exhausted"
    ESCALATED = "escalated"


@dataclass(frozen=True)
class Task:
    objective: str
    acceptance_criteria: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class RunResult:
    status: RunStatus
    attempts: int
    diagnostics: tuple[str, ...] = ()
    events: tuple[str, ...] = field(default_factory=tuple)
