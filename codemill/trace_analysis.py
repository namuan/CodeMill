from dataclasses import dataclass

from .models import RunResult, RunStatus


@dataclass(frozen=True)
class TraceDiagnosis:
    stage: str
    category: str
    event: str | None
    diagnostics: tuple[str, ...]


def analyze_trace(result: RunResult) -> TraceDiagnosis:
    events = result.events
    names = tuple(event.name for event in events)
    diagnostics = tuple(
        dict.fromkeys(
            (*result.diagnostics, *(diagnostic for event in events for diagnostic in event.diagnostics))
        )
    )
    if result.status is RunStatus.VERIFIED:
        return TraceDiagnosis("complete", "verified", "run_verified", diagnostics)

    stage = _failure_stage(names)
    category = _failure_category(names, diagnostics, result.status)
    preferred_events = {
        "protected_test_mutation": "protected_test_mutation_attempt",
        "model_timeout": "subtask_failed",
        "invalid_test_collection": "red_rejected",
        "invalid_red": "red_rejected",
        "decomposition_review_rejected": "decomposition_review_rejected",
        "scope_violation": "scope_violation",
    }
    preferred_event = preferred_events.get(category)
    event = next(
        (item.name for item in reversed(events) if item.name == preferred_event),
        None,
    )
    if event is None:
        event = next(
            (
                item.name
                for item in reversed(events)
                if item.name.endswith(("failed", "rejected", "escalated", "violation", "attempt"))
                and item.name not in {"run_failed", "run_escalated"}
            ),
            None,
        )
    return TraceDiagnosis(stage, category, event, diagnostics)


def _failure_stage(names: tuple[str, ...]) -> str:
    if "plan_validated" not in names:
        return "decomposition"
    test_write = _last_index(names, "test_write_started")
    test_applied = _last_index(names, "test_patch_applied")
    red_confirmed = _last_index(names, "red_confirmed")
    red_rejected = _last_index(names, "red_rejected")
    if test_write > test_applied:
        return "test_generation"
    if red_rejected > red_confirmed:
        return "red_verification"
    if test_applied > red_confirmed:
        return "red_verification"
    implementation = _last_index(names, "implementation_started")
    if implementation >= 0:
        implementation_patch = _last_index(names, "patch_applied")
        if implementation_patch < implementation:
            return "implementation"
        green_started = _last_index(names, "green_verify_started")
        green_passed = _last_index(names, "green_verify_passed")
        if green_started > green_passed:
            return "green_verification"
        repair_started = _last_index(names, "repair_started")
        if repair_started > green_passed:
            return "repair"
        regression_started = _last_index(names, "regression_verify_started")
        regression_passed = _last_index(names, "regression_verify_passed")
        if regression_started > regression_passed:
            return "regression_verification"
        if regression_passed >= 0 and _last_index(names, "minimality_review_accepted") < regression_passed:
            return "minimality_review"
    if "subtask_verified" in names and _last_index(names, "final_verify_passed") < 0:
        return "final_verification"
    if _last_index(names, "decomposition_review_rejected") > _last_index(names, "plan_validated"):
        return "decomposition_review"
    return "run"


def _failure_category(
    names: tuple[str, ...], diagnostics: tuple[str, ...], status: RunStatus
) -> str:
    text = "\n".join(diagnostics).lower()
    if any("test patch may not modify a pre-existing" in item.lower() for item in diagnostics):
        return "protected_test_mutation"
    if "timed out" in text or "timeout" in text:
        return "model_timeout"
    if "scope_violation" in names or any("scope" in item.lower() for item in diagnostics):
        return "scope_violation"
    if "pytest exited with status 2" in text:
        return "invalid_test_collection"
    if "red_rejected" in names:
        return "invalid_red"
    if "decomposition_review_rejected" in names:
        return "decomposition_review_rejected"
    if "LlamaServerError" in "\n".join(diagnostics):
        return "model_request_failure"
    if status is RunStatus.ESCALATED:
        return "harness_escalation"
    return "run_failure"


def _last_index(names: tuple[str, ...], name: str) -> int:
    return len(names) - 1 - names[::-1].index(name) if name in names else -1
