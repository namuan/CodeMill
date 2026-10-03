# CodeMill

**A verification-first coding harness for small language models.**

CodeMill explores how small coding models (initially around 9B parameters) can perform useful repository-level software engineering when the surrounding system provides strong context selection, constrained actions, deterministic verification, and bounded repair loops.

## Design principles

- **Small tasks, strong context.** Retrieve only code needed for the current decision.
- **Tools over guessing.** Search, inspect, patch, test, and compile through explicit tools.
- **Verification over confidence.** A patch is not successful until deterministic checks pass.
- **Minimal diffs.** Prefer the smallest change satisfying the task.
- **Bounded autonomy.** Limit repairs and escalate ambiguous/high-risk work.
- **Measure real engineering.** Optimize for verified patches, cost, latency, and human intervention.

## Initial workflow

```text
Task -> LOCATE -> PLAN -> PATCH -> VERIFY
                              ^       |
                              | fail  |
                              + REPAIR+
                                  |
                                 pass
                                  v
                               REVIEW
                                  |
                                  v
                         Result / Escalation
```

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

CodeMill is at **v0 / bootstrap**. The first milestone is a model-agnostic harness that can run one bounded patch task against a repository, verify it, and return structured diagnostics for repair.

See [the delivery plan](docs/PLAN.md) and [technical design](docs/TECHNICAL.md).

## Development

Requires Python 3.11+.

```bash
python -m pip install -e ".[dev]"
pytest
```

## License

MIT
