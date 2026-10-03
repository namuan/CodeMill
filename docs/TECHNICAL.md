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

## 2. v0 product contract

v0 is an end-to-end working prototype, not only an in-memory orchestration library. A user supplies a repository and task; CodeMill calls a real model through a running llama.cpp `llama-server`, drives the task through the harness-controlled workflow, and writes a reviewable result bundle. A run ends as VERIFIED, ESCALATED, or FAILED. It must not report VERIFIED unless the evidence required by the workflow is present.

### 2.1 Invocation and repository policy

The initial user interface may be a CLI. It accepts a repository path, task objective, optional acceptance criteria, and constraints. It records the starting revision and working-tree status before mutation. v0 must either safely preserve pre-existing user changes in an isolated worktree or refuse to mutate a dirty repository with a clear diagnostic; it must never silently overwrite or discard them. The chosen policy is part of the interface and is recorded in run metadata.

A run uses a unique run directory for its artifacts. The output location is reported to the user and must not be inside a protected source/test path by accident. Failure to initialize the workspace, reach the model, parse a response, apply a valid patch, or run required verification yields FAILED or ESCALATED with diagnostics, not a successful result.

### 2.2 Required result bundle

Every run, including failed and escalated runs, writes as much of the following bundle as is available:

```text
run.json                 task, repository revision/status, configuration, final status
plan.json                normalized task, sub-tasks, dependencies, validation outcome
trace.jsonl              ordered model/tool/state/verification events
final.diff               resulting repository diff, if any
changed-files.json       changed paths and change-budget results
verification.json        command, purpose, exit status, diagnostics, timestamps
result.md                concise human-readable summary and escalation details
```

The exact serialization may evolve, but the information must be captured. Artifacts distinguish model claims from harness-observed facts. Record prompts or packed contexts only as needed for reproducibility and security; never persist secrets or assume conversation transcripts are authoritative. Preserve diagnostic output subject to size limits and secret redaction.

A VERIFIED run requires evidence of valid RED for each newly implemented slice, test protection through implementation/repair, focused GREEN, required regression verification, accepted scope/minimality review, and final verification against the original task. If a task is already satisfied, CodeMill may report VERIFIED only when existing repository evidence demonstrates all acceptance criteria and final verification passes; it must not fabricate a failing test or unnecessary implementation. Ambiguous already-satisfied cases escalate.

The end-to-end v0 acceptance test runs a bounded task against a fixture repository using a real llama.cpp endpoint, then checks the final repository state and bundle. Deterministic fake-model tests cover state-machine and failure cases. Real-server integration can be opt-in in CI, but it must be run before declaring the v0 prototype usable.

## 3. Why decomposition is first-class

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

## 4. Core contracts

`Task` contains the original objective, acceptance criteria, and constraints.

`SubTask` contains:

```text
id
objective
acceptance_criteria
constraints
depends_on
expected_scope.max_files
expected_scope.max_changed_lines
expected_scope.allow_dependencies
expected_scope.allow_public_api
expected_scope.allow_schema_changes
```

The decomposition JSON schema is strict: required fields and types are checked, unknown fields are rejected, and acceptance criteria must be non-empty. Graph validation separately checks IDs and dependencies before deterministic scheduling. Vertical-slice quality remains a semantic review concern; structural validation must not pretend to prove that a proposed slice is minimal or behaviorally coherent.

The model adapter exposes specialised semantic operations:

```text
decompose(task, tools) -> structured JSON text
review_decomposition(task, subtasks, tools) -> structured quality decision
locate(subtask, tools) -> evidence requests
write_test(subtask, context) -> test patch
implement(subtask, failing_test, context) -> production patch
repair(subtask, failing_test, diagnostics, context) -> production patch
review(subtask, diff, verification) -> review
```

The harness owns sequencing. In particular, it never requests IMPLEMENT before it has accepted a failing test and demonstrated RED.

## 5. Decomposition protocol

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

Before execution CodeMill parses the structured JSON against the strict decomposition contract, then validates unique IDs, dependency existence, acyclicity, topological ordering, non-empty objectives, and usable acceptance criteria. A malformed response or invalid graph is rejected before repository mutation.

