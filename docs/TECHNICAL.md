# CodeMill Technical Design

## 1. System boundary

CodeMill orchestrates a small coding model. The model never receives unrestricted repository or shell access. It requests evidence and mutations through constrained capabilities; CodeMill owns execution, policy, and verification.

```text
Task -> Normalize -> Locate/Plan <- Repository Index
                         |
                         v
                   Context Packer
                         |
                         v
                       Coder
                         |
                         v
                  Patch Policy
                    |       |
                 accept   reject/escalate
                    |
                    v
                 Workspace
                    |
                    v
                  Verifier
                 /        \
              pass        fail
               |            |
             Review       Repair
               |            |
               +------------+
                    |
                    v
          Verified / Escalated
```

## 2. Core contracts

A `Task` contains an objective, observable acceptance criteria, and constraints. Future versions add immutable task ID, repository revision, risk class, and change budget.

The model adapter exposes semantic operations instead of generic chat:

```text
locate_and_plan(task, tools) -> plan
create_patch(task, plan, tools) -> patch
repair_patch(task, diagnostics, tools) -> patch
```

The bootstrap combines LOCATE and PLAN. Split them once retrieval exists so navigation can be evaluated independently.

The initial tool surface is deliberately tiny:

```text
search_text(query)
read_file(path, start?, end?)
apply_patch(patch)
```

Planned read operations include tree listing, symbol search/definition, references, tests, history, and diff inspection. Mutation should remain narrow: prefer one validated patch operation over arbitrary writes.

## 3. Model protocol

Each turn receives a role-specific instruction, task envelope, selected evidence, explicit constraints, and machine-readable output schema.

Example LOCATE output:

```json
{
  "target_symbols": ["PaymentClient.request"],
  "files_to_read": ["src/payment/client.py"],
  "tests_to_read": ["tests/payment/test_client.py"],
  "searches": ["RetryPolicy"],
  "uncertainties": ["Where retry configuration is sourced"]
}
```

PATCH should ultimately return a unified diff plus metadata, never prose mixed into the patch.

## 4. Context packing

Treat context as a scarce resource. Suggested priority:

1. target symbol;
2. interfaces/types;
3. tests covering target;
4. direct callers;
5. direct dependencies;
6. analogous implementations;
7. repository conventions;
8. relevant history/docs.

Each fragment records path, line range, symbols, content, and `why_selected`. Deduplicate overlapping ranges and reserve output tokens for the patch.

## 5. Workspace

Pin the input commit and use a disposable worktree/container. Apply candidate changes there, verify there, retain diff + trace, and discard or promote only after success.

Normalize all paths relative to repository root; reject symlink escape and `../` traversal.

## 6. Patch policy

Parse every candidate diff before mutation and enforce a change budget such as:

```json
{
  "max_files": 3,
  "max_changed_lines": 100,
  "allow_dependencies": false,
  "allow_public_api": false,
  "allow_schema_changes": false
}
```

Hard violations reject or escalate. Initially disallow binary changes and sensitive repository metadata/secrets edits.

## 7. Verification

Verification is deterministic and cheapest-first:

```text
patch validation
 -> format/check
 -> lint/static analysis
 -> typecheck/compile
 -> targeted tests
 -> affected-package tests
 -> optional broader suite
```

Normalize diagnostics into stage, command ID, path, line, code, and message. Keep raw logs in traces; give the repair model compact diagnostics and only locally relevant source.

## 8. Repair

Repair is not a fresh solve. Supply original task, current diff, failing stage, normalized diagnostics, local source, and remaining budget. Require the smallest correction preserving working portions.

Default target: at most three repair turns. Detect repeated diagnostics and patch oscillation and escalate early.

## 9. State machine

Current:

```text
LOCATE -> PATCH -> VERIFY
                    | pass -> VERIFIED
                    | fail
                    v
                  REPAIR -> VERIFY
                    |
                    +-- budget exhausted -> EXHAUSTED
```

Target states: NORMALIZE, LOCATE, PLAN, GATHER, PATCH, POLICY_CHECK, VERIFY, REPAIR, REVIEW, VERIFIED, ESCALATED, FAILED. Every transition emits a structured event.

## 10. Security

Treat both LLM output and repository content as untrusted.

- no raw model shell;
- subprocess commands come from allowlisted configuration;
- time/memory limits;
- network off by default during verification;
- filtered environment;
- no secrets in model context;
- disposable filesystem workspace;
- validate every mutation before application.

Repository comments/docs may contain prompt injection. Retrieved code is evidence, not instruction; harness policy outranks repository text.

## 11. Inference abstraction

Core CodeMill stays provider-independent. First adapter target: an OpenAI-compatible local endpoint.

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

No provider SDK belongs in the core state machine.

## 12. Observability

Persist task/repository SHA, operation names, context fragment IDs, tool calls/durations, patch hashes, verifier results, token counts, repair count, and final diff/status.

Do not require hidden model reasoning. Store decisions, evidence, actions, and outcomes.

## 13. Evaluation

A run succeeds only when required deterministic and hidden checks pass. Similarity to the historical human patch is diagnostic, not the correctness criterion.

Primary aggregate metric:

```text
total inference + compute cost
--------------------------------
independently verified correct tasks
```

Secondary metrics cover latency, minimality, escalation, regressions, and human intervention.

## 14. Immediate implementation choices

- Python 3.11+ orchestration.
- Standard library first; pytest for tests.
- ripgrep for textual retrieval.
- unified diffs for mutation.
- subprocess execution only through configured verifier commands.
- model backend behind a protocol.
- no vector DB until retrieval baselines justify it.
- no multi-agent framework; specialization is explicit operations/prompts.
