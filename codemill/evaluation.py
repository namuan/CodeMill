from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .benchmark import BenchmarkCase, BenchmarkDatasetError, verify_benchmark_checkout
from .models import GitStatus, InferenceMetrics, RunResult, RunStatus, Task


class BenchmarkRunnerError(RuntimeError):
    pass


class EvaluationReportError(RuntimeError):
    pass


@dataclass(frozen=True)
class BenchmarkRun:
    case_id: str
    base_revision: str
    result: RunResult
    metrics: RunMetrics
    reference_revision: str | None = None
    task: Task | None = None
    initial_git_status: GitStatus | None = None
    final_git_status: GitStatus | None = None
    final_diff: str = ""


class BenchmarkRunner:
    def __init__(
        self,
        harness_factory: Callable[[BenchmarkCase, Path], object],
        temp_root: str | Path | None = None,
        git_timeout: float = 30.0,
    ):
        if git_timeout <= 0:
            raise ValueError("git_timeout must be positive")
        self.harness_factory = harness_factory
        self.temp_root = Path(temp_root).resolve() if temp_root is not None else None
        self.git_timeout = git_timeout

    def run_case(self, case: BenchmarkCase) -> BenchmarkRun:
        try:
            verify_benchmark_checkout(case.repository, case.base_revision)
        except BenchmarkDatasetError as error:
            raise BenchmarkRunnerError(str(error)) from error

        if self.temp_root is not None:
            try:
                self.temp_root.relative_to(case.repository)
            except ValueError:
                pass
            else:
                raise BenchmarkRunnerError("temporary worktrees must be outside the source repository")

        with tempfile.TemporaryDirectory(prefix="codemill-eval-", dir=self.temp_root) as temporary:
            worktree = Path(temporary) / "repository"
            self._git(case.repository, "worktree", "add", "--detach", str(worktree), case.base_revision)
            try:
                verify_benchmark_checkout(worktree, case.base_revision)
                checkout = self._git_result(worktree, "rev-parse", "HEAD")
                if checkout.returncode != 0 or checkout.stdout.strip().lower() != case.base_revision.lower():
                    raise BenchmarkRunnerError("disposable worktree is not at base_revision")
                harness = self.harness_factory(case, worktree)
                tools_root = getattr(getattr(harness, "tools", None), "root", None)
                if tools_root is None or Path(tools_root).resolve() != worktree.resolve():
                    raise BenchmarkRunnerError("harness must target the disposable worktree")
                initial_git_status = harness.tools.git_status()
                if not initial_git_status.clean:
                    raise BenchmarkRunnerError("disposable worktree must start clean")
                model = getattr(harness, "model", None)
                calls = getattr(model, "calls", ())
                calls_before = len(calls)
                result = harness.run(case.task)
                if not isinstance(result, RunResult):
                    raise BenchmarkRunnerError("harness must return a RunResult")
                model_calls = tuple(getattr(model, "calls", ())[calls_before:])
                metrics = RunMetrics.from_result(result, model_calls)
                final_git_status = harness.tools.git_status()
                final_diff = harness.tools.git_diff()
                return BenchmarkRun(
                    case.id,
                    case.base_revision,
                    result,
                    metrics,
                    case.reference_revision,
                    case.task,
                    initial_git_status,
                    final_git_status,
                    final_diff,
                )
            finally:
                removal = self._git_result(
                    case.repository,
                    "worktree",
                    "remove",
                    "--force",
                    str(worktree),
                )
                if removal.returncode != 0:
                    self._git_result(case.repository, "worktree", "prune")
                    shutil.rmtree(worktree, ignore_errors=True)
                    raise BenchmarkRunnerError(
                        removal.stderr.strip() or "could not remove benchmark worktree"
                    )

    def run_cases(self, cases: tuple[BenchmarkCase, ...]) -> tuple[BenchmarkRun, ...]:
        return tuple(self.run_case(case) for case in cases)

    def _git(self, repository: Path, *arguments: str) -> None:
        result = self._git_result(repository, *arguments)
        if result.returncode != 0:
            raise BenchmarkRunnerError(result.stderr.strip() or "benchmark Git operation failed")

    def _git_result(self, repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=self.git_timeout,
        )


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
    test_mutation_attempts: int
    changed_files: tuple[str, ...]
    model_calls: int
    failed_model_calls: int
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    inference_seconds: float

    @classmethod
    def from_result(
        cls,
        result: RunResult,
        model_calls: tuple[InferenceMetrics, ...] = (),
    ) -> RunMetrics:
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
            event_names.count("protected_test_mutation_attempt"),
            tuple(sorted(changed_files)),
            len(model_calls),
            sum(not call.succeeded for call in model_calls),
            cls._sum_tokens(model_calls, "prompt_tokens"),
            cls._sum_tokens(model_calls, "completion_tokens"),
            cls._sum_tokens(model_calls, "total_tokens"),
            sum(call.duration_seconds for call in model_calls),
        )

    @staticmethod
    def _sum_tokens(calls: tuple[InferenceMetrics, ...], field: str) -> int | None:
        if not calls or any(getattr(call, field) is None for call in calls):
            return None
        return sum(getattr(call, field) for call in calls)


