# CodeMill Delivery Plan

## Goal

Build a specialised coding harness that makes small language models useful for real repository-level software development.

CodeMill decomposes every developer task into **minimal, dependency-aware, independently verifiable vertical slices**. Each slice is then implemented using **harness-enforced test-driven development**:

```text
LOCATE/GATHER
 -> WRITE_MINIMAL_TEST
 -> CONFIRM_RED
 -> IMPLEMENT_MINIMUM
 -> CONFIRM_GREEN
 -> REGRESSION_VERIFY
 -> MINIMALITY_REVIEW
 -> VERIFIED
```

If GREEN is not reached, bounded REPAIR attempts modify implementation code only. Only verified slices unlock their dependents. After every slice completes, CodeMill runs final verification against the original task and acceptance criteria.

The primary success metric is **cost per independently verified correct task**.

## v0 target: end-to-end working prototype

v0 accepts a task for a local repository, connects to a running llama.cpp `llama-server`, and attempts the task through the decomposition and harness-enforced TDD workflow. It must either produce a verified repository state (with a change when needed) or stop with an explicit, evidence-backed escalation/failure result. Fake-model tests are useful for development but do not satisfy this target.

The v0 user-facing entry point must accept a repository location, task objective, optional acceptance criteria, and constraints. It must make the working-tree policy explicit, record the starting revision/status, and avoid silently discarding pre-existing user changes. It must support a dirty repository safely or refuse to run with a clear explanation.

A completed run produces a reviewable artifact bundle containing:

- final status: verified, escalated, or failed;
- normalized task and validated sub-task/dependency plan;
- structured event trace of model operations, tool actions, state transitions, and verification outcomes;
- final diff and changed-file list;
- verification commands, purposes, exit statuses, and relevant diagnostics;
- repair attempts and unresolved issues, including escalation reasons;
- repository revision and run metadata sufficient to identify the state that was verified.

The v0 verified outcome requires demonstrated valid RED before implementation, protected accepted tests, focused GREEN, required regression checks, accepted scope/minimality review, final verification against the original task, and a reviewable result (including a no-change result when the task is already satisfied). The prototype must fail closed or escalate when it cannot establish these conditions. Model review may reject or escalate according to harness policy, but it cannot substitute for or override deterministic verification.

The v0 implementation covers the usable core of Phases 1–4, 6–7, plus minimum per-stage context construction from Phase 5. Full context ranking/provenance, persistent scoped learning, resumable runs, and evaluation infrastructure are not prerequisites unless needed to preserve safety or correctness.

The first end-to-end acceptance test uses a fixture repository and a real llama.cpp server/model: submit a bounded task, run the complete workflow, and inspect the artifacts and resulting repository state. Fake adapters remain the default for deterministic unit tests; the real integration test may be opt-in when a local server/model is unavailable in CI.

## Language and platform expansion

The initial concrete verifier targets Python/pytest, and structural retrieval currently defaults to Python. Keep the harness contracts language- and platform-neutral where practical, and add language/runtime and operating-system adapters after the first end-to-end prototype works. Expansion should cover repository mapping, targeted test selection, regression commands, patch/path handling, process execution, and CI fixtures across supported languages and platforms rather than relying on one global test command.

## Phase 0 — Decomposition-aware bootstrap

Define task, sub-task, dependency, result, model, tool, and verifier contracts. Implement decomposition, dependency validation and deterministic scheduling, bounded repair, structured run events, and final whole-task verification.

**Exit:** fake-model tests demonstrate decomposition, graph validation/scheduling, repair, failure handling, and final verification. This is an internal foundation, not completion of v0.

## Phase 1 — Structured vertical-slice decomposition

Replace free-form decomposition with schema-constrained output. A sub-task must contain stable ID, observable behavior, acceptance criteria, constraints, dependency IDs, and expected scope/change budget.

Validate graph mechanics: unique IDs, existing dependencies, no cycles, deterministic topological order.

Enforce the **vertical-slice invariant**:

1. Each slice delivers one observable behavior.
2. It includes every technical-layer change necessary to expose that behavior.
3. A slice is split further only if every child remains independently and meaningfully verifiable.
4. Reject layer-oriented decomposition when the pieces only become useful together.
5. Reject slices that restate the original task or bundle unrelated behaviors.

The decomposition test is: **Can this slice be made smaller while every resulting piece still has its own observable verification condition?**

The machine validator enforces schema completeness, field types, non-empty behavioral acceptance criteria, expected-scope bounds, unique IDs, known dependencies, acyclicity, and deterministic ordering. It does not claim to prove semantic minimality: ambiguous or suspicious vertical-slice plans are surfaced for model review or escalation, not silently accepted as verified quality.

