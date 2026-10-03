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

## Phase 0 — Decomposition-aware bootstrap

Define task, sub-task, dependency, result, model, tool, and verifier contracts. Implement decomposition, dependency-ordered execution, bounded repair, and final whole-task verification.

**Exit:** fake-model tests demonstrate decomposition, dependency ordering, repair, and final verification.

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

## Phase 6 — llama.cpp model adapter

Use a locally managed llama.cpp `llama-server` as the first inference backend. For the initial implementation, CodeMill hard-codes the server base URL to `http://127.0.0.1:9090`. The user starts and owns the llama-server process, including model selection/loading; CodeMill does not require or manage a model filesystem path.

Use llama-server's OpenAI-compatible HTTP API for inference.

Keep operations specialised: **DECOMPOSE, LOCATE, WRITE_TEST, IMPLEMENT, REPAIR, REVIEW**. Prefer schema-constrained output and evaluate each operation independently.

The implementation instruction is intentionally narrow: make the accepted failing test pass with the smallest production-code change; do not modify the test; do not implement behavior not required by the slice.

## Phase 7 — Change budgets and escalation

Apply budgets per slice and across the task. A vertical slice may legitimately touch multiple layers; budgets must not force horizontal decomposition.

Reject or escalate when the implementation changes the protected test, exceeds scope, introduces unjustified dependencies/APIs/schema changes, cannot demonstrate RED, repeatedly fails GREEN, or requires unsupported capabilities.

## Phase 8 — Evaluation

Build tasks from historical commits and evaluate the full decomposition-to-TDD workflow.

Track task success plus: slice count/depth, RED validity, tests that unexpectedly pass, GREEN attempts, test-mutation attempts, implementation LOC/files, unnecessary-code findings, regression failures, tokens/tool calls, latency/GPU time, escalation, and human intervention.

Compare small-model+harness runs with stronger-model baselines under equivalent verification.

## Phase 9 — Learning from traces

Analyze decomposition, test-generation, implementation, and repair failures separately before considering trajectory distillation, SFT/LoRA, or verifier-driven optimization.

Fine-tuning is an optimization step, not the starting architecture.

## Near-term backlog

1. Formal SubTask/decomposition JSON schema and graph validator.
2. Vertical-slice quality validator/rules.
3. TDD state model: WRITE_TEST, RED, IMPLEMENT, GREEN, REGRESSION, MINIMALITY_REVIEW.
4. Protected-test patch policy.
5. Structured event/trace format keyed by task and sub-task.
6. Filesystem sandbox + ast-grep structural retrieval adapter + rg textual fallback.
7. Unified-diff parser + per-slice/whole-task change budgets.
8. Allowlisted targeted/regression verifier.
9. llama.cpp adapter hard-coded to `http://127.0.0.1:9090`.
10. Fixture repository + first decomposition-to-TDD benchmark.
