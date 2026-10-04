import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Sequence, TextIO

from .benchmark import BenchmarkDatasetError, load_benchmark_cases
from .evaluation import (
    BenchmarkRunner,
    BenchmarkRunnerError,
    EvaluationReportError,
    EvaluationSummary,
    write_evaluation_report,
)
from .harness import CodingHarness
from .llama_cpp import LlamaCppModelDriver
from .pytest_verifier import PytestVerifier
from .repository_tools import LocalRepositoryTools


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codemill-benchmark")
    parser.add_argument("--dataset", default="benchmarks/cases.jsonl")
    parser.add_argument("--repository-root", default=".")
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--report", required=True)
    parser.add_argument("--model-identifier", required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:9090")
    parser.add_argument("--server-model", default="local-model")
    parser.add_argument("--temp-root")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--retries", type=int, default=0)
    parser.add_argument("--max-tokens", type=int, default=4096)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        cases = load_benchmark_cases(arguments.dataset, arguments.repository_root)
        if arguments.case_id:
            selected = set(arguments.case_id)
            known = {case.id for case in cases}
            missing = sorted(selected - known)
            if missing:
                raise BenchmarkDatasetError(
                    f"unknown benchmark case id: {missing[0]}"
                )
            cases = tuple(case for case in cases if case.id in selected)
        report_path = Path(arguments.report).expanduser().resolve()
        for case in cases:
            try:
                report_path.relative_to(case.repository)
            except ValueError:
                continue
            raise BenchmarkRunnerError(
                "evaluation reports must be written outside benchmark repositories"
            )
        temp_root = Path(arguments.temp_root).expanduser().resolve() if arguments.temp_root else None
        if temp_root is not None:
            for case in cases:
                try:
                    temp_root.relative_to(case.repository)
                except ValueError:
                    continue
                raise BenchmarkRunnerError(
                    "temporary worktrees must be outside benchmark repositories"
                )
            temp_root.mkdir(parents=True, exist_ok=True)
        runner = BenchmarkRunner(
            lambda case, worktree: CodingHarness(
                LlamaCppModelDriver(
                    endpoint=arguments.endpoint,
                    model=arguments.server_model,
                    timeout=arguments.timeout,
                    retries=arguments.retries,
                    max_tokens=arguments.max_tokens,
                ),
                LocalRepositoryTools(worktree),
                PytestVerifier(worktree, timeout=arguments.timeout),
            ),
            temp_root=temp_root,
        )
        runs = runner.run_cases(cases)
        report_path = write_evaluation_report(
            report_path,
            runs,
            arguments.model_identifier,
        )
        summary = EvaluationSummary.from_metrics(tuple(run.metrics for run in runs))
    except (BenchmarkDatasetError, BenchmarkRunnerError, EvaluationReportError, OSError, ValueError) as error:
        _write_json(sys.stderr, {"error": f"{type(error).__name__}: {error}"})
        return 2

    _write_json(
        sys.stdout,
        {
            "report": str(report_path),
            "summary": {**asdict(summary), "success_rate": summary.success_rate},
            "runs": [
                {"case_id": run.case_id, "status": run.result.status.value}
                for run in runs
            ],
        },
    )
    return 0


def _write_json(stream: TextIO, value: dict[str, object]) -> None:
    stream.write(json.dumps(value, indent=2) + "\n")
