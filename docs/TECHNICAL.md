# CodeMill Technical Design

## 1. System boundary and execution hierarchy

CodeMill is a hierarchical orchestrator around a small coding model. The model never receives unrestricted repository or shell access.

The outer loop reasons about **work decomposition and composition**. The inner loop solves one minimal sub-task at a time.

```text
Original Task
     |
 NORMALIZE
     |
 DECOMPOSE <------ Repository summary
     |
 validate dependency graph
     |
     v
+---------------------------------------+
| Next ready SubTask                    |
|                                       |
| LOCATE -> PLAN -> GATHER -> PATCH     |
|                           |           |
|                     POLICY_CHECK      |
|                           |           |
|                        VERIFY         |
|                      /        \       |
|                   pass        fail    |
|                    |            |     |
|                  REVIEW       REPAIR -+
+---------------------------------------+
     |
     | verified; unlock dependents
     v
 next ready SubTask
     |
     v
 FINAL_VERIFY(original acceptance criteria)
     |
     v
 VERIFIED / ESCALATED / FAILED
```

## 2. Why decomposition is first-class

A small model should not carry the full cognitive burden of a large software task through every generation turn. DECOMPOSE converts the original request into bounded units with explicit success conditions.

A valid sub-task should be:

- **minimal:** no unrelated behavior bundled into it;
- **coherent:** one meaningful repository change;
- **independently verifiable:** has an observable success condition;
- **dependency-aware:** names prerequisite sub-tasks;
- **bounded:** carries an expected change scope;
- **composable:** completion advances the original task.

Minimal does not mean one-line edits. Splitting below the level at which useful verification is possible is counterproductive.

## 3. Core contracts

`Task` contains the original objective, acceptance criteria, and constraints.

`SubTask` contains:

```text
id
objective
acceptance_criteria
constraints
depends_on
```

Planned additions include expected files/symbols, risk class, and change budget.

The model adapter exposes semantic operations:

```text
decompose(task, tools) -> SubTask[]
locate(subtask, tools) -> evidence requests
plan(subtask, context) -> bounded plan
create_patch(subtask, plan, tools) -> patch
repair_patch(subtask, diagnostics, tools) -> patch
review(subtask, diff, verification) -> review
```

The bootstrap currently combines LOCATE and PLAN; they will split when retrieval is implemented.

## 4. Decomposition protocol

DECOMPOSE receives the original task, acceptance criteria, constraints, and a lightweight repository summary. It should not receive the entire repository.

Target structured output:

```json
{
  "subtasks": [
    {
      "id": "ST-001",
      "objective": "Add token validation primitive",
      "acceptance_criteria": ["valid tokens return decoded claims"],
      "constraints": ["no new runtime dependency"],
      "depends_on": [],
      "expected_scope": {
        "max_files": 2,
        "max_changed_lines": 80
      }
    },
    {
      "id": "ST-002",
      "objective": "Use token validation in request middleware",
      "acceptance_criteria": ["invalid tokens produce an unauthorized response"],
      "constraints": [],
      "depends_on": ["ST-001"],
      "expected_scope": {
        "max_files": 3,
        "max_changed_lines": 100
      }
    }
  ]
}
```

Before execution CodeMill validates unique IDs, dependency existence, acyclicity, topological ordering, non-empty objectives, and usable acceptance criteria.

The decomposer proposes the graph; the orchestrator owns whether that graph is executable.

## 5. Scheduling and repository state

Execute only a sub-task whose dependencies are VERIFIED. Initially use deterministic sequential topological execution.

Each verified sub-task changes the workspace seen by later sub-tasks. This is intentional: dependent work should build on verified repository state rather than stale original state.

Parallel execution may be explored later only for independent sub-tasks with isolated workspaces and an explicit merge/reverification strategy.

## 6. Context packing

Context is built **per sub-task**. Priority:

1. target symbols;
2. relevant interfaces/types;
3. tests covering the target;
4. direct callers;
5. direct dependencies;
6. verified changes from prerequisite sub-tasks;
7. analogous implementations;
8. repository conventions;
9. relevant history/docs.

Every fragment records path, range, symbols, `why_selected`, and provenance. Deduplicate ranges and reserve output budget.

## 7. Tools and workspace

Initial capability surface:

```text
search_text(query)
read_file(path, start?, end?)
apply_patch(patch)
```

