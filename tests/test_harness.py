import json
from dataclasses import asdict

from codemill.harness import CodingHarness
from codemill.models import (
    ProtectedTestMutationError,
    ProtectedTests,
    RunStatus,
    ScopeViolationError,
    SubTask,
    Task,
    VerificationFailureKind,
    VerificationPurpose,
    VerificationResult,
    VerificationTarget,
)


class FakeTools:
    def __init__(self):
        self.patches = []
        self.freeze_calls = 0
        self.test_protection = None
        self.production_protections = []
        self.current_test_target = None
        self.active_test_patch = None
        self.discard_calls = 0
        self.patch_paths = []

    def search_text(self, query): return ""
    def read_file(self, path, start=None, end=None): return ""
    def git_diff(self): return "diff"
    def apply_test_patch(self, patch, *scope_args):
        self.patches.append(f"test:{patch}")
        self.active_test_patch = patch
        subtask_id = patch.rsplit(" ", 1)[-1]
        self.current_test_target = VerificationTarget((f"tests/test_{subtask_id}.py",))
        self.patch_paths.append(self.current_test_target.paths[0])
        return self.current_test_target

    def discard_test_patch(self):
        self.discard_calls += 1
        self.active_test_patch = None
        self.patch_paths.pop()

    def freeze_tests(self):
        self.freeze_calls += 1
        self.test_protection = ProtectedTests(self.current_test_target.paths, "test-fingerprint")
        return self.test_protection

    def patch_checkpoint(self):
        return len(self.patch_paths)

    def changed_files_since(self, checkpoint):
        return tuple(sorted(set(self.patch_paths[checkpoint:])))

    def apply_production_patch(self, patch, protected_tests, *scope_args):
        if protected_tests != self.test_protection:
            raise PermissionError("protected test set mismatch")
        if patch == "modify-protected-test":
            raise PermissionError("implementation attempted to modify a protected test")
        self.production_protections.append(protected_tests)
        self.patches.append(f"implementation:{patch}")
        subtask_id = patch.rsplit(" ", 1)[-1]
        self.patch_paths.append(f"src/{subtask_id}.py")


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
    def create_patch(self, task, plan, tools, test_target, red_diagnostics): return f"patch {task.id}"
    def review_implementation(self, task, diff, tools, test_target):
        return json.dumps({"accepted": True, "findings": []})
    def repair_patch(self, task, diagnostics, tools, test_target): return f"repair {task.id}"


class SequenceVerifier:
    def __init__(self, results):
        self.results = iter(results)
        self.purposes = []
        self.targets = []

    def verify(self, purpose, target=None):
        self.purposes.append(purpose)
        self.targets.append((purpose, target))
        return next(self.results)


def test_red_and_green_verify_the_same_focused_test_target():
    tools = FakeTools()
    verifier = SequenceVerifier([
        VerificationResult(False, ("behavior absent",), VerificationFailureKind.EXPECTED_BEHAVIOR),
        VerificationResult(True),
        VerificationResult(True),
        VerificationResult(True),
    ])

    CodingHarness(FakeModel(), tools, verifier).run(Task("feature"))

    target = VerificationTarget(("tests/test_ST-001.py",))
    assert verifier.targets == [
        (VerificationPurpose.RED, target),
        (VerificationPurpose.GREEN, target),
        (VerificationPurpose.REGRESSION, None),
        (VerificationPurpose.FINAL, None),
    ]


