from codemill.harness import CodingHarness
from codemill.models import RunStatus, Task, VerificationResult


class FakeTools:
    def __init__(self):
        self.patches = []

    def search_text(self, query): return ""
    def read_file(self, path, start=None, end=None): return ""
    def apply_patch(self, patch): self.patches.append(patch)


class FakeModel:
    def locate_and_plan(self, task, tools): return "change target"
    def create_patch(self, task, plan, tools): return "initial"
    def repair_patch(self, task, diagnostics, tools): return "repair"


class SequenceVerifier:
    def __init__(self, results): self.results = iter(results)
    def verify(self): return next(self.results)


def test_repairs_then_verifies():
    tools = FakeTools()
    verifier = SequenceVerifier([
        VerificationResult(False, ("type error",)),
        VerificationResult(True),
    ])
    result = CodingHarness(FakeModel(), tools, verifier).run(Task("fix bug"))
    assert result.status is RunStatus.VERIFIED
    assert result.attempts == 2
    assert tools.patches == ["initial", "repair"]


def test_stops_at_repair_budget():
    tools = FakeTools()
    verifier = SequenceVerifier([
        VerificationResult(False, ("failure 1",)),
        VerificationResult(False, ("failure 2",)),
    ])
    result = CodingHarness(FakeModel(), tools, verifier, max_repairs=1).run(Task("fix bug"))
    assert result.status is RunStatus.EXHAUSTED
    assert result.attempts == 2
