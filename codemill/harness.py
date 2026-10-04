from dataclasses import dataclass
from uuid import uuid4

from .decomposition import parse_decomposition, parse_decomposition_review
from .models import (
    ExpectedScope,
    ProtectedTestMutationError,
    RunEvent,
    RunResult,
    RunStatus,
    ScopeViolationError,
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
from .subtask_graph import order_subtasks
from .tools import CodingTools, ModelDriver
from .verifier import Verifier


@dataclass
class CodingHarness:
    """DECOMPOSE, then run the coding cycle for each minimal subtask."""

    model: ModelDriver
    tools: CodingTools
    verifier: Verifier
    max_repairs: int = 3
    max_test_patch_retries: int = 1

    def run(self, task: Task) -> RunResult:
        run_id = uuid4().hex
        run_checkpoint = self.tools.patch_checkpoint()
        events = [self._event(run_id, "run_started")]
        events.append(self._event(run_id, "decompose_started"))
        try:
            response = self.model.decompose(task, self.tools)
        except Exception as error:
            diagnostics = self._exception_diagnostic(error)
            events.append(self._event(run_id, "run_failed", diagnostics=diagnostics))
            return RunResult(RunStatus.FAILED, 0, run_id, diagnostics, tuple(events))

        try:
            proposed_subtasks = parse_decomposition(response)
            subtasks = order_subtasks(proposed_subtasks)
        except ValueError as error:
            diagnostics = (str(error),)
            events.append(self._event(run_id, "plan_rejected", diagnostics=diagnostics))
            events.append(self._event(run_id, "run_escalated", diagnostics=diagnostics))
            return RunResult(RunStatus.ESCALATED, 0, run_id, diagnostics, tuple(events))

        events.append(self._event(run_id, "decompose_completed"))
        events.append(self._event(run_id, "decomposition_review_started"))
        try:
            review_response = self.model.review_decomposition(task, subtasks, self.tools)
        except Exception as error:
            diagnostics = self._exception_diagnostic(error)
            events.append(self._event(run_id, "run_failed", diagnostics=diagnostics))
            return RunResult(
                RunStatus.FAILED,
                0,
                run_id,
                diagnostics,
                tuple(events),
                planned_subtasks=tuple(subtasks),
            )

        try:
            review = parse_decomposition_review(review_response)
        except ValueError as error:
            diagnostics = (str(error),)
            events.append(
                self._event(run_id, "decomposition_review_rejected", diagnostics=diagnostics)
            )
            events.append(self._event(run_id, "run_escalated", diagnostics=diagnostics))
            return RunResult(
                RunStatus.ESCALATED,
                0,
                run_id,
                diagnostics,
                tuple(events),
                planned_subtasks=tuple(subtasks),
            )

        if not review.accepted:
            diagnostics = review.findings or ("decomposition quality review rejected the plan",)
            events.append(
                self._event(run_id, "decomposition_review_rejected", diagnostics=diagnostics)
            )
            events.append(self._event(run_id, "run_escalated", diagnostics=diagnostics))
            return RunResult(
                RunStatus.ESCALATED,
                0,
                run_id,
                diagnostics,
                tuple(events),
                planned_subtasks=tuple(subtasks),
            )

        if review.already_satisfied and subtasks:
            diagnostics = ("already-satisfied review cannot include implementation subtasks",)
            events.append(
                self._event(run_id, "decomposition_review_rejected", diagnostics=diagnostics)
            )
            events.append(self._event(run_id, "run_escalated", diagnostics=diagnostics))
            return RunResult(
                RunStatus.ESCALATED,
                0,
                run_id,
                diagnostics,
                tuple(events),
                planned_subtasks=tuple(subtasks),
            )
        if not subtasks and not review.already_satisfied:
            diagnostics = ("empty plan requires an already-satisfied review with test evidence",)
            events.append(
                self._event(run_id, "decomposition_review_rejected", diagnostics=diagnostics)
            )
            events.append(self._event(run_id, "run_escalated", diagnostics=diagnostics))
            return RunResult(RunStatus.ESCALATED, 0, run_id, diagnostics, tuple(events))

        events.append(self._event(run_id, "decomposition_review_accepted"))
        events.append(self._event(run_id, "plan_validated"))
        results: list[SubTaskResult] = []
        pre_final_verifications: list[VerificationRecord] = []
        attempts = 0

        if review.already_satisfied:
            events.append(
                self._event(run_id, "no_change_review_accepted", diagnostics=review.evidence)
            )
            events.append(self._event(run_id, "no_change_verify_started"))
            try:
                no_change = self.verifier.verify(
                    VerificationPurpose.NO_CHANGE,
                    review.test_target,
                )
            except Exception as error:
                diagnostics = self._exception_diagnostic(error)
                events.append(self._event(run_id, "no_change_verify_failed", diagnostics=diagnostics))
                events.append(self._event(run_id, "run_failed", diagnostics=diagnostics))
                return RunResult(
                    RunStatus.FAILED,
                    0,
                    run_id,
                    diagnostics,
                    tuple(events),
                    planned_subtasks=tuple(subtasks),
                )
            no_change_record = VerificationRecord(
                VerificationPurpose.NO_CHANGE,
                review.test_target,
                no_change,
            )
            pre_final_verifications.append(no_change_record)
            if not no_change.ok:
                diagnostics = no_change.diagnostics or (
                    "existing tests did not verify the already-satisfied task",
                )
                events.append(
                    self._event(run_id, "no_change_verify_failed", diagnostics=diagnostics)
                )
                events.append(self._event(run_id, "run_escalated", diagnostics=diagnostics))
                return RunResult(
                    RunStatus.ESCALATED,
                    0,
                    run_id,
                    diagnostics,
                    tuple(events),
                    planned_subtasks=tuple(subtasks),
                    pre_final_verifications=tuple(pre_final_verifications),
                )
            events.append(self._event(run_id, "no_change_verified", diagnostics=review.evidence))

        for subtask in subtasks:
            result = self._run_subtask(
                run_id,
                subtask,
                run_checkpoint,
                task.expected_scope,
            )
            results.append(result)
            attempts += result.attempts
            events.extend(result.events)

            if result.status is not RunStatus.VERIFIED:
                terminal_event = (
                    "run_escalated"
                    if result.status is RunStatus.ESCALATED
                    else "run_failed"
                )
                events.append(
                    self._event(
                        run_id,
                        terminal_event,
                        subtask_id=subtask.id,
                        diagnostics=result.diagnostics,
                    )
                )
                return RunResult(
                    result.status,
                    attempts,
                    run_id,
                    result.diagnostics,
                    tuple(events),
                    tuple(results),
                    tuple(subtasks),
                )

        events.append(self._event(run_id, "final_verify_started"))
        try:
            final = self.verifier.verify(VerificationPurpose.FINAL)
        except Exception as error:
            diagnostics = self._exception_diagnostic(error)
            events.append(self._event(run_id, "run_failed", diagnostics=diagnostics))
            return RunResult(
                RunStatus.FAILED,
                attempts,
                run_id,
                diagnostics,
                tuple(events),
                tuple(results),
                tuple(subtasks),
                pre_final_verifications=tuple(pre_final_verifications),
            )

        final_record = VerificationRecord(VerificationPurpose.FINAL, None, final)
        if not final.ok:
            events.append(
                self._event(run_id, "final_verify_failed", diagnostics=final.diagnostics)
            )
            events.append(self._event(run_id, "run_failed", diagnostics=final.diagnostics))
            return RunResult(
                RunStatus.FAILED,
                attempts,
                run_id,
                final.diagnostics,
                tuple(events),
                tuple(results),
                tuple(subtasks),
                final_record,
                tuple(pre_final_verifications),
            )

        events.append(self._event(run_id, "final_verify_passed"))
        events.append(self._event(run_id, "run_verified"))
        return RunResult(
            RunStatus.VERIFIED,
            attempts,
            run_id,
            final.diagnostics,
            tuple(events),
            tuple(results),
            tuple(subtasks),
            final_record,
            tuple(pre_final_verifications),
        )

    def _run_subtask(
        self,
        run_id: str,
        task: SubTask,
        task_checkpoint: int,
        task_scope: ExpectedScope,
    ) -> SubTaskResult:
        events: list[RunEvent] = [self._event(run_id, "subtask_started", task.id)]
        checkpoint = self.tools.patch_checkpoint()
        attempts = 0
        verification_records: list[VerificationRecord] = []

        try:
            events.append(self._event(run_id, "locate_started", task.id))
            plan = self.model.locate_and_plan(task, self.tools)
            events.append(self._event(run_id, "plan_created", task.id))

            events.append(self._event(run_id, "test_write_started", task.id))
            test_patch = self.model.create_test_patch(task, plan, self.tools)
            for revision_attempt in range(self.max_test_patch_retries + 1):
                try:
                    test_target = self.tools.apply_test_patch(
                        test_patch,
                        task.expected_scope,
                        checkpoint,
                        task_scope,
                        task_checkpoint,
                    )
                    break
                except ProtectedTestMutationError as error:
                    revise_test_patch = getattr(self.model, "revise_test_patch", None)
                    if revision_attempt >= self.max_test_patch_retries or not callable(
                        revise_test_patch
                    ):
                        raise
                    diagnostics = (str(error),)
                    events.append(
                        self._event(
                            run_id,
                            "protected_test_mutation_attempt",
                            task.id,
                            diagnostics,
                        )
                    )
                    events.append(
                        self._event(run_id, "test_patch_rejected", task.id, diagnostics)
                    )
                    events.append(
                        self._event(run_id, "test_patch_revision_started", task.id, diagnostics)
                    )
                    test_patch = revise_test_patch(
                        task,
                        plan,
                        self.tools,
                        test_patch,
                        diagnostics,
                    )
                    events.append(self._event(run_id, "test_patch_revised", task.id))
            if not isinstance(test_target, VerificationTarget):
                raise TypeError("test patch application must return a VerificationTarget")
            events.append(self._event(run_id, "test_patch_applied", task.id))

            events.append(self._event(run_id, "red_verify_started", task.id))
            try:
                red = self.verifier.verify(VerificationPurpose.RED, test_target)
                verification_records.append(
                    VerificationRecord(VerificationPurpose.RED, test_target, red)
                )
            except Exception:
                self.tools.discard_test_patch()
                raise
            if red.ok or red.failure_kind is not VerificationFailureKind.EXPECTED_BEHAVIOR:
                self.tools.discard_test_patch()
                events.append(self._event(run_id, "test_patch_discarded", task.id))
                diagnostics = red.diagnostics or (
                    "focused test did not fail for the expected missing behavior",
                )
                events.append(
                    self._event(run_id, "red_rejected", task.id, diagnostics)
                )
                events.append(
                    self._event(run_id, "subtask_escalated", task.id, diagnostics)
                )
                return SubTaskResult(
                    task.id,
                    RunStatus.ESCALATED,
                    attempts,
                    diagnostics,
                    tuple(events),
                    verifications=tuple(verification_records),
                )

            events.append(self._event(run_id, "red_confirmed", task.id, red.diagnostics))
            try:
                protected_tests = self.tools.freeze_tests()
            except Exception:
                self.tools.discard_test_patch()
                raise
            events.append(self._event(run_id, "tests_frozen", task.id))
            events.append(self._event(run_id, "implementation_started", task.id))
            patch = self.model.create_patch(
                task,
                plan,
                self.tools,
                test_target,
                red.diagnostics,
            )
            attempts += 1
            self.tools.apply_production_patch(
                patch,
                protected_tests,
                task.expected_scope,
                checkpoint,
                task_scope,
                task_checkpoint,
            )
            events.append(self._event(run_id, "patch_applied", task.id))

            while True:
                events.append(self._event(run_id, "green_verify_started", task.id))
                result = self.verifier.verify(VerificationPurpose.GREEN, test_target)
                verification_records.append(
                    VerificationRecord(VerificationPurpose.GREEN, test_target, result)
                )
                if result.ok:
                    events.append(
                        self._event(run_id, "green_verify_passed", task.id, result.diagnostics)
                    )
                    events.append(self._event(run_id, "regression_verify_started", task.id))
                    result = self.verifier.verify(VerificationPurpose.REGRESSION)
                    verification_records.append(
                        VerificationRecord(VerificationPurpose.REGRESSION, None, result)
                    )
                    if result.ok:
                        events.append(
                            self._event(
                                run_id,
                                "regression_verify_passed",
                                task.id,
                                result.diagnostics,
                            )
                        )
                        events.append(self._event(run_id, "minimality_review_started", task.id))
                        diff = self.tools.git_diff()
                        review_response = self.model.review_implementation(
                            task,
                            diff,
                            self.tools,
                            test_target,
                        )
                        review = parse_decomposition_review(review_response)
                        if review.accepted:
                            events.append(
                                self._event(run_id, "minimality_review_accepted", task.id)
                            )
                            verified_slice = VerifiedSliceRecord(
                                task.id,
                                task.objective,
                                task.acceptance_criteria,
                                test_target.paths,
                                self.tools.changed_files_since(checkpoint),
                                (
                                    VerificationPurpose.RED,
                                    VerificationPurpose.GREEN,
                                    VerificationPurpose.REGRESSION,
                                ),
                            )
                            events.append(self._event(run_id, "subtask_verified", task.id))
                            events.append(self._event(run_id, "slice_compacted", task.id))
                            return SubTaskResult(
                                task.id,
                                RunStatus.VERIFIED,
                                attempts,
                                result.diagnostics,
                                tuple(events),
                                verified_slice,
                                tuple(verification_records),
                            )
                        result = VerificationResult(False, review.findings)
                        events.append(
                            self._event(
                                run_id,
                                "minimality_review_rejected",
                                task.id,
                                review.findings,
                            )
                        )
                    else:
                        events.append(
                            self._event(
                                run_id,
                                "regression_verify_failed",
                                task.id,
                                result.diagnostics,
                            )
                        )
                else:
                    events.append(
                        self._event(run_id, "green_verify_failed", task.id, result.diagnostics)
                    )

                if attempts - 1 >= self.max_repairs:
                    events.append(
                        self._event(
                            run_id,
                            "repair_budget_exhausted",
                            task.id,
                            result.diagnostics,
                        )
                    )
                    events.append(
                        self._event(
                            run_id,
                            "subtask_failed",
                            task.id,
                            result.diagnostics,
                        )
                    )
                    return SubTaskResult(
                        task.id,
                        RunStatus.FAILED,
                        attempts,
                        result.diagnostics,
                        tuple(events),
                        verifications=tuple(verification_records),
                    )

                events.append(self._event(run_id, "repair_started", task.id, result.diagnostics))
                patch = self.model.repair_patch(
                    task,
                    result.diagnostics,
                    self.tools,
                    test_target,
                )
                attempts += 1
                self.tools.apply_production_patch(
                    patch,
                    protected_tests,
                    task.expected_scope,
                    checkpoint,
                    task_scope,
                    task_checkpoint,
                )
                events.append(self._event(run_id, "repair_patch_applied", task.id))
        except ProtectedTestMutationError as error:
            diagnostics = (str(error),)
            events.append(
                self._event(run_id, "protected_test_mutation_attempt", task.id, diagnostics)
            )
            events.append(self._event(run_id, "subtask_failed", task.id, diagnostics))
            return SubTaskResult(
                task.id,
                RunStatus.FAILED,
                attempts,
                diagnostics,
                tuple(events),
                verifications=tuple(verification_records),
            )
        except ScopeViolationError as error:
            diagnostics = (str(error),)
            events.append(self._event(run_id, "scope_violation", task.id, diagnostics))
            return SubTaskResult(
                task.id,
                RunStatus.ESCALATED,
                attempts,
                diagnostics,
                tuple(events),
                verifications=tuple(verification_records),
            )
        except Exception as error:
            diagnostics = self._exception_diagnostic(error)
            events.append(
                self._event(run_id, "subtask_failed", task.id, diagnostics)
            )
            return SubTaskResult(
                task.id,
                RunStatus.FAILED,
                attempts,
                diagnostics,
                tuple(events),
                verifications=tuple(verification_records),
            )

    @staticmethod
    def _event(
        run_id: str,
        name: str,
        subtask_id: str | None = None,
        diagnostics: tuple[str, ...] = (),
    ) -> RunEvent:
        return RunEvent(run_id, name, subtask_id, diagnostics)

    @staticmethod
    def _exception_diagnostic(error: Exception) -> tuple[str, ...]:
        return (f"{type(error).__name__}: {error}",)
