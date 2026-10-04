import json
from dataclasses import replace

import pytest

from codemill.artifacts import ArtifactWriter, ArtifactWriterError
from codemill.models import (
    GitStatus,
    ProtectedTests,
    RunEvent,
    RunResult,
    RunStatus,
    SubTask,
    SubTaskResult,
    Task,
    VerificationFailureKind,
    VerificationPurpose,
    VerificationRecord,
    VerificationResult,
    VerificationTarget,
    VerifiedSliceRecord,
)


def verified_result(run_id="run-123"):
    subtask = SubTask(
        "ST-001",
        "return greeting",
        ("Ada receives Hello, Ada!",),
        depends_on=(),
    )
    target = VerificationTarget(("tests/test_greeting.py",))
    subtask_verifications = (
        VerificationRecord(
            VerificationPurpose.RED,
            target,
            VerificationResult(
                False,
                ("pytest exited with status 1", "AssertionError"),
                VerificationFailureKind.EXPECTED_BEHAVIOR,
                ("python", "-m", "pytest", "tests/test_greeting.py"),
                1,
                0.3,
            ),
        ),
        VerificationRecord(
            VerificationPurpose.GREEN,
            target,
            VerificationResult(
                True,
                ("pytest passed",),
                command=("python", "-m", "pytest", "tests/test_greeting.py"),
                exit_code=0,
                duration_seconds=0.4,
            ),
        ),
    )
    slice_record = VerifiedSliceRecord(
        "ST-001",
        "return greeting",
        ("Ada receives Hello, Ada!",),
        target.paths,
        ("src/greeting.py", "tests/test_greeting.py"),
        (VerificationPurpose.RED, VerificationPurpose.GREEN, VerificationPurpose.REGRESSION),
    )
    events = (
        RunEvent(run_id, "run_started"),
        RunEvent(run_id, "repair_started", "ST-001", ("first patch failed",)),
        RunEvent(run_id, "subtask_verified", "ST-001"),
        RunEvent(run_id, "final_verify_passed"),
        RunEvent(run_id, "run_verified"),
    )
    subtask_result = SubTaskResult(
        "ST-001",
        RunStatus.VERIFIED,
        2,
        events=events[1:3],
        verified_slice=slice_record,
        verifications=subtask_verifications,
    )
    final_record = VerificationRecord(
        VerificationPurpose.FINAL,
        None,
        VerificationResult(
            True,
            ("pytest passed",),
            command=("python", "-m", "pytest", "-q"),
            exit_code=0,
            duration_seconds=0.5,
        ),
    )
    return Task("Implement greeting", ("Ada receives Hello, Ada!",)), RunResult(
        RunStatus.VERIFIED,
        2,
        run_id,
        events=events,
        subtasks=(subtask_result,),
        planned_subtasks=(subtask,),
        final_verification=final_record,
    )


def test_writes_complete_reviewable_run_bundle(tmp_path):
    task, result = verified_result()
    initial = GitStatus("base-sha", "main", True, ())
    final = GitStatus("base-sha", "main", False, ("src/greeting.py", "tests/test_greeting.py"))

    run_directory = ArtifactWriter(tmp_path).write(
        task,
        result,
        initial,
        final,
        "diff --git a/src/greeting.py b/src/greeting.py\n+return greeting\n",
    )

    assert run_directory == tmp_path / "run-123"
    assert json.loads((run_directory / "run.json").read_text())["status"] == "verified"
    plan = json.loads((run_directory / "plan.json").read_text())
    assert plan["subtasks"][0]["depends_on"] == []
    assert (run_directory / "trace.jsonl").read_text().count("\n") == len(result.events)
    changed = json.loads((run_directory / "changed-files.json").read_text())
    assert changed["changed_paths"] == ["src/greeting.py", "tests/test_greeting.py"]
    verification = json.loads((run_directory / "verification.json").read_text())
    assert [item["purpose"] for item in verification["records"]] == [
        "red",
        "green",
        "final",
    ]
    assert verification["records"][0]["result"]["exit_code"] == 1
    assert verification["records"][0]["result"]["command"][-1] == "tests/test_greeting.py"
    assert json.loads((run_directory / "repairs.json").read_text())["attempts"][0]["subtask_id"] == "ST-001"
    assert "Implement greeting" in (run_directory / "result.md").read_text()
    assert (run_directory / "final.diff").read_text().startswith("diff --git")
    assert (run_directory / "manifest.json").exists()


def test_persists_no_change_verification_and_outcome(tmp_path):
    task, result = verified_result("already-satisfied")
    target = VerificationTarget(("tests/test_greeting.py",), ("test_greeting",))
    result = replace(
        result,
        pre_final_verifications=(
            VerificationRecord(
                VerificationPurpose.NO_CHANGE,
                target,
                VerificationResult(
                    True,
                    ("existing acceptance test passed",),
                    command=("python", "-B", "-m", "pytest", "tests/test_greeting.py::test_greeting"),
                    exit_code=0,
                    duration_seconds=0.2,
                ),
            ),
        ),
    )

    run_directory = ArtifactWriter(tmp_path).write(
        task,
        result,
        GitStatus("base-sha", "main", True, ()),
        GitStatus("base-sha", "main", True, ()),
        "",
    )

    verification = json.loads((run_directory / "verification.json").read_text())
    assert verification["records"][0]["purpose"] == "no_change"
    assert "Already satisfied" in (run_directory / "result.md").read_text()


def test_refuses_to_overwrite_existing_run_bundle(tmp_path):
    task, result = verified_result()
    writer = ArtifactWriter(tmp_path)
    writer.write(task, result, GitStatus(None, "", True), GitStatus(None, "", True), "")

    with pytest.raises(ArtifactWriterError, match="already exists"):
        writer.write(task, result, GitStatus(None, "", True), GitStatus(None, "", True), "")


def test_rejects_unsafe_run_ids(tmp_path):
    task, result = verified_result("../escape")

    with pytest.raises(ArtifactWriterError, match="unsafe run id"):
        ArtifactWriter(tmp_path).write(
            task,
            result,
            GitStatus(None, "", True),
            GitStatus(None, "", True),
            "",
        )
