import json
from pathlib import Path

from codemill.benchmark import BenchmarkCase
from codemill.evaluation import BenchmarkRun, RunMetrics
from codemill.models import RunResult, RunStatus, Task


def benchmark_case(repository):
    return BenchmarkCase(
        "case-001",
        repository,
        "a" * 40,
        Task("implement feature", ("feature works",)),
        "b" * 40,
    )


def benchmark_run(case):
    result = RunResult(RunStatus.VERIFIED, 1, "run-001")
    return BenchmarkRun(
        case.id,
        case.base_revision,
        result,
        RunMetrics.from_result(result),
        case.reference_revision,
        case.task,
    )


def test_runs_selected_benchmark_cases_and_writes_report(monkeypatch, capsys, tmp_path):
    from codemill import benchmark_cli

    repository = tmp_path / "repository"
    repository.mkdir()
    case = benchmark_case(repository)
    received = {}

    class Runner:
        def __init__(self, harness_factory, temp_root=None):
            received["harness_factory"] = harness_factory
            received["temp_root"] = temp_root

        def run_cases(self, cases):
            received["cases"] = cases
            return (benchmark_run(case),)

    monkeypatch.setattr(benchmark_cli, "load_benchmark_cases", lambda path, root: (case,))
    monkeypatch.setattr(benchmark_cli, "BenchmarkRunner", Runner)
    report_path = tmp_path / "results" / "report.json"

    exit_code = benchmark_cli.main(
        [
            "--dataset",
            str(tmp_path / "cases.jsonl"),
            "--repository-root",
            str(tmp_path),
            "--case-id",
            "case-001",
            "--report",
            str(report_path),
            "--model-identifier",
            "local-model-q8",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    report = json.loads(report_path.read_text())
    assert exit_code == 0
    assert received["cases"] == (case,)
    assert report["model_identifier"] == "local-model-q8"
    assert report["runs"][0]["case_id"] == "case-001"
    assert output["summary"]["success_rate"] == 1.0


def test_refuses_report_paths_inside_benchmark_repository(monkeypatch, capsys, tmp_path):
    from codemill import benchmark_cli

    repository = tmp_path / "repository"
    repository.mkdir()
    case = benchmark_case(repository)
    monkeypatch.setattr(benchmark_cli, "load_benchmark_cases", lambda path, root: (case,))

    exit_code = benchmark_cli.main(
        [
            "--report",
            str(repository / "report.json"),
            "--model-identifier",
            "local-model",
        ]
    )

    assert exit_code == 2
    assert "outside benchmark repositories" in json.loads(capsys.readouterr().err)["error"]
