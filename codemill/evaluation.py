from dataclasses import dataclass

from .models import RunResult, RunStatus


@dataclass(frozen=True)
class RunMetrics:
    run_id: str
    status: RunStatus
    subtask_count: int
    verified_subtasks: int
    valid_reds: int
    rejected_reds: int
    repairs: int
    scope_violations: int
    changed_files: tuple[str, ...]

    @classmethod
    def from_result(cls, result: RunResult) -> RunMetrics:
        event_names = tuple(event.name for event in result.events)
        changed_files = {
            path
            for verified_slice in result.verified_slices
            for path in verified_slice.changed_files
        }
        return cls(
            result.run_id,
            result.status,
            len(result.subtasks),
            sum(subtask.status is RunStatus.VERIFIED for subtask in result.subtasks),
            event_names.count("red_confirmed"),
            event_names.count("red_rejected"),
            event_names.count("repair_started"),
            event_names.count("scope_violation"),
            tuple(sorted(changed_files)),
        )


@dataclass(frozen=True)
class EvaluationSummary:
    total_runs: int
    verified_runs: int
    escalated_runs: int
    failed_runs: int
    repair_attempts: int

    @property
    def success_rate(self) -> float:
        if self.total_runs == 0:
            return 0.0
        return self.verified_runs / self.total_runs

    @classmethod
    def from_results(cls, results: tuple[RunResult, ...]) -> EvaluationSummary:
        metrics = tuple(RunMetrics.from_result(result) for result in results)
        return cls(
            len(metrics),
            sum(metric.status is RunStatus.VERIFIED for metric in metrics),
            sum(metric.status is RunStatus.ESCALATED for metric in metrics),
            sum(metric.status is RunStatus.FAILED for metric in metrics),
            sum(metric.repairs for metric in metrics),
        )