**Exit:** structured model output is parsed and validated before execution; malformed plans cannot mutate the repository; graph scheduling is deterministic; semantic quality concerns produce a review/escalation outcome.

## Phase 2 — Harness-enforced TDD

Make TDD a state-machine invariant rather than a prompt convention.

For every sub-task:

1. **WRITE_MINIMAL_TEST** — create the smallest focused test expressing the observable acceptance criterion.
2. **CONFIRM_RED** — run that test against the current verified repository state.
3. Require failure for the expected behavioral reason. A passing test provides no evidence that implementation is needed; revise the test or escalate.
4. Freeze/protect the accepted test.
5. **IMPLEMENT_MINIMUM** — ask the coding model for the smallest production-code change that can satisfy the failing test.
6. **CONFIRM_GREEN** — rerun the focused test.
7. On failure, enter bounded **REPAIR** using diagnostics while keeping the test immutable.
8. **REGRESSION_VERIFY** — run affected/existing checks to ensure the minimal implementation did not break verified behavior.
9. **MINIMALITY_REVIEW** — reject unnecessary production code, speculative abstractions, unrelated refactors, extra APIs, or behavior not justified by the slice/test.

A sub-task becomes VERIFIED only after RED was demonstrated, GREEN was reached, regression checks passed, and minimality review accepted the diff.

## Phase 3 — Local repository tools

Use **ast-grep as the primary code retrieval engine**. Its structural/AST-aware queries and machine-readable output provide deterministic evidence about code definitions, declarations, calls, imports, tests, and nearby syntax without exposing a shell to the model.

Use **ripgrep only for non-code/textual evidence and fallback**, including Markdown/docs, configuration and data files that ast-grep does not structurally understand, literal error messages, generated text, and cases where a structural query is unavailable.

Expose semantic read operations to the context engine/model rather than raw CLI access:

```text
list_tree(path, depth)
find_definitions(name)
find_structural(pattern)
find_calls(name)
find_imports(name)
find_tests_for(symbol_or_path)
read_range(path, start, end)
search_text(query, paths?)       # rg fallback/non-code
```

Mutation and execution remain harness-only capabilities: validated patch application, Git diff/status, targeted tests, regression checks, formatting/lint/type/build checks, protected-test enforcement, allowed-path checks, and change-budget checks.

Guardrails include repository-root sandboxing, path traversal prevention, patch budgets, sensitive-path deny rules, no arbitrary shell, and protection preventing implementation turns from modifying the accepted test. ast-grep is retrieval-only initially; CodeMill does not use its rewrite capability.

## Phase 4 — Verification pipeline

Separate verification purposes:

- **RED verification:** prove the new behavioral test fails for the intended missing behavior.
- **GREEN verification:** prove the minimal implementation satisfies that focused test.
- **Regression verification:** prove previously verified behavior still passes.
- **Final verification:** prove all slices compose to satisfy the original task.

Normalize failures before returning them to REPAIR.

## Phase 5 — Progressive context engine

Build context **per vertical slice and per TDD stage** rather than constructing one large context pack up front.

Start from a cheap repository map: source/test layout, language/framework clues, package/module boundaries, build/test configuration, and verified prerequisite slices. Derive structural search candidates from the slice objective and acceptance criteria.

Use ast-grep to discover code structure and expand evidence incrementally: candidate definitions/declarations, imports, calls/usages that can be expressed structurally, nearby tests, interfaces/types, and analogous local patterns. Use rg for non-code/textual material and literal fallback searches.

Build a small **test context** containing the slice, acceptance criteria, constraints, closest test conventions/fixtures, public behavioral surface, required input/output types, and relevant verified prerequisites. Avoid exposing unnecessary production internals that could cause the generated test to encode an implementation rather than behavior.

After CONFIRM_RED, treat failure evidence as a new retrieval signal. Stack frames, file/line locations, exceptions, compiler/type diagnostics, and assertion output should receive the highest retrieval priority. Use them to construct a separate **implementation context** containing the accepted immutable failing test, RED diagnostics, implicated production symbols/ranges, required interfaces/types, nearby error-handling or implementation conventions, constraints, and change budget.

Every context fragment records path/range, symbols when applicable, kind, why it was selected, retrieval source, and score. Deduplicate overlapping ranges and enforce a strict token budget. The objective is **minimum sufficient evidence**, not filling the model's available context window.

Context must not grow monotonically across sub-tasks. Treat every model invocation as a fresh call whose working context is reconstructed from the current repository plus explicit persistent run state. No correctness behavior may depend on llama.cpp conversation history.

