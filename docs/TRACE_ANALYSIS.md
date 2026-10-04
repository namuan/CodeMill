# Initial Trace Analysis

## Scope

This is an exploratory analysis of three historical benchmark tasks run with `Tesslate-OmniCoder-9B-Q8_0`, plus the passing opt-in real-model acceptance run. It is not a model comparison and is not enough evidence to support fine-tuning or trajectory distillation.

## Observations by stage

### Decomposition and review

The latest attempts for all three historical cases passed decomposition review and plan validation. That is a positive signal for these specific tasks, not evidence of general decomposition quality: each run had only one subtask, and the sample is small. An earlier RED-cleanup attempt was rejected because review context contained repository maps but omitted the relevant source. Task-level source evidence was subsequently added to decomposition reviews.

### Test generation and RED

Test generation is the observed bottleneck.

- `git-status-001`: the initial test patch targeted the existing `tests/test_repository_tools.py`; the bounded revision targeted it again. Both were rejected before mutation.
- `discard-invalid-red-test-001`: the initial patch and bounded revision targeted existing `tests/test_harness.py`. Both were rejected before mutation.
- `context-overlap-dedup-001`: an earlier attempt generated a test importing nonexistent `merge_fragments`; pytest collection failed, so the harness discarded the test and escalated. After clarifying the private helper target, a later test-generation request timed out at 300 seconds.

The protected-test policy worked as intended: the original patch-based runs left existing tests unchanged and produced no final diff. The two protected-file cases each recorded two rejected test-patch attempts. Test generation now returns module source instead of a model-selected diff path; the harness creates a fresh test file, adds explicit guards for requested missing methods, and can revise a rejected RED once. In the latest Git-status attempt (`/tmp/codemill/omnicoder-git-status-001q.json`), the model produced a new test file and CodeMill confirmed RED without touching existing tests. The generated test still asserted an unsupported dict result, so test correctness remains a failure mode even when path protection and RED succeed.

### Implementation and repair

The earlier historical attempts did not reach implementation. The latest Git-status attempt did reach implementation after valid RED, but the model's production diff repeatedly failed `git apply` context checks despite three bounded revisions; no production change was applied. A recent live greeting attempt reached implementation but was escalated for a public-API scope violation. The earlier passing greeting acceptance run still provides one complete positive trace. The historical runs therefore provide little evidence about successful implementation or repair quality.

### Runtime and evidence quality

The context-dedup test-generation call timed out after 300 seconds. The report records the timeout and duration, but token totals are unavailable for the failed call. This is an inference/runtime failure, not a demonstrated reasoning failure. Reports capture event traces, task/revision metadata, final status, and diff; the current sample does not justify learning generalized rules from model trajectories. Benchmark reports now include a deterministic stage/category diagnosis derived from events and diagnostics, without inferring behavior for stages the run never reached.

## Conclusions

1. Keep protected-test enforcement unchanged. Model-generated test modules now use harness-selected new paths, and rejected tests are discarded before implementation.
2. Continue targeting test quality: the current model may invent result shapes or imports not supported by the subtask. Only exact task-named missing APIs may count as expected missing-method RED.
3. A valid RED now exposes later model weaknesses: production patches can fail exact Git hunk application, and the current bounded revisions have not corrected that case.
4. Do not start SFT, LoRA, trajectory distillation, or verifier-driven optimization from this sample. Gather more varied traces, including successful historical tasks and failures at later stages.
5. Stronger-model comparison, GPU-time accounting, and monetary-cost accounting are optional and are not prerequisites for Phase 9.

## Evidence

- Historical benchmark reports: `/tmp/codemill/omnicoder-git-status-001b.json`, `/tmp/codemill/omnicoder-discard-red-001d.json`, and `/tmp/codemill/omnicoder-context-overlap-001c.json`.
- An earlier context-dedup RED rejection is in `/tmp/codemill/omnicoder-context-overlap-001b.json`.
- Passing real-model acceptance artifact run `77d7ddd080a440e6b0548d53e8df9710` is under `/private/tmp/pytest-of-nnn/pytest-155/test_real_model_completes_tdd_0/artifacts/`.