The decomposer proposes the graph; the orchestrator owns whether that graph is executable. A separate `review_decomposition` operation evaluates whether slices are independently verifiable vertical behaviors rather than horizontal layer tasks or bundles of unrelated work. Rejection escalates before any repository mutation. Acceptance is evidence for planning quality, not a substitute for deterministic verification of implemented behavior.

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

## 6. Scheduling and repository state

Execute only a sub-task whose dependencies are VERIFIED. Initially use deterministic sequential topological execution.

Each verified sub-task changes the workspace seen by later sub-tasks. This is intentional: dependent work should build on verified repository state rather than stale original state.

Parallel execution may be explored later only for independent sub-tasks with isolated workspaces and an explicit merge/reverification strategy.

## 7. Progressive context construction

CodeMill does not build one generic context pack for a sub-task. Context is **stage-specific and progressively refined by deterministic evidence**.

```text
SubTask
   |
   +--> repository map + structural discovery
   |          |
   |          v
   |     TEST CONTEXT
   |          |
   |      WRITE_TEST
   |          |
   |      CONFIRM_RED
   |          |
   |     failure evidence
   |     stack/file/line
   |     diagnostics
   |          |
   |          v
   +--> IMPLEMENTATION CONTEXT
              |
        IMPLEMENT_MINIMUM
```

### 6.1 Repository map and discovery

Begin with inexpensive metadata rather than file contents: repository tree, source/test roots, languages, package/module boundaries, build/test configuration, and verified prerequisite slices.

Derive candidate concepts and identifiers from the sub-task objective and acceptance criteria. Use structural discovery to identify the behavioral surface and its test neighborhood. Expand only as needed through definitions/declarations, imports, structurally discoverable calls/usages, nearby tests, required types/interfaces, and analogous local patterns.

The context engine should represent relationships between evidence rather than treating search hits as an unordered bag. For example:

```text
acceptance criterion
   |
public behavior
   +-- nearby tests / fixtures
   +-- target definition
          +-- relevant call/import
```

### 6.2 Test context

WRITE_TEST receives an aggressively small behavioral context:

1. sub-task objective and acceptance criteria;
2. constraints;
3. closest existing test conventions;
4. fixtures/helpers needed to exercise the behavior;
5. public function/API/interface under test;
6. types required to construct inputs and assert outputs;
7. relevant verified prerequisite changes.

Do not automatically include implementation internals merely because discovery found them. The test should encode requested behavior, not mirror a proposed implementation.

### 6.3 RED-driven implementation context

CONFIRM_RED is also a retrieval step. Parse deterministic failure evidence such as assertion output, exception type/message, stack frames, file/line locations, compiler/type diagnostics, and implicated symbols.

These signals outrank speculative pre-RED retrieval. Read bounded ranges around implicated locations and structurally discover the immediately relevant definitions/calls/imports.

IMPLEMENT receives:

1. sub-task and acceptance criteria;
2. accepted immutable failing test;
3. normalized RED diagnostics;
4. implicated production symbols/ranges;
5. required interfaces/types;
6. closest relevant implementation/error-handling convention;
7. relevant verified prerequisite changes;
8. constraints and remaining change budget.

REPAIR uses the same principle: new GREEN failures refine context rather than causing broad repository expansion.

### 6.4 Context fragment provenance

Every fragment should carry:

```text
path
start_line
end_line
symbols
kind
why_selected
source
score
```

Possible sources include structural search, textual search, nearby test discovery, RED stack frame, compiler diagnostic, verified prerequisite diff, and explicit model evidence request.

Deduplicate overlapping ranges and record why every fragment entered the prompt. This makes retrieval quality measurable.

### 6.5 Context budget

Optimize for **minimum sufficient evidence**, not maximum context-window utilization. Priority for implementation is normally: slice/acceptance criteria, failing test, RED diagnostics, exact implicated symbols, required interfaces/types, direct relevant relationships, analogous local convention, prerequisite diff, then repository documentation.

If the budget is exceeded, discard lower-ranked evidence rather than truncating high-value fragments blindly.

### 6.6 Persistent state and compaction

Working context is disposable. Persistent state is structured.

CodeMill maintains three distinct sources of durable state:

