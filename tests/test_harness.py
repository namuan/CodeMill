from codemill.harness import CodingHarness
from codemill.models import RunStatus, SubTask, Task, VerificationResult


class FakeTools:
    def __init__(self):
        self.patches = []

    def search_text(self, query): return ""
    def read_file(self, path, start=None, end=None): return ""
    def apply_patch(self, patch): self.patches.append(patch)


class FakeModel:
    def __init__(self, subtasks=None):
        self.subtasks = subtasks or (SubTask("ST-001", "fix bug"),)

    def decompose(self, task, tools):
        return self.subtasks

    def locate_and_plan(self, task, tools): return f"plan {task.id}"
    def create_patch(self, task, plan, tools): return f"patch {task.id}"
    def repair_patch(self, task, diagnostics, tools): return f"repair {task.id}"


class SequenceVerifier:
    def __init__(self, results): self.results = iter(results)
    def verify(self): return next(self.results)


def test_repairs_subtask_then_runs_final_verification():
    tools = FakeTools()
    verifier = SequenceVerifier([
        VerificationResult(False, ("type error",)),
        VerificationResult(True),
        VerificationResult(True),
    ])

    result = CodingHarness(FakeModel(), tools, verifier).run(Task("fix bug"))

    assert result.status is RunStatus.VERIFIED
    assert result.attempts == 2
    assert tools.patches == ["patch ST-001", "repair ST-001"]
    assert result.subtasks[0].status is RunStatus.VERIFIED
    assert "final_verify_started" in [event.name for event in result.events]
    assert all(event.run_id == result.run_id for event in result.events)
    assert all(event.subtask_id == "ST-001" for event in result.subtasks[0].events)


def test_executes_dependency_ordered_subtasks():
    subtasks = (
        SubTask("ST-002", "integrate primitive", depends_on=("ST-001",)),
        SubTask("ST-001", "add primitive"),
    )
    tools = FakeTools()
    verifier = SequenceVerifier([
        VerificationResult(True),
        VerificationResult(True),
        VerificationResult(True),
    ])

    result = CodingHarness(FakeModel(subtasks), tools, verifier).run(Task("feature"))

    assert result.status is RunStatus.VERIFIED
    assert tools.patches == ["patch ST-001", "patch ST-002"]
    assert [item.subtask_id for item in result.subtasks] == ["ST-001", "ST-002"]


def test_escalates_on_unmet_dependency():
    subtasks = (SubTask("ST-002", "integrate", depends_on=("ST-001",)),)
    result = CodingHarness(
        FakeModel(subtasks),
        FakeTools(),
        SequenceVerifier([]),
    ).run(Task("feature"))

    assert result.status is RunStatus.ESCALATED
    assert "unmet dependencies" in result.diagnostics[0]
    assert result.events[-1].name == "run_escalated"


def test_records_decomposition_errors_as_failed_runs():
    class FailingModel(FakeModel):
        def decompose(self, task, tools):
            raise RuntimeError("model unavailable")

    result = CodingHarness(
        FailingModel(),
        FakeTools(),
        SequenceVerifier([]),
    ).run(Task("feature"))

    assert result.status is RunStatus.FAILED
    assert result.diagnostics == ("RuntimeError: model unavailable",)
    assert result.events[-1].name == "run_failed"


def test_records_patch_errors_on_the_subtask_result():
    class FailingTools(FakeTools):
        def apply_patch(self, patch):
            raise OSError("patch rejected")

    result = CodingHarness(
        FakeModel(),
        FailingTools(),
        SequenceVerifier([]),
    ).run(Task("feature"))

    assert result.status is RunStatus.FAILED
    assert result.subtasks[0].attempts == 1
    assert result.subtasks[0].diagnostics == ("OSError: patch rejected",)
    assert result.subtasks[0].events[-1].name == "subtask_failed"


def test_records_final_verification_errors_as_failed_runs():
    class FailingVerifier:
        def __init__(self):
            self.calls = 0

        def verify(self):
            self.calls += 1
            if self.calls == 1:
                return VerificationResult(True)
            raise RuntimeError("test runner unavailable")

    result = CodingHarness(FakeModel(), FakeTools(), FailingVerifier()).run(Task("feature"))

    assert result.status is RunStatus.FAILED
    assert result.diagnostics == ("RuntimeError: test runner unavailable",)
    assert result.events[-1].name == "run_failed"


def test_stops_when_subtask_repair_budget_is_exhausted():
    tools = FakeTools()
    verifier = SequenceVerifier([
        VerificationResult(False, ("failure 1",)),
        VerificationResult(False, ("failure 2",)),
    ])

    result = CodingHarness(
        FakeModel(), tools, verifier, max_repairs=1
    ).run(Task("fix bug"))

    assert result.status is RunStatus.FAILED
    assert result.attempts == 2
    assert len(result.subtasks) == 1
    assert result.subtasks[0].events[-1].name == "subtask_failed"
