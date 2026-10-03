# CodeMill

**A verification-first coding harness for small language models.**

CodeMill explores how small coding models (initially around 9B parameters) can perform useful repository-level software engineering by first decomposing a developer task into the **smallest independently verifiable vertical slices**, then executing each change with strong context selection, constrained actions, deterministic verification, and bounded repair.

## Design principles

- **Decompose into vertical slices.** Each sub-task delivers one observable behavior through whatever layers are required to verify it.\n- **Smallest independently verifiable unit.** Split further only when every resulting slice still has a meaningful observable verification condition.\n- **Avoid horizontal decomposition.** Database, service, API, UI, or tests are not separate sub-tasks merely because they are separate technical layers.\n- **Verification belongs to the slice.** Production changes and the focused tests proving them normally live in the same sub-task.
- **One bounded cycle per sub-task.** Each sub-task gets its own locate, plan, patch, verify, repair, and review cycle.
- **Small tasks, strong context.** Retrieve only code needed for the current sub-task.
- **Tools over guessing.** Search, inspect, patch, test, and compile through explicit tools.
- **Verification over confidence.** A sub-task is not complete until deterministic checks pass.
- **Minimal diffs.** Prefer the smallest change satisfying the sub-task.
- **Verify composition.** After all sub-tasks pass, verify the complete repository against the original task.
- **Bounded autonomy.** Limit repairs and escalate ambiguous/high-risk work.
- **Measure real engineering.** Optimize for verified tasks, cost, latency, and human intervention.

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
     +--> ST-001: LOCATE -> PLAN -> PATCH -> VERIFY
     |                                  ^       |
     |                                  + REPAIR+
     |                                      |
     |                                   REVIEW
     |
     +--> ST-002: LOCATE -> PLAN -> PATCH -> VERIFY -> REVIEW
     |
    ...
     |
     v
FINAL VERIFY
     |
     v
Result / Escalation
```

A sub-task is the **smallest vertical slice of behavior that can be meaningfully verified on its own**. It may cross storage, domain, API, UI, and test layers when those changes are jointly required to expose one observable behavior. Sub-tasks declare dependencies, and CodeMill only executes a sub-task after its dependencies have verified.

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

CodeMill is at **v0 / bootstrap**. The current core models task decomposition, dependency-ordered sub-task execution, bounded repair loops, and final verification. The next milestone is a structured decomposition protocol that enforces the vertical-slice invariant.

See [the delivery plan](docs/PLAN.md) and [technical design](docs/TECHNICAL.md).

## Development

CodeMill uses **uv** for Python and dependency management, with `pyproject.toml` as the project configuration.

Requires Python 3.11+ and uv.

```bash
uv sync
uv run pytest
```

Add dependencies with `uv add <package>` and development dependencies with `uv add --dev <package>`. Commit `uv.lock` so development and CI resolve the same dependency set.

## License

MIT
