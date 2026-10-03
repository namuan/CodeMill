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
| LOCATE -> GATHER                      |
|      |                                |
| WRITE_TEST -> CONFIRM_RED             |
|      |                                |
| IMPLEMENT_MINIMUM -> CONFIRM_GREEN    |
|                         | fail        |
|                       REPAIR ---------+
|                         |
|                  REGRESSION_VERIFY
|                         |
|                  MINIMALITY_REVIEW
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

The fundamental invariant is:

> **A sub-task is the smallest independently verifiable vertical slice of the original task.**

A valid sub-task should be:

- **vertical:** delivers one observable behavior through every technical layer required for that behavior;
- **minimal:** cannot be split further without producing pieces that lack meaningful independent verification;
- **coherent:** contains one behavior rather than unrelated changes;
- **independently verifiable:** has an observable success condition;
- **verification-complete:** focused tests/checks proving the behavior belong to the slice;
- **dependency-aware:** names prerequisite slices;
- **bounded:** carries an expected change scope;
- **composable:** completion advances the original task.

Minimal does not mean one file, one layer, or one-line edits. A slice may change persistence, domain logic, API/UI code, and tests together when all are required for one observable behavior.

Horizontal decomposition is an anti-pattern when the pieces are not independently meaningful. Avoid separate tasks such as "add database field", "add service method", "add endpoint", and "add tests" when none represents a useful verified behavior alone.

The decomposition test is: **Can this slice be made smaller while every resulting piece still has an independently observable verification condition?** If yes, split it. If no, it is a candidate minimal vertical slice.

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

The model adapter exposes specialised semantic operations:

```text
decompose(task, tools) -> SubTask[]
locate(subtask, tools) -> evidence requests
write_test(subtask, context) -> test patch
implement(subtask, failing_test, context) -> production patch
repair(subtask, failing_test, diagnostics, context) -> production patch
review(subtask, diff, verification) -> review
```

The harness owns sequencing. In particular, it never requests IMPLEMENT before it has accepted a failing test and demonstrated RED.

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

### Decomposition quality validation

Graph validity is necessary but not sufficient. CodeMill should also validate or review decomposition quality:

- every slice states an observable behavior;
- acceptance criteria verify behavior rather than implementation steps;
- tests are not standalone sub-tasks unless the test artifact itself is the requested behavior;
- technical layers are combined when jointly necessary for verification;
- unrelated behaviors are not bundled into one slice;
- a proposed split is accepted only when all children remain independently verifiable.

Undesirable horizontal decomposition:

```text
ST-001 Add database column
ST-002 Add repository method
ST-003 Add API serialization
ST-004 Add tests
```

Preferred vertical decomposition:

```text
ST-001 Expose the new field through the API
       Changes: persistence + mapping + serialization + focused test
       Verify: API response returns the field correctly
```

Additional observable behavior becomes another vertical slice.

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

## 9. Harness-enforced TDD

TDD is a control-flow invariant, not an instruction the model may choose to follow.

For each vertical slice:

```text
LOCATE / GATHER
      |
WRITE_MINIMAL_TEST
      |
CONFIRM_RED
   |       \
   |        +-- test already passes / wrong failure -> REVISE_TEST or ESCALATE
   v
FREEZE_TEST
      |
IMPLEMENT_MINIMUM
      |
CONFIRM_GREEN
   |       \
   |        +-- fail -> REPAIR -> CONFIRM_GREEN
   v
REGRESSION_VERIFY
      |
MINIMALITY_REVIEW
      |
VERIFIED
```

### Test generation

The harness requests the smallest focused test that demonstrates the slice's observable acceptance criterion. The test should avoid asserting incidental implementation details unless those details are part of the requested contract.

### RED is mandatory

The harness executes the new test before any production implementation patch is accepted. RED must fail for the expected missing behavior. Syntax errors, broken fixtures, unrelated failures, or an already-passing test do not qualify.

