from __future__ import annotations

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
    NO_CHANGE = "no_change"
    FINAL = "final"


class VerificationFailureKind(str, Enum):
    EXPECTED_BEHAVIOR = "expected_behavior"
    OTHER = "other"


class ScopeViolationError(PermissionError):
    pass


class ProtectedTestMutationError(PermissionError):
    pass


@dataclass(frozen=True)
class ExpectedScope:
    max_files: int = 3
    max_changed_lines: int = 100
    allow_dependencies: bool = False
    allow_public_api: bool = False
    allow_schema_changes: bool = False
    planned_paths: tuple[str, ...] = ()


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
    expected_scope: ExpectedScope = field(default_factory=ExpectedScope)


@dataclass(frozen=True)
class DecompositionReview:
    accepted: bool
    findings: tuple[str, ...] = ()
    already_satisfied: bool = False
    evidence: tuple[str, ...] = ()
    test_target: VerificationTarget | None = None


@dataclass(frozen=True)
class GitStatus:
    commit: str | None
    branch: str
    clean: bool
    changed_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class VerificationTarget:
    paths: tuple[str, ...]
    selectors: tuple[str, ...] = ()
    expected_missing_symbols: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProtectedTests:
    paths: tuple[str, ...]
    fingerprint: str


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    diagnostics: tuple[str, ...] = ()
    failure_kind: VerificationFailureKind | None = None
    command: tuple[str, ...] = ()
    exit_code: int | None = None
    duration_seconds: float | None = None


@dataclass(frozen=True)
class VerificationRecord:
    purpose: VerificationPurpose
    target: VerificationTarget | None
    result: VerificationResult


@dataclass(frozen=True)
class InferenceMetrics:
    operation: str
    duration_seconds: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    succeeded: bool = True
    error: str | None = None


@dataclass(frozen=True)
class RunEvent:
    run_id: str
    name: str
    subtask_id: str | None = None
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class VerifiedSliceRecord:
    subtask_id: str
    behavior: str
    acceptance_criteria: tuple[str, ...]
    accepted_test_paths: tuple[str, ...]
    changed_files: tuple[str, ...]
    verification_purposes: tuple[VerificationPurpose, ...]


@dataclass(frozen=True)
class SubTaskResult:
    subtask_id: str
    status: RunStatus
    attempts: int
    diagnostics: tuple[str, ...] = ()
    events: tuple[RunEvent, ...] = field(default_factory=tuple)
    verified_slice: VerifiedSliceRecord | None = None
    verifications: tuple[VerificationRecord, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RunResult:
    status: RunStatus
    attempts: int
    run_id: str
    diagnostics: tuple[str, ...] = ()
    events: tuple[RunEvent, ...] = field(default_factory=tuple)
    subtasks: tuple[SubTaskResult, ...] = ()
    planned_subtasks: tuple[SubTask, ...] = ()
    final_verification: VerificationRecord | None = None
    pre_final_verifications: tuple[VerificationRecord, ...] = ()

    @property
    def verifications(self) -> tuple[VerificationRecord, ...]:
        records = (
            *self.pre_final_verifications,
            *(
                record
                for subtask in self.subtasks
                for record in subtask.verifications
            ),
        )
        if self.final_verification is None:
            return records
        return (*records, self.final_verification)

    @property
    def verified_slices(self) -> tuple[VerifiedSliceRecord, ...]:
        return tuple(
            result.verified_slice
            for result in self.subtasks
            if result.verified_slice is not None
        )
