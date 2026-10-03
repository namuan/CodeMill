from dataclasses import dataclass

from .models import RunResult, RunStatus, Task
from .tools import CodingTools, ModelDriver
from .verifier import Verifier


@dataclass
class CodingHarness:
    """Minimal LOCATE -> PATCH -> VERIFY -> REPAIR state machine."""

    model: ModelDriver
    tools: CodingTools
    verifier: Verifier
    max_repairs: int = 3

    def run(self, task: Task) -> RunResult:
        events = ["locate"]
        plan = self.model.locate_and_plan(task, self.tools)

        events.append("patch")
        self.tools.apply_patch(self.model.create_patch(task, plan, self.tools))
        attempts = 1

        while True:
            events.append("verify")
            result = self.verifier.verify()
            if result.ok:
                events.append("verified")
                return RunResult(RunStatus.VERIFIED, attempts, result.diagnostics, tuple(events))

            if attempts - 1 >= self.max_repairs:
                events.append("exhausted")
                return RunResult(RunStatus.EXHAUSTED, attempts, result.diagnostics, tuple(events))

            events.append("repair")
            self.tools.apply_patch(self.model.repair_patch(task, result.diagnostics, self.tools))
            attempts += 1
