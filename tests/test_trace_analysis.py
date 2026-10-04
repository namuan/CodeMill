from codemill.models import RunEvent, RunResult, RunStatus
from codemill.trace_analysis import analyze_trace


def test_classifies_protected_test_mutation_as_test_generation_failure():
    result = RunResult(
        RunStatus.FAILED,
        0,
        "run-protected",
        diagnostics=("test patch may not modify a pre-existing test file: tests/test_tools.py",),
        events=(
            RunEvent("run-protected", "plan_validated"),
            RunEvent("run-protected", "test_write_started"),
            RunEvent(
                "run-protected",
                "protected_test_mutation_attempt",
                diagnostics=("test patch may not modify a pre-existing test file: tests/test_tools.py",),
            ),
            RunEvent("run-protected", "run_failed"),
        ),
    )

    diagnosis = analyze_trace(result)

    assert diagnosis.stage == "test_generation"
    assert diagnosis.category == "protected_test_mutation"
    assert diagnosis.event == "protected_test_mutation_attempt"


def test_classifies_collection_error_as_invalid_red():
    result = RunResult(
        RunStatus.ESCALATED,
        0,
        "run-red",
        diagnostics=("pytest exited with status 2", "ImportError while collecting focused test"),
        events=(
            RunEvent("run-red", "plan_validated"),
            RunEvent("run-red", "test_patch_applied"),
            RunEvent("run-red", "red_verify_started"),
            RunEvent("run-red", "red_rejected"),
            RunEvent("run-red", "run_escalated"),
        ),
    )

    diagnosis = analyze_trace(result)

    assert diagnosis.stage == "red_verification"
    assert diagnosis.category == "invalid_test_collection"


def test_classifies_model_timeout_at_test_generation():
    result = RunResult(
        RunStatus.FAILED,
        0,
        "run-timeout",
        diagnostics=("LlamaServerError: request timed out",),
        events=(
            RunEvent("run-timeout", "plan_validated"),
            RunEvent("run-timeout", "test_write_started"),
            RunEvent("run-timeout", "subtask_failed"),
        ),
    )

    diagnosis = analyze_trace(result)

    assert diagnosis.stage == "test_generation"
    assert diagnosis.category == "model_timeout"


def test_marks_verified_run_as_complete():
    result = RunResult(RunStatus.VERIFIED, 1, "run-verified")

    diagnosis = analyze_trace(result)

    assert diagnosis.stage == "complete"
    assert diagnosis.category == "verified"
    assert diagnosis.event == "run_verified"
