from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .benchmark import BenchmarkCase, BenchmarkDatasetError, verify_benchmark_checkout
from .models import RunResult, RunStatus


class BenchmarkRunnerError(RuntimeError):
    pass


@dataclass(frozen=True)
class BenchmarkRun:
    case_id: str
    base_revision: str
    result: RunResult
    metrics: RunMetrics


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
                harness = self.harness_factory(case, worktree)
                tools_root = getattr(getattr(harness, "tools", None), "root", None)
                if tools_root is None or Path(tools_root).resolve() != worktree.resolve():
                    raise BenchmarkRunnerError("harness must target the disposable worktree")
                result = harness.run(case.task)
                if not isinstance(result, RunResult):
                    raise BenchmarkRunnerError("harness must return a RunResult")
                metrics = RunMetrics.from_result(result)
                return BenchmarkRun(case.id, case.base_revision, result, metrics)
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