Planned read capabilities include tree listing, symbol lookup, references, tests, history, and diff inspection.

Pin the input commit and use a disposable worktree/container. Normalize paths relative to repository root; reject symlink escape and traversal. The LLM never receives a raw shell capability.

## 8. Patch policy and budgets

Enforce budgets both per sub-task and cumulatively:

```json
{
  "max_files": 3,
  "max_changed_lines": 100,
  "allow_dependencies": false,
  "allow_public_api": false,
  "allow_schema_changes": false
}
```

Hard violations reject or escalate. Initially disallow binary changes and sensitive metadata/secrets edits. Optionally require edits to intersect the sub-task's planned scope.

## 9. Verification at two levels

### Sub-task verification

Answers: **does this repository state correctly complete this sub-task without breaking the current verified state?**

Run cheapest-first: patch validation, format, lint/static checks, typecheck/compile, targeted tests, then affected tests.

A sub-task does not unlock dependents until verification passes.

### Final task verification

After all sub-tasks verify, evaluate the combined repository against the **original task and acceptance criteria**. Run integration/broader checks needed to detect composition failures that isolated verification cannot catch.

Final failure must not be silently attributed to the last sub-task. The trace should preserve evidence needed for future diagnosis/replanning.

## 10. Repair

REPAIR operates within one sub-task. Supply original task context, current sub-task, current diff, failing stage, normalized diagnostics, relevant local source, verified prerequisite changes, and remaining budget.

It is not a fresh solve. Require the smallest correction. Default target is at most three repair turns; detect identical failures and patch oscillation.

## 11. Review

REVIEW is distinct from deterministic verification. It checks scope and intent: unnecessary changes, violation of the sub-task plan, accidental API expansion, suspicious deletion, or behavior not covered by verification.

Reviewer output should be structured and advisory/policy-driven, not a replacement for tests or compilers.

## 12. State and failure semantics

Outer states:

```text
NORMALIZE -> DECOMPOSE -> VALIDATE_GRAPH -> EXECUTE_SUBTASKS
 -> FINAL_VERIFY -> VERIFIED
```

Sub-task states:

```text
PENDING -> LOCATE -> PLAN -> GATHER -> PATCH -> POLICY_CHECK
 -> VERIFY -> REPAIR* -> REVIEW -> VERIFIED
```

Terminal alternatives include EXHAUSTED, ESCALATED, and FAILED.

Every transition emits a structured event keyed by run ID and sub-task ID.

## 13. Security

Treat LLM output and repository content as untrusted: no raw model shell; allowlisted subprocess commands; time/memory limits; network off by default; filtered environment; no secrets in model context; disposable workspace; validated mutations.

Repository content may contain prompt injection. Retrieved text is evidence, not harness instruction.

## 14. Inference abstraction

Core CodeMill stays provider-independent. First adapter target is an OpenAI-compatible local endpoint.

```toml
[model]
base_url = "http://localhost:8000/v1"
model = "local-coder-9b"
temperature = 0.1
max_output_tokens = 4096

[harness]
max_repairs = 3
context_tokens = 16000
```

DECOMPOSE may eventually use a different model/configuration from PATCH/REPAIR, but the initial design should prove whether one 9B model can perform all specialised operations.

## 15. Observability and evaluation

Persist original task/repository SHA, decomposition graph, sub-task transitions, context fragment IDs, tool calls/durations, patch hashes, verifier results, tokens, repair counts, and final diff/status.

Do not require hidden model reasoning. Store decisions, evidence, actions, and outcomes.

A run succeeds only when final required and hidden checks pass. Historical-patch similarity is diagnostic, not correctness.

Primary metric:

```text
total inference + compute cost
--------------------------------
independently verified correct tasks
```

Also measure decomposition size/depth, per-sub-task success, retrieval quality, unnecessary edits, repairs, latency, escalation, regressions, and human intervention.

## 16. Immediate implementation choices

- Python 3.11+ with uv and `pyproject.toml`.
- Standard library first; pytest for tests.
- sequential dependency-aware execution first.
- ripgrep for textual retrieval.
- unified diffs for mutation.
- allowlisted verifier subprocesses.
- provider-independent model protocol.
- no vector DB until retrieval baselines justify it.
- no multi-agent framework; specialization is explicit operations/prompts.