If the test already passes, the harness must revise the test when the acceptance criterion is not actually covered, mark the slice already satisfied when evidence supports that conclusion, or escalate ambiguity. It must not manufacture production changes merely to create work.

### Test immutability

Once a test has demonstrated valid RED, record its patch/hash as the accepted specification for the slice. IMPLEMENT and REPAIR may modify production code only. Any attempt to modify, delete, skip, weaken, or bypass the protected test is rejected before application.

### Minimal implementation

The implementation model receives the slice, accepted failing test, relevant source context, constraints, and change budget. Its contract is:

> Make the accepted failing test pass with the smallest production-code change. Do not modify the test. Do not add behavior, abstractions, APIs, dependencies, or refactors not required by the slice.

GREEN is necessary but not sufficient. Passing the focused test is followed by regression verification and minimality review.

### Minimality review

Compare the production diff against the slice and accepted test. Reject or repair speculative abstractions, unrelated refactors, extra public surface, unnecessary files/LOC, dead code, or behavior unsupported by the acceptance criterion.

Minimality is semantic, not simply lowest line count: the implementation should be the smallest maintainable change consistent with repository conventions and the requested behavior.

## 10. Verification at two levels

### Sub-task verification

Answers: **does this repository state correctly complete this sub-task without breaking the current verified state?**

Run cheapest-first: patch validation, format, lint/static checks, typecheck/compile, targeted tests, then affected tests.

A sub-task does not unlock dependents until verification passes.

### Final task verification

After all sub-tasks verify, evaluate the combined repository against the **original task and acceptance criteria**. Run integration/broader checks needed to detect composition failures that isolated verification cannot catch.

Final failure must not be silently attributed to the last sub-task. The trace should preserve evidence needed for future diagnosis/replanning.

## 11. Repair

REPAIR operates within one sub-task. Supply original task context, current sub-task, current diff, failing stage, normalized diagnostics, relevant local source, verified prerequisite changes, and remaining budget.

It is not a fresh solve. Require the smallest correction. Default target is at most three repair turns; detect identical failures and patch oscillation.

## 12. Review

REVIEW is distinct from deterministic verification. It checks scope and intent: unnecessary changes, violation of the sub-task plan, accidental API expansion, suspicious deletion, or behavior not covered by verification.

Reviewer output should be structured and advisory/policy-driven, not a replacement for tests or compilers.

## 13. State and failure semantics

Outer states:

```text
NORMALIZE -> DECOMPOSE -> VALIDATE_GRAPH -> EXECUTE_SUBTASKS
 -> FINAL_VERIFY -> VERIFIED
```

Sub-task states:

```text
PENDING -> LOCATE -> GATHER -> WRITE_TEST -> CONFIRM_RED
 -> FREEZE_TEST -> IMPLEMENT -> CONFIRM_GREEN
 -> REPAIR* -> REGRESSION_VERIFY -> MINIMALITY_REVIEW -> VERIFIED
```

IMPLEMENT is unreachable until valid RED has been recorded. REPAIR cannot mutate the protected test.

Terminal alternatives include EXHAUSTED, ESCALATED, and FAILED.

Every transition emits a structured event keyed by run ID and sub-task ID.

## 14. Security

Treat LLM output and repository content as untrusted: no raw model shell; allowlisted subprocess commands; time/memory limits; network off by default; filtered environment; no secrets in model context; disposable workspace; validated mutations.

Repository content may contain prompt injection. Retrieved text is evidence, not harness instruction.

## 15. Inference abstraction

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

## 16. Observability and evaluation

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

## 17. Immediate implementation choices

- Python 3.11+ with uv and `pyproject.toml`.
- Standard library first; pytest for tests.
- sequential dependency-aware execution first.
- ripgrep for textual retrieval.
- unified diffs for mutation.
- protected test patches/hashes after valid RED.
- separate test and production patch policies.
- allowlisted verifier subprocesses.
- provider-independent model protocol.
- no vector DB until retrieval baselines justify it.
- no multi-agent framework; specialization is explicit operations/prompts.