After a sub-task verifies, run **COMPACT**. Persist a concise verified-slice record (behavior, accepted test, changed files/symbols, verification result), durable decisions/constraints, and only reusable evidence-backed learnings from failed attempts. Discard transient prompts, previous packed contexts, superseded diagnostics, and failed patch bodies.

Learnings are retrieved on demand rather than injected globally. Each learning carries kind, statement, file/symbol/concept scope, evidence/provenance, originating sub-task/repository revision, confidence, and supersession state. Current repository evidence outranks stored learnings; newer verified facts can supersede older entries.

## Phase 6 — llama.cpp model adapter

This phase is required for v0, not a post-v0 enhancement. Use a locally managed llama.cpp `llama-server` as the first inference backend. The initial endpoint is hard-coded to `http://127.0.0.1:9090`; the user starts and owns the server and model selection/loading.

Use llama-server's OpenAI-compatible HTTP API. Define and test request/response parsing, operation-specific prompts, structured-output validation, timeouts, bounded retries, and clear handling for unavailable servers, malformed output, and model refusal/failure. Never treat malformed model output as authorization to skip a harness invariant.

Keep operations specialised: **DECOMPOSE, LOCATE, WRITE_TEST, IMPLEMENT, REPAIR, REVIEW**. Prefer schema-constrained output and evaluate each operation independently. Every call receives the current task/sub-task, relevant repository evidence, constraints, and explicit run state it needs; correctness must not depend on retained conversation history.

The implementation instruction is intentionally narrow: make the accepted failing test pass with the smallest production-code change; do not modify the test; do not implement behavior not required by the slice.

## Phase 7 — Change budgets and escalation

Apply budgets per slice and across the task. A vertical slice may legitimately touch multiple layers; budgets must not force horizontal decomposition.

Reject or escalate when the implementation changes the protected test, exceeds scope, introduces unjustified dependencies/APIs/schema changes, cannot demonstrate RED, repeatedly fails GREEN, or requires unsupported capabilities.

## Phase 8 — Evaluation

Build tasks from historical commits and evaluate the full decomposition-to-TDD workflow. The dataset loader accepts JSONL cases pinned to a full repository commit SHA, validates task acceptance criteria, rejects duplicate IDs/path escapes, and refuses dirty or mismatched repository checkouts. `BenchmarkRunner` rechecks the base, creates a detached disposable Git worktree, verifies the harness targets that worktree, records run metrics, and removes the worktree after each case. Curated historical cases and broader token/latency/cost/retrieval metrics remain outstanding.

Track task success plus: slice count/depth, RED validity, tests that unexpectedly pass, GREEN attempts, test-mutation attempts, implementation LOC/files, unnecessary-code findings, regression failures, tokens/tool calls, latency/GPU time, escalation, and human intervention. The initial metrics module derives run/sub-task outcomes, valid/rejected RED, repair counts, scope violations, verified changed files, inference duration, and server-reported prompt/completion/total tokens. Curated historical cases, test-mutation attempts, GPU time, and monetary cost remain outstanding.

Compare small-model+harness runs with stronger-model baselines under equivalent verification.

## Phase 9 — Learning from traces

Analyze decomposition, test-generation, implementation, and repair failures separately before considering trajectory distillation, SFT/LoRA, or verifier-driven optimization.

Fine-tuning is an optimization step, not the starting architecture.

## Near-term backlog

1. Define the user invocation, repository cleanliness/worktree policy, result statuses, and artifact bundle.
2. Formal SubTask/decomposition schema, graph validator, deterministic scheduler, and invalid-plan escalation.
3. TDD state model and verifier contracts for expected RED, focused GREEN, regression, and final verification.
4. Protected-test patch policy, validated diff application, allowed-path and change-budget enforcement.
5. Harness-controlled repository tools and an explicit v0 sandbox/subprocess security boundary.
6. Structured event trace and artifact writer keyed by task and sub-task; minimum context construction for each model operation.
7. llama.cpp adapter at `http://127.0.0.1:9090`, including real request/response handling and failure behavior.
8. Minimal progressive retrieval (ast-grep for source structure, rg textual fallback); advanced provenance ranking and scoped learning may follow.
9. Fixture-repository end-to-end test with a real llama.cpp server/model, plus deterministic fake-model unit tests.
10. Run the complete task workflow and inspect the resulting bundle, diff, and verification evidence.

Persistent resume, a durable scoped learning store, sophisticated semantic decomposition scoring, and benchmark/evaluation infrastructure are valuable follow-ups, but should not block the first v0 unless needed for safe, reproducible runs.