def test_repairs_subtask_then_runs_final_verification():
    tools = FakeTools()
    verifier = SequenceVerifier([
        VerificationResult(False, ("missing greeting behavior",), VerificationFailureKind.EXPECTED_BEHAVIOR),
        VerificationResult(False, ("type error",)),
        VerificationResult(True),
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
        VerificationPurpose.REGRESSION,
        VerificationPurpose.FINAL,
    ]
    assert result.subtasks[0].status is RunStatus.VERIFIED
    assert "final_verify_started" in [event.name for event in result.events]
    assert all(event.run_id == result.run_id for event in result.events)
    assert all(event.subtask_id == "ST-001" for event in result.subtasks[0].events)
    record = result.subtasks[0].verified_slice
    assert record.subtask_id == "ST-001"
    assert record.behavior == "fix bug"
    assert record.accepted_test_paths == ("tests/test_ST-001.py",)
    assert record.changed_files == ("src/ST-001.py", "tests/test_ST-001.py")
    assert record.verification_purposes == (
        VerificationPurpose.RED,
        VerificationPurpose.GREEN,
        VerificationPurpose.REGRESSION,
    )
    assert result.subtasks[0].events[-1].name == "slice_compacted"
    assert tuple(record.purpose for record in result.verifications) == (
        VerificationPurpose.RED,
        VerificationPurpose.GREEN,
        VerificationPurpose.GREEN,
        VerificationPurpose.REGRESSION,
        VerificationPurpose.FINAL,
    )


def test_verifies_already_satisfied_task_without_mutation():
    class SatisfiedModel(FakeModel):
        def decompose(self, task, tools):
            return '{"subtasks": []}'

        def review_decomposition(self, task, subtasks, tools):
            return json.dumps(
                {
                    "accepted": True,
                    "findings": [],
                    "already_satisfied": True,
                    "evidence": ["tests/test_feature.py::test_feature covers the criterion"],
                    "test_target": {
                        "paths": ["tests/test_feature.py"],
                        "selectors": ["test_feature"],
                    },
                }
            )

    tools = FakeTools()
    verifier = SequenceVerifier([VerificationResult(True), VerificationResult(True)])

    result = CodingHarness(SatisfiedModel(), tools, verifier).run(
        Task("feature is already implemented", ("feature behavior works",))
    )

    assert result.status is RunStatus.VERIFIED
    assert result.subtasks == ()
    assert tools.patches == []
    assert verifier.purposes == [VerificationPurpose.NO_CHANGE, VerificationPurpose.FINAL]
    assert verifier.targets[0] == (
        VerificationPurpose.NO_CHANGE,
        VerificationTarget(("tests/test_feature.py",), ("test_feature",)),
    )
    assert tuple(record.purpose for record in result.verifications) == (
        VerificationPurpose.NO_CHANGE,
        VerificationPurpose.FINAL,
    )
    assert "no_change_verified" in [event.name for event in result.events]


def test_retries_focused_test_after_preexisting_test_is_protected():
    class RetryTools(FakeTools):
        def __init__(self):
            super().__init__()
            self.test_patch_calls = 0

        def apply_test_patch(self, patch, *scope_args):
            self.test_patch_calls += 1
            if self.test_patch_calls == 1:
                raise ProtectedTestMutationError("test patch may not modify a pre-existing file")
            return super().apply_test_patch(patch, *scope_args)

    class RetryModel(FakeModel):
        def __init__(self):
            super().__init__()
            self.revisions = []

        def revise_test_patch(self, task, plan, tools, rejected_patch, diagnostics):
            self.revisions.append((rejected_patch, diagnostics))
            return "replacement focused test patch ST-001"

    tools = RetryTools()
    model = RetryModel()
    verifier = SequenceVerifier(
        [
            VerificationResult(False, ("expected behavior missing",), VerificationFailureKind.EXPECTED_BEHAVIOR),
            VerificationResult(True),
            VerificationResult(True),
            VerificationResult(True),
        ]
    )

    result = CodingHarness(model, tools, verifier).run(Task("fix bug"))

    assert result.status is RunStatus.VERIFIED
    assert model.revisions == [
        ("test patch ST-001", ("test patch may not modify a pre-existing file",))
    ]
    assert tools.patches[0] == "test:replacement focused test patch ST-001"
    assert "protected_test_mutation_attempt" in [event.name for event in result.events]
    assert "test_patch_rejected" in [event.name for event in result.events]


def test_refuses_empty_plan_without_no_change_evidence():
    class EmptyPlanModel(FakeModel):
        def decompose(self, task, tools):
            return '{"subtasks": []}'

    verifier = SequenceVerifier([])

    result = CodingHarness(EmptyPlanModel(), FakeTools(), verifier).run(Task("feature"))

    assert result.status is RunStatus.ESCALATED
    assert result.diagnostics == (
        "empty plan requires an already-satisfied review with test evidence",
    )
    assert verifier.purposes == []


def test_freezes_red_test_before_production_patches():
    tools = FakeTools()
    verifier = SequenceVerifier([
        VerificationResult(False, ("behavior absent",), VerificationFailureKind.EXPECTED_BEHAVIOR),
        VerificationResult(True),
        VerificationResult(True),
        VerificationResult(True),
    ])

    result = CodingHarness(FakeModel(), tools, verifier).run(Task("feature"))

    names = [event.name for event in result.events]
    assert names.index("red_confirmed") < names.index("tests_frozen")
    assert names.index("tests_frozen") < names.index("implementation_started")
    assert tools.freeze_calls == 1
    assert tools.production_protections == [tools.test_protection]


def test_rejects_production_patch_that_modifies_a_protected_test():
    class TestEditingModel(FakeModel):
        def create_patch(self, task, plan, tools, test_target, red_diagnostics):
            return "modify-protected-test"

    tools = FakeTools()
    verifier = SequenceVerifier([
        VerificationResult(False, ("behavior absent",), VerificationFailureKind.EXPECTED_BEHAVIOR),
    ])

    result = CodingHarness(TestEditingModel(), tools, verifier).run(Task("feature"))

    assert result.status is RunStatus.FAILED
    assert result.diagnostics == (
        "PermissionError: implementation attempted to modify a protected test",
    )
    assert tools.patches == ["test:test patch ST-001"]
    assert verifier.purposes == [VerificationPurpose.RED]


def test_repairs_minimality_review_findings_before_verifying_slice():
    class ReviewModel(FakeModel):
        def __init__(self):
            super().__init__()
            self.review_calls = 0

        def review_implementation(self, task, diff, tools, test_target):
            self.review_calls += 1
            if self.review_calls == 1:
                return json.dumps(
                    {"accepted": False, "findings": ["unnecessary helper"]}
                )
            return json.dumps({"accepted": True, "findings": []})

    model = ReviewModel()
    tools = FakeTools()
    verifier = SequenceVerifier([
        VerificationResult(False, ("behavior absent",), VerificationFailureKind.EXPECTED_BEHAVIOR),
        VerificationResult(True),
        VerificationResult(True),
        VerificationResult(True),
        VerificationResult(True),
        VerificationResult(True),
    ])

    result = CodingHarness(model, tools, verifier).run(Task("feature"))

    assert result.status is RunStatus.VERIFIED
    assert model.review_calls == 2
    assert tools.patches[-1] == "implementation:repair ST-001"
    names = [event.name for event in result.events]
    assert "minimality_review_rejected" in names
    assert "minimality_review_accepted" in names
    assert "regression_verify_failed" not in names


def test_repairs_regression_failure_without_changing_protected_test():
    tools = FakeTools()
    verifier = SequenceVerifier([
        VerificationResult(False, ("behavior absent",), VerificationFailureKind.EXPECTED_BEHAVIOR),
        VerificationResult(True),
        VerificationResult(False, ("existing test failed",)),
        VerificationResult(True),
        VerificationResult(True),
        VerificationResult(True),
    ])

    result = CodingHarness(FakeModel(), tools, verifier).run(Task("feature"))

    assert result.status is RunStatus.VERIFIED
    assert tools.patches == [
        "test:test patch ST-001",
        "implementation:patch ST-001",
        "implementation:repair ST-001",
    ]
    assert tools.freeze_calls == 1
    assert tools.production_protections == [tools.test_protection, tools.test_protection]
    assert verifier.purposes == [
        VerificationPurpose.RED,
        VerificationPurpose.GREEN,
        VerificationPurpose.REGRESSION,
        VerificationPurpose.GREEN,
        VerificationPurpose.REGRESSION,
        VerificationPurpose.FINAL,
    ]


def test_executes_dependency_ordered_subtasks():
    subtasks = (
        SubTask("ST-002", "integrate primitive", depends_on=("ST-001",)),
        SubTask("ST-001", "add primitive"),
    )
    tools = FakeTools()
    verifier = SequenceVerifier([
        VerificationResult(False, ("behavior absent",), VerificationFailureKind.EXPECTED_BEHAVIOR),
        VerificationResult(True),
        VerificationResult(True),
        VerificationResult(False, ("behavior absent",), VerificationFailureKind.EXPECTED_BEHAVIOR),
        VerificationResult(True),
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
    assert tools.discard_calls == 1
    assert tools.active_test_patch is None
    assert "implementation_started" not in [event.name for event in result.events]
    assert result.events[-1].name == "run_escalated"


def test_discards_focused_test_when_red_verification_errors():
    class FailingRedVerifier:
        def verify(self, purpose, target=None):
            raise RuntimeError("test runner unavailable")

    tools = FakeTools()
    result = CodingHarness(FakeModel(), tools, FailingRedVerifier()).run(Task("feature"))

    assert result.status is RunStatus.FAILED
    assert tools.discard_calls == 1
    assert tools.active_test_patch is None
    assert result.subtasks[0].events[-1].name == "subtask_failed"


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


def test_escalates_scope_violations_before_mutating():
    class OverBudgetTools(FakeTools):
        def apply_test_patch(self, patch, *scope_args):
            raise ScopeViolationError("patch exceeds changed-line budget")

    tools = OverBudgetTools()
    verifier = SequenceVerifier([])

    result = CodingHarness(FakeModel(), tools, verifier).run(Task("feature"))

    assert result.status is RunStatus.ESCALATED
    assert result.diagnostics == ("patch exceeds changed-line budget",)
    assert verifier.purposes == []
    assert "scope_violation" in [event.name for event in result.events]


def test_records_patch_errors_on_the_subtask_result():
    class FailingTools(FakeTools):
        def apply_production_patch(self, patch, protected_tests, *scope_args):
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

        def verify(self, purpose, target=None):
            self.calls += 1
            if purpose is VerificationPurpose.RED:
                return VerificationResult(
                    False,
                    ("behavior absent",),
                    VerificationFailureKind.EXPECTED_BEHAVIOR,
                )
            if purpose in (VerificationPurpose.GREEN, VerificationPurpose.REGRESSION):
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
