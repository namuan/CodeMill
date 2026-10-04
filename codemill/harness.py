from dataclasses import dataclass
from uuid import uuid4

from .decomposition import parse_decomposition, parse_decomposition_review
from .models import (
    RunEvent,
    RunResult,
    RunStatus,
    SubTask,
    SubTaskResult,
    Task,
    VerificationFailureKind,
    VerificationPurpose,
    VerificationResult,
    VerificationTarget,
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

    def run(self, task: Task) -> RunResult:
        run_id = uuid4().hex
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
            return RunResult(RunStatus.FAILED, 0, run_id, diagnostics, tuple(events))

        try:
            review = parse_decomposition_review(review_response)
        except ValueError as error:
            diagnostics = (str(error),)
            events.append(
                self._event(run_id, "decomposition_review_rejected", diagnostics=diagnostics)
            )
            events.append(self._event(run_id, "run_escalated", diagnostics=diagnostics))
            return RunResult(RunStatus.ESCALATED, 0, run_id, diagnostics, tuple(events))

        if not review.accepted:
            diagnostics = review.findings or ("decomposition quality review rejected the plan",)
            events.append(
                self._event(run_id, "decomposition_review_rejected", diagnostics=diagnostics)
            )
            events.append(self._event(run_id, "run_escalated", diagnostics=diagnostics))
            return RunResult(RunStatus.ESCALATED, 0, run_id, diagnostics, tuple(events))

        events.append(self._event(run_id, "decomposition_review_accepted"))
        events.append(self._event(run_id, "plan_validated"))
        results: list[SubTaskResult] = []
        attempts = 0

        for subtask in subtasks:
            result = self._run_subtask(run_id, subtask)
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
            )

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
        )

    def _run_subtask(self, run_id: str, task: SubTask) -> SubTaskResult:
        events: list[RunEvent] = [self._event(run_id, "subtask_started", task.id)]
        attempts = 0

        try:
            events.append(self._event(run_id, "locate_started", task.id))
            plan = self.model.locate_and_plan(task, self.tools)
            events.append(self._event(run_id, "plan_created", task.id))

            events.append(self._event(run_id, "test_write_started", task.id))
            test_patch = self.model.create_test_patch(task, plan, self.tools)
            test_target = self.tools.apply_test_patch(test_patch)
            if not isinstance(test_target, VerificationTarget):
                raise TypeError("test patch application must return a VerificationTarget")
            events.append(self._event(run_id, "test_patch_applied", task.id))

            events.append(self._event(run_id, "red_verify_started", task.id))
            try:
                red = self.verifier.verify(VerificationPurpose.RED, test_target)
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
                )

            events.append(self._event(run_id, "red_confirmed", task.id, red.diagnostics))
            try:
                protected_tests = self.tools.freeze_tests()
            except Exception:
                self.tools.discard_test_patch()
                raise
            events.append(self._event(run_id, "tests_frozen", task.id))
            events.append(self._event(run_id, "implementation_started", task.id))
            patch = self.model.create_patch(task, plan, self.tools)
            attempts += 1
            self.tools.apply_production_patch(patch, protected_tests)
            events.append(self._event(run_id, "patch_applied", task.id))

            while True:
                events.append(self._event(run_id, "green_verify_started", task.id))
                result = self.verifier.verify(VerificationPurpose.GREEN, test_target)
                if result.ok:
                    events.append(
                        self._event(run_id, "green_verify_passed", task.id, result.diagnostics)
                    )
                    events.append(self._event(run_id, "regression_verify_started", task.id))
                    result = self.verifier.verify(VerificationPurpose.REGRESSION)
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
                        )
                        review = parse_decomposition_review(review_response)
                        if review.accepted:
                            events.append(
                                self._event(run_id, "minimality_review_accepted", task.id)
                            )
                            events.append(self._event(run_id, "subtask_verified", task.id))
                            return SubTaskResult(
                                task.id,
                                RunStatus.VERIFIED,
                                attempts,
                                result.diagnostics,
                                tuple(events),
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
                    )

                events.append(self._event(run_id, "repair_started", task.id, result.diagnostics))
                patch = self.model.repair_patch(task, result.diagnostics, self.tools)
                attempts += 1
                self.tools.apply_production_patch(patch, protected_tests)
                events.append(self._event(run_id, "repair_patch_applied", task.id))
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
