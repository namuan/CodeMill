# CodeMill

**A verification-first, test-driven coding harness for small language models.**

CodeMill explores how small coding models (initially around 9B parameters) can perform useful repository-level software engineering by decomposing a developer task into the **smallest independently verifiable vertical slices**, then executing each slice under a harness-enforced TDD cycle.

## Design principles

- **Decompose into vertical slices.** Each sub-task delivers one observable behavior through whatever layers are required to verify it.
- **Smallest independently verifiable unit.** Split further only when every resulting slice still has a meaningful observable verification condition.
- **Avoid horizontal decomposition.** Database, service, API, UI, or tests are not separate sub-tasks merely because they are separate technical layers.
- **Harness-enforced TDD.** CodeMill writes the minimal behavioral test first and proves it fails before implementation begins.
- **Tests are immutable during implementation.** The implementation model fixes production code; it does not weaken or rewrite the test to obtain GREEN.
- **Minimal implementation.** Add only the production behavior required to make the new test pass. No speculative abstractions, unrelated refactors, or extra behavior.
- **GREEN is not enough.** Run regression checks and review the diff for unnecessary implementation after the focused test passes.
- **Small tasks, progressive context.** Build separate discovery, test, and implementation context packs; retrieve only evidence needed for the current TDD stage.
- **Structure before text.** Use ast-grep for code-aware structural discovery and ripgrep only for non-code/textual evidence or fallback.
- **RED drives retrieval.** Test failures, stack frames, file/line locations, and diagnostics become high-priority evidence for implementation context.
- **Reconstruct, don't accumulate.** Every model call gets a fresh bounded context assembled from the current repository and explicit run state; correctness never depends on LLM conversation history.
- **Compact verified work.** After each slice, retain structured verified behaviors, decisions, constraints, and scoped learnings—not old prompts, whole contexts, or failed patch bodies.
- **Tools over guessing.** Search, inspect, patch, test, and compile through explicit harness-controlled tools.
- **Verify composition.** After all sub-tasks pass, verify the complete repository against the original task.
- **Bounded autonomy.** Limit repairs and escalate ambiguous/high-risk work.

## Workflow

```text
Developer Task
     |
     v
 DECOMPOSE
     |
     v
Minimal independently verifiable vertical slices
     |
     +--> SubTask
     |      |
     |   LOCATE / GATHER
     |      |
     |   WRITE MINIMAL TEST
     |      |
     |   CONFIRM RED -------- test passes already --> REVISE / ESCALATE
     |      |
     |   IMPLEMENT MINIMUM
     |      |
     |   CONFIRM GREEN
     |      | fail
     |    REPAIR
     |      |
     |   REGRESSION VERIFY
     |      |
     |   MINIMALITY REVIEW
     |      |
     |   VERIFIED
     |
    ... next ready SubTask
     |
     v
FINAL VERIFY
     |
     v
Result / Escalation
```

A sub-task is the **smallest vertical slice of behavior that can be meaningfully verified on its own**. It may cross storage, domain, API, UI, and test layers when those changes are jointly required to expose one observable behavior.

For every slice, CodeMill owns the TDD sequence. It creates the smallest test that expresses the slice's acceptance criterion, confirms the test fails for the expected reason, and only then asks the coding model for the smallest production change that makes it pass. The test is protected during implementation.

Sub-tasks declare dependencies, and CodeMill only executes a sub-task after its dependencies have verified.

After a slice verifies, CodeMill compacts it into structured run state. The current repository remains authoritative; later slices retrieve only relevant verified facts and evidence-backed learnings. Learnings are scoped to files/symbols/concepts and may be superseded by newer repository evidence, preventing context from growing monotonically across a long task.

## Repository layout

```text
codemill/
  __init__.py
  models.py
  tools.py
  verifier.py
  harness.py
docs/
  PLAN.md
  TECHNICAL.md
tests/
  test_harness.py
```

## Status

CodeMill is an in-progress **v0 prototype**. The core includes structured decomposition, harness-enforced TDD, repository tools, pytest verification, a llama.cpp adapter, scope budgets, and benchmark scaffolding. If the plan is empty, an explicit review must cite existing tests, which the harness runs before reporting an unchanged task as verified. The CLI refuses dirty repositories, emits a JSON run result, and writes a reviewable artifact bundle. A complete real-model end-to-end run remains outstanding.

See [the delivery plan](docs/PLAN.md) and [technical design](docs/TECHNICAL.md).

## Development

CodeMill uses **uv** for Python and dependency management, with `pyproject.toml` as the project configuration.

Requires Python 3.11+, uv, ast-grep, ripgrep, and a locally running llama.cpp `llama-server`. CodeMill initially assumes the server is already running at `http://127.0.0.1:9090`; model loading and model paths are owned by llama-server, not CodeMill.

```bash
uv sync
uv run pytest
uv run codemill \\
  --repository /path/to/clean/repository \\
  --output-directory /path/outside/repository/codemill-runs \\
  --task "Add a greeting helper" \\
  --acceptance-criterion "greeting('Ada') returns 'Hello, Ada!'" \\
  --constraint "Use the standard library"
```

Repeat `--acceptance-criterion` and `--constraint` to provide multiple values. The CLI records the starting Git revision/status in its JSON output and refuses to run when the repository is dirty; commit, stash, or discard existing changes first. It also writes a run artifact bundle to the required output directory, which must be outside the target repository.

Add dependencies with `uv add <package>` and development dependencies with `uv add --dev <package>`. Commit `uv.lock` so development and CI resolve the same dependency set.

## License

MIT
