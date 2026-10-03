from dataclasses import dataclass

from .models import RunResult, RunStatus, SubTask, SubTaskResult, Task
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
        events = ["decompose"]
        subtasks = self.model.decompose(task, self.tools)
        completed: set[str] = set()
        results: list[SubTaskResult] = []
        attempts = 0

        for subtask in subtasks:
            missing = set(subtask.depends_on) - completed
            if missing:
                diagnostics = (
                    f"{subtask.id} has unmet dependencies: {', '.join(sorted(missing))}",
                )
                events.append("escalated")
                return RunResult(
                    RunStatus.ESCALATED,
                    attempts,
                    diagnostics,
                    tuple(events),
                    tuple(results),
                )

            result = self._run_subtask(subtask)
            results.append(result)
            attempts += result.attempts
            events.extend(f"{subtask.id}:{event}" for event in result.events)

            if result.status is not RunStatus.VERIFIED:
                return RunResult(
                    result.status,
                    attempts,
                    result.diagnostics,
                    tuple(events),
                    tuple(results),
                )

            completed.add(subtask.id)

        events.append("final_verify")
        final = self.verifier.verify()
        if not final.ok:
            events.append("exhausted")
            return RunResult(
                RunStatus.EXHAUSTED,
                attempts,
                final.diagnostics,
                tuple(events),
                tuple(results),
            )

        events.append("verified")
        return RunResult(
            RunStatus.VERIFIED,
            attempts,
            final.diagnostics,
            tuple(events),
            tuple(results),
        )

    def _run_subtask(self, task: SubTask) -> SubTaskResult:
        events = ["locate", "plan"]
        plan = self.model.locate_and_plan(task, self.tools)

        events.append("patch")
        self.tools.apply_patch(self.model.create_patch(task, plan, self.tools))
        attempts = 1

        while True:
            events.append("verify")
            result = self.verifier.verify()
            if result.ok:
                events.extend(("review", "verified"))
                return SubTaskResult(
                    task.id, RunStatus.VERIFIED, attempts, result.diagnostics, tuple(events)
                )

            if attempts - 1 >= self.max_repairs:
                events.append("exhausted")
                return SubTaskResult(
                    task.id, RunStatus.EXHAUSTED, attempts, result.diagnostics, tuple(events)
                )

            events.append("repair")
            self.tools.apply_patch(
                self.model.repair_patch(task, result.diagnostics, self.tools)
            )
            attempts += 1
