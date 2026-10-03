from dataclasses import dataclass, field
from enum import Enum


class RunStatus(str, Enum):
    VERIFIED = "verified"
    ESCALATED = "escalated"
    FAILED = "failed"


class VerificationPurpose(str, Enum):
    RED = "red"
    GREEN = "green"
    REGRESSION = "regression"
    FINAL = "final"


class VerificationFailureKind(str, Enum):
    EXPECTED_BEHAVIOR = "expected_behavior"
    OTHER = "other"


@dataclass(frozen=True)
class ExpectedScope:
    max_files: int = 3
    max_changed_lines: int = 100
    allow_dependencies: bool = False
    allow_public_api: bool = False
    allow_schema_changes: bool = False


@dataclass(frozen=True)
class SubTask:
    id: str
    objective: str
    acceptance_criteria: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    expected_scope: ExpectedScope = field(default_factory=ExpectedScope)


@dataclass(frozen=True)
class Task:
    objective: str
    acceptance_criteria: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()


@dataclass(frozen=True)
class DecompositionReview:
    accepted: bool
    findings: tuple[str, ...] = ()


@dataclass(frozen=True)
class VerificationTarget:
    paths: tuple[str, ...]
    selectors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProtectedTests:
    paths: tuple[str, ...]
    fingerprint: str


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    diagnostics: tuple[str, ...] = ()
    failure_kind: VerificationFailureKind | None = None


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
