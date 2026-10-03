# CodeMill Delivery Plan

## Goal

Build a specialised coding harness that makes small language models useful for real repository-level software development by reducing each model decision to a bounded, context-rich, verifiable operation.

The primary success metric is **cost per independently verified correct patch**.

## Phase 0 — Bootstrap

Define task/result types, narrow model/tool/verifier interfaces, and the bounded `LOCATE -> PATCH -> VERIFY -> REPAIR` loop.

**Exit:** a fake model produces a patch, receives deterministic failure feedback, repairs it, and finishes verified.

## Phase 1 — Local repository tools

Implement safe deterministic tools:

- `search_text` using ripgrep;
- ranged `read_file`;
- symbol discovery using tree-sitter or LSP;
- references and test discovery;
- validated unified-diff application;
- Git diff/status inspection.

Guardrails: repository-root sandbox, path traversal prevention, patch size/file budgets, sensitive-path deny rules, and no arbitrary shell exposed to the model.

## Phase 2 — Verification pipeline

Run cheapest checks first:

1. patch validity;
2. formatter;
3. linter/static checks;
4. type checker/compiler;
5. targeted tests;
6. broader affected tests;
7. diff policy review.

Normalize failures before returning them to the model.

## Phase 3 — Context engine

Index files, symbols, definitions, imports, references, tests, repository conventions, and selected Git history. Start without embeddings.

Use a token-budgeted context packer. Rank target definitions, interfaces, and tests above broad repository material. Every fragment records provenance and `why_selected`.

## Phase 4 — 9B model adapter

Add an OpenAI-compatible local inference adapter so vLLM/llama.cpp-style servers can be tested without coupling orchestration to a provider.

Keep model operations specialised: **LOCATE, PLAN, PATCH, REPAIR, REVIEW**. Prefer schema-constrained output.

## Phase 5 — Change budgets and escalation

Enforce maximum files/LOC and policies for dependencies, public APIs, schemas, generated files, and sensitive paths.

Escalate when policy is exceeded, context remains ambiguous, repairs oscillate, verification is unavailable, or the task requires unsupported capabilities.

## Phase 6 — Evaluation

Build tasks from historical commits: checkout N-1, provide the original issue/PR intent without commit N, run CodeMill, then execute public and hidden verification.

Track verified-task rate, hidden-test pass rate, regressions, unnecessary LOC/files, tool calls, tokens, repairs, wall time, GPU time, escalation rate, and human intervention.

Compare small-model+harness runs with stronger-model baselines under equivalent verification.

## Phase 7 — Learning from traces

Only after evaluation data exists, analyze recurring navigation/generation/repair failures. Then consider trajectory distillation, SFT/LoRA, or verifier-driven optimization.

Fine-tuning is an optimization step, not the starting architecture.

## Near-term backlog

1. Filesystem sandbox + ripgrep adapter.
2. Unified-diff parser + change budgets.
3. Allowlisted subprocess verifier.
4. Structured event/trace format.
5. OpenAI-compatible local model adapter.
6. Fixture repository + first end-to-end benchmark.
