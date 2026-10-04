from codemill.evaluation import EvaluationSummary, RunMetrics
from codemill.models import (
    RunEvent,
    RunResult,
    RunStatus,
    SubTaskResult,
    VerificationPurpose,
    VerifiedSliceRecord,
)


def test_measures_harness_outcomes_without_hidden_model_reasoning():
    run = RunResult(
        RunStatus.VERIFIED,
        2,
        "run-1",
        events=(
            RunEvent("run-1", "red_confirmed", "ST-001"),
            RunEvent("run-1", "repair_started", "ST-001"),
            RunEvent("run-1", "regression_verify_passed", "ST-001"),
            RunEvent("run-1", "final_verify_passed"),
        ),
        subtasks=(
            SubTaskResult(
                "ST-001",
                RunStatus.VERIFIED,
                2,
                verified_slice=VerifiedSliceRecord(
                    "ST-001",
                    "return greeting",
                    ("name is returned",),
                    ("tests/test_greeting.py",),
                    ("src/greeting.py", "tests/test_greeting.py"),
                    (
                        VerificationPurpose.RED,
                        VerificationPurpose.GREEN,
                        VerificationPurpose.REGRESSION,
                    ),
                ),
            ),
        ),
    )

    metrics = RunMetrics.from_result(run)

    assert metrics.status is RunStatus.VERIFIED
    assert metrics.subtask_count == 1
    assert metrics.verified_subtasks == 1
    assert metrics.valid_reds == 1
    assert metrics.repairs == 1
    assert metrics.scope_violations == 0
    assert metrics.changed_files == ("src/greeting.py", "tests/test_greeting.py")


def test_aggregates_success_escalation_and_repair_metrics():
    runs = (
        RunResult(RunStatus.VERIFIED, 1, "run-1"),
        RunResult(RunStatus.ESCALATED, 0, "run-2"),
        RunResult(
            RunStatus.FAILED,
            2,
            "run-3",
            events=(RunEvent("run-3", "repair_started"),),
        ),
    )

    summary = EvaluationSummary.from_results(runs)

    assert summary.total_runs == 3
    assert summary.verified_runs == 1
    assert summary.escalated_runs == 1
    assert summary.failed_runs == 1
    assert summary.repair_attempts == 1
    assert summary.success_rate == 1 / 3


def test_empty_evaluation_has_zero_success_rate():
    summary = EvaluationSummary.from_results(())

    assert summary.total_runs == 0
    assert summary.success_rate == 0.0
