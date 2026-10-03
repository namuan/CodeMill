import json
from dataclasses import asdict

from codemill.harness import CodingHarness
from codemill.models import (
    RunStatus,
    SubTask,
    Task,
    VerificationFailureKind,
    VerificationPurpose,
    VerificationResult,
)


class FakeTools:
    def __init__(self):
        self.patches = []

    def search_text(self, query): return ""
    def read_file(self, path, start=None, end=None): return ""
    def apply_test_patch(self, patch): self.patches.append(f"test:{patch}")
    def apply_patch(self, patch): self.patches.append(f"implementation:{patch}")


class FakeModel:
    def __init__(self, subtasks=None):
        self.subtasks = subtasks or (SubTask("ST-001", "fix bug"),)

    def decompose(self, task, tools):
        items = []
        for subtask in self.subtasks:
            item = asdict(subtask)
            item["acceptance_criteria"] = item["acceptance_criteria"] or [
                f"subtask completes: {subtask.objective}"
            ]
            items.append(item)
        return json.dumps({"subtasks": items})

    def review_decomposition(self, task, subtasks, tools):
        return json.dumps({"accepted": True, "findings": []})

    def locate_and_plan(self, task, tools): return f"plan {task.id}"
    def create_test_patch(self, task, plan, tools): return f"test patch {task.id}"
    def create_patch(self, task, plan, tools): return f"patch {task.id}"
    def repair_patch(self, task, diagnostics, tools): return f"repair {task.id}"


class SequenceVerifier:
    def __init__(self, results):
        self.results = iter(results)
        self.purposes = []

    def verify(self, purpose):
        self.purposes.append(purpose)
        return next(self.results)


def test_repairs_subtask_then_runs_final_verification():
    tools = FakeTools()
    verifier = SequenceVerifier([
        VerificationResult(False, ("missing greeting behavior",), VerificationFailureKind.EXPECTED_BEHAVIOR),
        VerificationResult(False, ("type error",)),
        VerificationResult(True),
        VerificationResult(True),
    ])

    result = CodingHarness(FakeModel(), tools, verifier).run(Task("fix bug"))

    assert result.status is RunStatus.VERIFIED
    assert result.attempts == 2
    assert tools.patches == [
        "test:test patch ST-001",
        "implementation:patch ST-001",
        "implementation:repair ST-001",
    ]
    assert verifier.purposes == [
        VerificationPurpose.RED,
        VerificationPurpose.GREEN,
        VerificationPurpose.GREEN,
        VerificationPurpose.FINAL,
    ]
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
        VerificationResult(False, ("behavior absent",), VerificationFailureKind.EXPECTED_BEHAVIOR),
        VerificationResult(True),
        VerificationResult(False, ("behavior absent",), VerificationFailureKind.EXPECTED_BEHAVIOR),
        VerificationResult(True),
        VerificationResult(True),
    ])

    result = CodingHarness(FakeModel(subtasks), tools, verifier).run(Task("feature"))

    assert result.status is RunStatus.VERIFIED
    assert tools.patches == [
        "test:test patch ST-001",
        "implementation:patch ST-001",
        "test:test patch ST-002",
        "implementation:patch ST-002",
    ]
    assert [item.subtask_id for item in result.subtasks] == ["ST-001", "ST-002"]


def test_escalates_if_focused_test_does_not_demonstrate_expected_red():
    tools = FakeTools()
    model = FakeModel()
    verifier = SequenceVerifier([VerificationResult(True)])

    result = CodingHarness(model, tools, verifier).run(Task("feature"))

    assert result.status is RunStatus.ESCALATED
    assert tools.patches == ["test:test patch ST-001"]
    assert "implementation_started" not in [event.name for event in result.events]
    assert result.events[-1].name == "run_escalated"


def test_escalates_if_focused_test_fails_for_an_unexpected_reason():
    tools = FakeTools()
    verifier = SequenceVerifier([VerificationResult(False, ("fixture error",))])

    result = CodingHarness(FakeModel(), tools, verifier).run(Task("feature"))

    assert result.status is RunStatus.ESCALATED
    assert tools.patches == ["test:test patch ST-001"]
    assert result.diagnostics == ("fixture error",)


def test_escalates_on_malformed_structured_decomposition_before_mutation():
    class MalformedModel(FakeModel):
        def decompose(self, task, tools):
            return '{"subtasks": [{"id": "ST-001"}]}'

    tools = FakeTools()
    result = CodingHarness(
        MalformedModel(),
        tools,
        SequenceVerifier([]),
    ).run(Task("feature"))

    assert result.status is RunStatus.ESCALATED
    assert result.diagnostics
    assert tools.patches == []
    assert result.events[-1].name == "run_escalated"


def test_escalates_on_malformed_decomposition_review_before_mutation():
    class MalformedReviewModel(FakeModel):
        def review_decomposition(self, task, subtasks, tools):
            return '{"accepted": "yes", "findings": []}'

    tools = FakeTools()
    result = CodingHarness(
        MalformedReviewModel(),
        tools,
        SequenceVerifier([]),
    ).run(Task("feature"))

    assert result.status is RunStatus.ESCALATED
    assert result.diagnostics
    assert tools.patches == []


def test_escalates_when_decomposition_quality_review_rejects_plan():
    class RejectingModel(FakeModel):
        def review_decomposition(self, task, subtasks, tools):
            return json.dumps(
                {
                    "accepted": False,
                    "findings": ["subtasks are split by technical layer"],
                }
            )

    tools = FakeTools()
    result = CodingHarness(
        RejectingModel(),
        tools,
        SequenceVerifier([]),
    ).run(Task("feature"))

    assert result.status is RunStatus.ESCALATED
    assert result.diagnostics == ("subtasks are split by technical layer",)
    assert tools.patches == []
    assert "decomposition_review_rejected" in [event.name for event in result.events]


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
        SequenceVerifier([
            VerificationResult(False, ("behavior absent",), VerificationFailureKind.EXPECTED_BEHAVIOR),
        ]),
    ).run(Task("feature"))

    assert result.status is RunStatus.FAILED
    assert result.subtasks[0].attempts == 1
    assert result.subtasks[0].diagnostics == ("OSError: patch rejected",)
    assert result.subtasks[0].events[-1].name == "subtask_failed"


def test_records_final_verification_errors_as_failed_runs():
    class FailingVerifier:
        def __init__(self):
            self.calls = 0

        def verify(self, purpose):
            self.calls += 1
            if purpose is VerificationPurpose.RED:
                return VerificationResult(
                    False,
                    ("behavior absent",),
                    VerificationFailureKind.EXPECTED_BEHAVIOR,
                )
            if purpose is VerificationPurpose.GREEN:
                return VerificationResult(True)
            raise RuntimeError("test runner unavailable")

    result = CodingHarness(FakeModel(), FakeTools(), FailingVerifier()).run(Task("feature"))

    assert result.status is RunStatus.FAILED
    assert result.diagnostics == ("RuntimeError: test runner unavailable",)
    assert result.events[-1].name == "run_failed"


def test_stops_when_subtask_repair_budget_is_exhausted():
    tools = FakeTools()
    verifier = SequenceVerifier([
        VerificationResult(False, ("behavior absent",), VerificationFailureKind.EXPECTED_BEHAVIOR),
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
