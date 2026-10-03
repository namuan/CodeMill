# CodeMill Delivery Plan

## Goal

Build a specialised coding harness that makes small language models useful for real repository-level software development.

CodeMill begins every developer task by decomposing it into **minimal, dependency-aware, independently verifiable vertical slices**. Each sub-task then runs through the same bounded coding cycle:

```text
LOCATE -> PLAN -> PATCH -> VERIFY -> REVIEW
                         ^       |
                         + REPAIR+
```

Only verified sub-tasks unlock their dependents. After every sub-task completes, CodeMill runs final verification against the original task and acceptance criteria.

The primary success metric is **cost per independently verified correct task**, with sub-task success and repair behavior recorded as diagnostic metrics.

## Phase 0 — Decomposition-aware bootstrap

Define task, sub-task, dependency, result, model, tool, and verifier contracts.

Implement:

- `DECOMPOSE` as the first model operation;
- dependency-ordered sub-task execution;
- per-sub-task `LOCATE -> PLAN -> PATCH -> VERIFY -> REPAIR -> REVIEW`;
- bounded repair attempts per sub-task;
- final whole-task verification;
- escalation for invalid/unmet dependency plans.

**Exit:** fake model tests demonstrate decomposition, dependency ordering, per-sub-task repair, and final verification.

## Phase 1 — Structured decomposition protocol

Replace free-form decomposition with schema-constrained output. A sub-task must contain:

- stable ID;
- objective;
- observable acceptance criteria;
- constraints;
- dependency IDs;
- expected scope/change budget.

Validate the graph before execution: unique IDs, existing dependencies, no cycles, and deterministic topological order.

Add decomposition quality rules built around the **vertical-slice invariant**: each sub-task delivers one observable behavior through all technical layers needed to verify it. Tests belong to the slice rather than becoming a separate horizontal task. Split a slice further only when every resulting slice remains independently and meaningfully verifiable. Reject layer-oriented plans such as “add database field”, “add service”, “add endpoint”, and “add tests” when those pieces only become meaningful together.\n\nThe decomposition test is: **Can this slice be made smaller while every resulting piece still has its own observable verification condition?** If yes, split it. If no, keep it as the minimal vertical slice.

## Phase 2 — Local repository tools

Implement safe deterministic tools: ripgrep search, ranged reads, tree/symbol discovery, references/tests, validated unified-diff application, and Git diff/status inspection.

Guardrails include repository-root sandboxing, path traversal prevention, patch budgets, sensitive-path deny rules, and no arbitrary shell exposed to the model.

## Phase 3 — Verification pipeline

For every sub-task run cheapest checks first: patch validity, formatter, linter/static checks, compiler/type checker, targeted behavioral tests, affected tests, and diff policy review. Verification must prove the slice's observable behavior, not merely that its implementation layers compile.

Final task verification then runs the checks needed to prove the combined changes satisfy the original acceptance criteria.

Normalize failures before returning them to REPAIR.

## Phase 4 — Context engine

Index files, symbols, definitions, imports, references, tests, repository conventions, and selected Git history. Start without embeddings.

Build context **per sub-task**, not per original task. Rank target definitions, interfaces, tests, direct dependencies, and changes produced by prerequisite sub-tasks. Every fragment records provenance and `why_selected`.

## Phase 5 — 9B model adapter

Add an OpenAI-compatible local inference adapter for local serving stacks.

Keep model operations specialised: **DECOMPOSE, LOCATE, PLAN, PATCH, REPAIR, REVIEW**. Prefer schema-constrained output. Evaluate each operation independently so model weaknesses can be attributed to decomposition, navigation, generation, or repair.

## Phase 6 — Change budgets and escalation

Apply budgets per sub-task and across the whole task: files/LOC, dependencies, public APIs, schemas, generated files, and sensitive paths. A vertical slice may legitimately touch multiple layers/files; budgets must not force horizontal decomposition.

Escalate when decomposition is invalid, policy is exceeded, context remains ambiguous, repairs oscillate, verification is unavailable, or the task requires unsupported capabilities.

## Phase 7 — Evaluation

Build tasks from historical commits: checkout N-1, provide original issue/PR intent without commit N, let CodeMill decompose and execute, then run public and hidden verification.

Track task success plus decomposition metrics: number of sub-tasks, dependency depth, failed/replanned sub-tasks, verification isolation, unnecessary edits, tokens/tool calls per sub-task, repairs, wall/GPU time, escalation, and human intervention.

Compare small-model+harness runs with stronger-model baselines under equivalent verification.

## Phase 8 — Learning from traces

Once evaluation data exists, analyze decomposition, navigation, generation, and repair failure modes separately. Then consider trajectory distillation, SFT/LoRA, or verifier-driven optimization.

Fine-tuning is an optimization step, not the starting architecture.

## Near-term backlog

1. Formal `SubTask`/decomposition JSON schema and graph validator.\n2. Vertical-slice quality validator/rules.
2. Structured event/trace format keyed by task and sub-task.
3. Filesystem sandbox + ripgrep adapter.
4. Unified-diff parser + per-sub-task/whole-task change budgets.
5. Allowlisted subprocess verifier with targeted and final modes.
6. OpenAI-compatible local model adapter.
7. Fixture repository + first decomposition-to-verification benchmark.