- **repository state:** the current workspace is authoritative; retrieve current source rather than trusting prose summaries of code;
- **task state:** original task/criteria/constraints plus concise records of verified sub-tasks and their dependencies;
- **learning state:** scoped, evidence-backed facts, conventions, decisions, and failure learnings that may help later work.

There is a hard invariant:

> **No correctness dependency on LLM conversation history.**

Every model operation must be reproducible from the current repository and explicit CodeMill state. A later sub-task can therefore use a fresh llama.cpp request/session without receiving previous prompts or transcripts.

After each verified sub-task, run a COMPACT transition:

```text
VERIFIED
   |
 COMPACT
   +-- record verified behavior
   +-- record accepted test
   +-- record changed files/symbols
   +-- record verification evidence
   +-- extract reusable scoped learnings
   +-- discard old packed contexts/prompts
   +-- discard superseded diagnostics
   +-- discard failed patch bodies
   |
next SubTask
```

A verified-slice record should be compact enough to retrieve as prerequisite context without replacing current source as truth.

### 6.7 Learning store

Do not append every failure to every future prompt. Convert only useful evidence into typed learnings and retrieve them when their scope intersects the current sub-task/evidence graph.

Initial learning kinds:

```text
repository_fact
convention
decision
failure_learning
verification_fact
constraint
```

A learning should carry:

```text
id
kind
statement
scope.paths
scope.symbols
scope.concepts
derived_from_subtask
repository_revision
evidence
confidence
superseded_by
```

For example, a failed implementation that reveals a generic exception handler breaks an existing malformed-token behavior can become a scoped failure learning for that handler/symbol. The failed patch itself is not durable context.

Retrieval precedence is:

```text
current repository evidence
    > recent verified fact/decision
    > verified scoped learning
    > older/inferred learning
```

Learnings are candidates, not authority. If current source or newer verification contradicts a learning, prefer current evidence and mark the older learning superseded.

This produces a bounded context lifecycle:

```text
GATHER -> RANK -> PACK -> MODEL -> VERIFY -> COMPACT
   ^                                      |
   +------ current repo + run state ------+
```

## 8. Retrieval tools and workspace

CodeMill uses **ast-grep as the primary retrieval engine for source code**. ast-grep provides syntax/AST-aware structural matching and structured result ranges suitable for deterministic context construction. It is used for retrieval only; its rewrite functionality is not part of CodeMill's mutation path.

Use **ripgrep (rg) as the fallback for non-code and textual evidence**: Markdown/documentation, configuration/data files without useful structural support, literal error strings, generated text, and textual searches that do not require syntax awareness.

The semantic read capability surface is:

```text
list_tree(path, depth)
find_definitions(name)
find_structural(pattern)
find_calls(name)
find_imports(name)
find_tests_for(symbol_or_path)
read_range(path, start, end)
search_text(query, paths?)
```

The harness translates these semantic operations into ast-grep or rg invocations. The model does not receive either CLI or a raw shell.

ast-grep understands local syntax structure but is not treated as a semantic type/reference engine. CodeMill should not claim compiler/LSP-level certainty from structural matches. If evaluation later shows that type resolution, true reference resolution, or call hierarchy is a retrieval bottleneck, an LSP/compiler-backed layer can be considered then.

Mutation/execution capabilities are harness-only:

```text
apply_validated_patch(diff)
git_diff(scope)
git_status()
run_targeted_test(target)
run_regression_checks(scope)
run_formatter()
run_linter()
run_typecheck()
run_build()
protect_test(paths_or_hash)
check_allowed_paths(diff)
check_change_budget(diff)
```

Pin the input commit and use a disposable worktree/container for mutations and verification. Record initial Git status and preserve user changes; v0 may refuse dirty worktrees rather than implement safe isolation, but must not silently mutate or discard pre-existing changes. Normalize paths relative to repository root; reject symlink escape and traversal. All subprocesses are allowlisted, parameterized by the harness, bounded by time/output limits, and run with a filtered environment. Repository content and model output are untrusted data, never harness instructions.

## 9. Patch policy and budgets

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

## 10. Harness-enforced TDD

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

## 11. Verification at two levels

### Sub-task verification

Answers: **does this repository state correctly complete this sub-task without breaking the current verified state?**

Run cheapest-first: patch validation, format, lint/static checks, typecheck/compile, targeted tests, then affected tests.

