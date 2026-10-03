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
                events.append(
                    self._event(
                        run_id,
                        "run_failed",
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
            final = self.verifier.verify()
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

            events.append(self._event(run_id, "implementation_started", task.id))
            patch = self.model.create_patch(task, plan, self.tools)
            attempts += 1
            self.tools.apply_patch(patch)
            events.append(self._event(run_id, "patch_applied", task.id))

            while True:
                events.append(self._event(run_id, "verify_started", task.id))
                result = self.verifier.verify()
                if result.ok:
                    events.append(
                        self._event(
                            run_id,
                            "verify_passed",
                            task.id,
                            result.diagnostics,
                        )
                    )
                    events.append(self._event(run_id, "subtask_verified", task.id))
                    return SubTaskResult(
                        task.id,
                        RunStatus.VERIFIED,
                        attempts,
                        result.diagnostics,
                        tuple(events),
                    )

                events.append(
                    self._event(
                        run_id,
                        "verify_failed",
                        task.id,
                        result.diagnostics,
                    )
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
                self.tools.apply_patch(patch)
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
