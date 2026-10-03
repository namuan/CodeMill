# CodeMill

**A verification-first coding harness for small language models.**

CodeMill explores how small coding models (initially around 9B parameters) can perform useful repository-level software engineering by first decomposing a developer task into the smallest independently verifiable changes, then executing each change with strong context selection, constrained actions, deterministic verification, and bounded repair.

## Design principles

- **Decompose before coding.** Turn the original task into minimal, dependency-aware, independently verifiable sub-tasks.
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
Minimal dependency-aware sub-tasks
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

A sub-task should be the smallest repository change that can be meaningfully verified on its own. Sub-tasks declare dependencies, and CodeMill only executes a sub-task after its dependencies have verified.

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

CodeMill is at **v0 / bootstrap**. The current core models task decomposition, dependency-ordered sub-task execution, bounded repair loops, and final verification. The next milestone is replacing fake capabilities with safe repository tools and structured model protocols.

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