A sub-task does not unlock dependents until verification passes.

### Final task verification

After all sub-tasks verify, evaluate the combined repository against the **original task and acceptance criteria**. Run integration/broader checks needed to detect composition failures that isolated verification cannot catch.

Final failure must not be silently attributed to the last sub-task. The trace should preserve evidence needed for future diagnosis/replanning.

## 12. Repair

REPAIR operates within one sub-task. Supply original task context, current sub-task, current diff, failing stage, normalized diagnostics, relevant local source, verified prerequisite changes, and remaining budget.

It is not a fresh solve. Require the smallest correction. Default target is at most three repair turns; detect identical failures and patch oscillation.

## 13. Review

REVIEW is distinct from deterministic verification. It checks scope and intent: unnecessary changes, violation of the sub-task plan, accidental API expansion, suspicious deletion, or behavior not covered by verification.

Reviewer output should be structured and advisory/policy-driven, not a replacement for tests or compilers.

## 14. State and failure semantics

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

Run terminal statuses are VERIFIED, ESCALATED, and FAILED. Repair-budget exhaustion, verifier failure, and operational errors are FAILED outcomes with structured reason codes; use ESCALATED when human input or unsupported capability is required. Sub-task outcomes remain non-terminal workflow results and must not be confused with the run status.

Every transition emits a structured event with a run ID, event name, optional sub-task ID, and diagnostics. Event order is authoritative; events are recorded at each model-operation boundary, patch application, verifier result, state transition, and terminal outcome.

## 15. Security

Treat LLM output and repository content as untrusted: no raw model shell; allowlisted subprocess commands; time/memory/output limits; outbound network off by default except the configured local llama-server endpoint; filtered environment; no secrets in model context; disposable workspace; validated mutations.

Repository content may contain prompt injection. Retrieved text is evidence, not harness instruction.

## 16. Inference backend

The first CodeMill backend is a locally running llama.cpp `llama-server`.

For the bootstrap implementation, the endpoint is intentionally hard-coded:

```text
http://127.0.0.1:9090
```

CodeMill assumes llama-server has already been started by the user. Process lifecycle, GGUF/model path, model loading, GPU/offload settings, and other llama.cpp runtime configuration remain outside CodeMill. CodeMill only owns requests to the running HTTP server.

Use llama-server's OpenAI-compatible API surface so the adapter remains small. Configuration can be introduced later after the harness behavior is proven; initially there is no model-path setting and no configurable host/port.

Conceptually:

```text
CodeMill
   |
   | HTTP / OpenAI-compatible requests
   v
127.0.0.1:9090
   |
llama-server
   |
locally loaded model
```

The same local model initially performs DECOMPOSE, LOCATE, WRITE_TEST, IMPLEMENT, REPAIR, and REVIEW with operation-specific prompts/context. Later evaluation may justify different model/configuration choices per operation.

## 17. Observability and evaluation

Persist original task/repository SHA, decomposition graph, sub-task transitions, context fragment IDs, packed-context manifests, verified-slice records, scoped learning IDs/provenance/supersession, tool calls/durations, patch hashes, verifier results, tokens, repair counts, and final diff/status.

Do not require hidden model reasoning. Store decisions, evidence, actions, and outcomes.

A run succeeds only when final required and hidden checks pass. Historical-patch similarity is diagnostic, not correctness.

Primary metric:

```text
total inference + compute cost
--------------------------------
independently verified correct tasks
```

Also measure decomposition size/depth, per-sub-task success, retrieval quality, unnecessary edits, repairs, latency, escalation, regressions, and human intervention.

## 18. Immediate implementation choices

- Python 3.11+ with uv and `pyproject.toml`.
- Standard library first; pytest for tests.
- sequential dependency-aware execution first.
- ast-grep for primary source-code structural retrieval; ripgrep only for non-code/textual fallback.
- unified diffs for mutation.
- protected test patches/hashes after valid RED.
- separate test and production patch policies.
- allowlisted verifier subprocesses.
- llama.cpp `llama-server` backend at hard-coded `127.0.0.1:9090`, accessed through its OpenAI-compatible API.
- no vector DB until retrieval baselines justify it.
- no multi-agent framework; specialization is explicit operations/prompts.
