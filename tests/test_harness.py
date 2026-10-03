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
    assert "final_verify" in result.events


def test_executes_dependency_ordered_subtasks():
    subtasks = (
        SubTask("ST-001", "add primitive"),
        SubTask("ST-002", "integrate primitive", depends_on=("ST-001",)),
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


def test_stops_when_subtask_repair_budget_is_exhausted():
    tools = FakeTools()
    verifier = SequenceVerifier([
        VerificationResult(False, ("failure 1",)),
        VerificationResult(False, ("failure 2",)),
    ])

    result = CodingHarness(
        FakeModel(), tools, verifier, max_repairs=1
    ).run(Task("fix bug"))

    assert result.status is RunStatus.EXHAUSTED
    assert result.attempts == 2
    assert len(result.subtasks) == 1
