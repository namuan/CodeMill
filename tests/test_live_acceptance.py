import os
import subprocess

import pytest

from codemill.artifacts import ArtifactWriter
from codemill.harness import CodingHarness
from codemill.llama_cpp import LlamaCppModelDriver
from codemill.models import ExpectedScope, RunStatus, Task
from codemill.pytest_verifier import PytestVerifier
from codemill.repository_tools import LocalRepositoryTools


@pytest.mark.skipif(
    os.environ.get("CODEMILL_RUN_LIVE_ACCEPTANCE") != "1",
    reason="set CODEMILL_RUN_LIVE_ACCEPTANCE=1 to use the local llama.cpp server",
)
def test_real_model_completes_tdd_workflow_and_writes_artifacts(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "src").mkdir()
    (repository / "src" / "greetings.py").write_text(
        "def greeting(name: str) -> str:\n    return \"Hello\"\n"
    )
    subprocess.run(["git", "-C", str(repository), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.email", "acceptance@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.name", "CodeMill Acceptance"],
        check=True,
    )
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-qm", "seed fixture"], check=True)

    task = Task(
        "Fix greeting(name) to return a personalized greeting.",
        ('greeting("Ada") returns "Hello, Ada!"',),
        ("Preserve the existing function signature and avoid unrelated changes.",),
        ExpectedScope(max_files=2, max_changed_lines=40),
    )
    tools = LocalRepositoryTools(repository)
    initial_status = tools.git_status()
    verifier = PytestVerifier(repository, timeout=120)
    result = CodingHarness(
        LlamaCppModelDriver(timeout=180, retries=0, max_tokens=4096),
        tools,
        verifier,
    ).run(task)

    assert result.status is RunStatus.VERIFIED, result.diagnostics
    assert result.subtasks
    assert all(subtask.status is RunStatus.VERIFIED for subtask in result.subtasks)
    assert (repository / "src" / "greetings.py").read_text() != (
        "def greeting(name: str) -> str:\n    return \"Hello\"\n"
    )
    final_status = tools.git_status()
    assert not final_status.clean
    assert "src/greetings.py" in final_status.changed_paths
    accepted_test_paths = {
        path
        for subtask in result.subtasks
        for record in subtask.verifications
        if record.purpose.value == "red" and record.target is not None
        for path in record.target.paths
    }
    assert accepted_test_paths
    assert accepted_test_paths <= set(final_status.changed_paths)

    artifacts = ArtifactWriter(tmp_path / "artifacts").write(
        task,
        result,
        initial_status,
        final_status,
        tools.git_diff(),
    )

    assert (artifacts / "plan.json").exists()
    assert (artifacts / "trace.jsonl").exists()
    assert (artifacts / "verification.json").exists()
    assert "greeting" in (artifacts / "final.diff").read_text()
