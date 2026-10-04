import json
import subprocess
from types import SimpleNamespace

import pytest

from codemill.benchmark import load_benchmark_cases
from codemill.evaluation import BenchmarkRunner, BenchmarkRunnerError
from codemill.models import InferenceMetrics, RunResult, RunStatus
from codemill.repository_tools import LocalRepositoryTools


def create_repository(path):
    path.mkdir()
    (path / "sample.py").write_text("value = 1\n")
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "tests@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "CodeMill Tests"], check=True)
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "fixture"], check=True)
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def load_case(tmp_path, repository, revision):
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "id": "case-1",
                "repository": repository,
                "base_revision": revision,
                "task": {
                    "objective": "Change value",
                    "acceptance_criteria": ["value is 2"],
                    "constraints": [],
                },
            }
        )
        + "\n"
    )
    return load_benchmark_cases(dataset)[0]


class Harness:
    def __init__(self, root, result):
        self.tools = LocalRepositoryTools(root)
        self.result = result
        self.task = None
        self.model = SimpleNamespace(calls=[])

    def run(self, task):
        self.task = task
        self.model.calls.append(InferenceMetrics("decompose", 0.5, 10, 2, 12))
        (self.tools.root / "sample.py").write_text("value = 2\n")
        return self.result


def test_runner_uses_and_removes_a_disposable_worktree(tmp_path):
    repository = tmp_path / "fixture"
    revision = create_repository(repository)
    case = load_case(tmp_path, "fixture", revision)
    result = RunResult(RunStatus.VERIFIED, 1, "run-1")
    observed_worktrees = []

    def harness_factory(current_case, worktree):
        observed_worktrees.append(worktree)
        harness = Harness(worktree, result)
        assert harness.tools.git_status().commit == revision
        assert harness.tools.git_status().clean
        return harness

    benchmark_run = BenchmarkRunner(harness_factory).run_case(case)

    assert benchmark_run.case_id == "case-1"
    assert benchmark_run.result is result
    assert benchmark_run.metrics.verified_subtasks == 0
    assert benchmark_run.metrics.total_tokens == 12
    assert benchmark_run.metrics.inference_seconds == 0.5
    assert benchmark_run.initial_git_status.clean
    assert benchmark_run.final_git_status.changed_paths == ("sample.py",)
    assert "+value = 2" in benchmark_run.final_diff
    assert observed_worktrees[0] != repository
    assert not observed_worktrees[0].exists()
    assert (repository / "sample.py").read_text() == "value = 1\n"
    assert LocalRepositoryTools(repository).git_status().clean


def test_runner_rejects_a_harness_pointing_at_the_source_repository(tmp_path):
    repository = tmp_path / "fixture"
    revision = create_repository(repository)
    case = load_case(tmp_path, "fixture", revision)

    with pytest.raises(BenchmarkRunnerError, match="must target the disposable worktree"):
        BenchmarkRunner(lambda current_case, worktree: Harness(repository, RunResult(RunStatus.FAILED, 0, "run"))).run_case(case)

    assert (repository / "sample.py").read_text() == "value = 1\n"
    assert LocalRepositoryTools(repository).git_status().clean


def test_runner_checks_out_historical_base_revision(tmp_path):
    repository = tmp_path / "fixture"
    revision = create_repository(repository)
    case = load_case(tmp_path, "fixture", revision)
    (repository / "sample.py").write_text("value = 3\n")
    subprocess.run(["git", "-C", str(repository), "add", "sample.py"], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-qm", "advance"], check=True)

    def harness_factory(current_case, worktree):
        harness = Harness(worktree, RunResult(RunStatus.VERIFIED, 1, "historical"))
        assert harness.tools.git_status().commit == revision
        assert (worktree / "sample.py").read_text() == "value = 1\n"
        return harness

    benchmark_run = BenchmarkRunner(harness_factory).run_case(case)

    assert benchmark_run.result.status is RunStatus.VERIFIED
    assert (repository / "sample.py").read_text() == "value = 3\n"
    assert LocalRepositoryTools(repository).git_status().clean
