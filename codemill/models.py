from dataclasses import dataclass, field
from enum import Enum


class RunStatus(str, Enum):
    VERIFIED = "verified"
    ESCALATED = "escalated"
    FAILED = "failed"


@dataclass(frozen=True)
class SubTask:
    id: str
    objective: str
    acceptance_criteria: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()


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
class RunEvent:
    run_id: str
    name: str
    subtask_id: str | None = None
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class SubTaskResult:
    subtask_id: str
    status: RunStatus
    attempts: int
    diagnostics: tuple[str, ...] = ()
    events: tuple[RunEvent, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RunResult:
    status: RunStatus
    attempts: int
    run_id: str
    diagnostics: tuple[str, ...] = ()
    events: tuple[RunEvent, ...] = field(default_factory=tuple)
    subtasks: tuple[SubTaskResult, ...] = ()