@dataclass(frozen=True)
class EvaluationSummary:
    total_runs: int
    verified_runs: int
    escalated_runs: int
    failed_runs: int
    repair_attempts: int
    test_mutation_attempts: int = 0
    model_calls: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    inference_seconds: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.total_runs == 0:
            return 0.0
        return self.verified_runs / self.total_runs

    @classmethod
    def from_results(cls, results: tuple[RunResult, ...]) -> EvaluationSummary:
        metrics = tuple(RunMetrics.from_result(result) for result in results)
        return cls.from_metrics(metrics)

    @classmethod
    def from_metrics(cls, metrics: tuple[RunMetrics, ...]) -> EvaluationSummary:
        return cls(
            len(metrics),
            sum(metric.status is RunStatus.VERIFIED for metric in metrics),
            sum(metric.status is RunStatus.ESCALATED for metric in metrics),
            sum(metric.status is RunStatus.FAILED for metric in metrics),
            sum(metric.repairs for metric in metrics),
            sum(metric.test_mutation_attempts for metric in metrics),
            sum(metric.model_calls for metric in metrics),
            cls._sum_metric_tokens(metrics, "prompt_tokens"),
            cls._sum_metric_tokens(metrics, "completion_tokens"),
            cls._sum_metric_tokens(metrics, "total_tokens"),
            sum(metric.inference_seconds for metric in metrics),
        )

    @staticmethod
    def _sum_metric_tokens(metrics: tuple[RunMetrics, ...], field: str) -> int | None:
        if not metrics or any(getattr(metric, field) is None for metric in metrics):
            return None
        return sum(getattr(metric, field) for metric in metrics)


def write_evaluation_report(
    path: str | Path,
    runs: tuple[BenchmarkRun, ...],
    model_identifier: str,
) -> Path:
    if not model_identifier.strip():
        raise ValueError("model_identifier must not be empty")
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise EvaluationReportError(f"evaluation report already exists: {destination}")
    metrics = tuple(run.metrics for run in runs)
    summary = EvaluationSummary.from_metrics(metrics)
    document = {
        "format_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model_identifier": model_identifier,
        "python_version": sys.version.split()[0],
        "summary": {
            **asdict(summary),
            "success_rate": summary.success_rate,
        },
        "runs": [
            {
                "case_id": run.case_id,
                "base_revision": run.base_revision,
                "reference_revision": run.reference_revision,
                "task": asdict(run.task) if run.task is not None else None,
                "initial_git_status": (
                    asdict(run.initial_git_status) if run.initial_git_status is not None else None
                ),
                "final_git_status": (
                    asdict(run.final_git_status) if run.final_git_status is not None else None
                ),
                "final_diff": run.final_diff,
                "metrics": asdict(run.metrics),
                "result": asdict(run.result),
            }
            for run in runs
        ],
    }
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}-",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary = Path(output.name)
            output.write(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
        os.replace(temporary, destination)
        temporary = None
        return destination
    except OSError as error:
        raise EvaluationReportError(f"could not write evaluation report: {error}") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
