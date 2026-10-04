import json
import re
from typing import Any

from .models import DecompositionReview, ExpectedScope, SubTask, VerificationTarget


DECOMPOSITION_REVIEW_JSON_SCHEMA = {
    "type": "object",
    "required": ["accepted", "findings", "already_satisfied", "evidence", "test_target"],
    "additionalProperties": False,
    "properties": {
        "accepted": {"type": "boolean"},
        "findings": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        },
        "already_satisfied": {"type": "boolean"},
        "evidence": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        },
        "test_target": {
            "type": "object",
            "required": ["paths", "selectors"],
            "additionalProperties": False,
            "properties": {
                "paths": {"type": "array", "items": {"type": "string", "minLength": 1}},
                "selectors": {"type": "array", "items": {"type": "string", "minLength": 1}},
            },
        },
    },
}


DECOMPOSITION_JSON_SCHEMA = {
    "type": "object",
    "required": ["subtasks"],
    "additionalProperties": False,
    "properties": {
        "subtasks": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "id",
                    "objective",
                    "acceptance_criteria",
                    "constraints",
                    "depends_on",
                    "expected_scope",
                ],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "objective": {"type": "string", "minLength": 1},
                    "acceptance_criteria": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "constraints": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                    },
                    "depends_on": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                    },
                    "expected_scope": {
                        "type": "object",
                        "required": [
                            "max_files",
                            "max_changed_lines",
                            "allow_dependencies",
                            "allow_public_api",
                            "allow_schema_changes",
                            "planned_paths",
                        ],
                        "additionalProperties": False,
                        "properties": {
                            "max_files": {"type": "integer", "minimum": 1},
                            "max_changed_lines": {"type": "integer", "minimum": 0},
                            "allow_dependencies": {"type": "boolean"},
                            "allow_public_api": {"type": "boolean"},
                            "allow_schema_changes": {"type": "boolean"},
                            "planned_paths": {
                                "type": "array",
                                "items": {"type": "string", "minLength": 1},
                            },
                        },
                    },
                },
            },
        }
    },
}


def parse_decomposition(payload: str) -> tuple[SubTask, ...]:
    if not isinstance(payload, str):
        raise ValueError("decomposition response must be JSON text")
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid decomposition JSON: {error.msg}") from error

    root = _require_object(document, "decomposition")
    _reject_unknown_fields(root, {"subtasks"}, "decomposition")
    subtasks_value = _require_field(root, "subtasks", "decomposition")
    if not isinstance(subtasks_value, list):
        raise ValueError("subtasks must be an array")

    return tuple(
        _parse_subtask(value, f"subtasks[{index}]")
        for index, value in enumerate(subtasks_value)
    )


def parse_decomposition_review(payload: str) -> DecompositionReview:
    if not isinstance(payload, str):
        raise ValueError("decomposition review response must be JSON text")
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid decomposition review JSON: {error.msg}") from error

    review = _require_object(document, "decomposition review")
    _reject_unknown_fields(
        review,
        {"accepted", "findings", "already_satisfied", "evidence", "test_target"},
        "decomposition review",
    )
    accepted = _require_boolean(
        _require_field(review, "accepted", "decomposition review"),
        "decomposition review.accepted",
    )
    findings = _require_string_array(
        _require_field(review, "findings", "decomposition review"),
        "decomposition review.findings",
    )
    if not accepted and not findings:
        raise ValueError("rejected review must include findings")
    already_satisfied = _require_boolean(
        review.get("already_satisfied", False), "decomposition review.already_satisfied"
    )
    evidence = _require_string_array(
        review.get("evidence", []), "decomposition review.evidence"
    )
    target_value = review.get("test_target")
    target = _parse_verification_target(target_value) if target_value is not None else None
    if already_satisfied and (not accepted or not evidence or target is None or not target.paths):
        raise ValueError("already-satisfied review requires acceptance, evidence, and test paths")
    return DecompositionReview(accepted, findings, already_satisfied, evidence, target)


def _parse_verification_target(value: Any) -> VerificationTarget:
    target = _require_object(value, "decomposition review.test_target")
    _reject_unknown_fields(target, {"paths", "selectors"}, "decomposition review.test_target")
    paths = _require_string_array(
        _require_field(target, "paths", "decomposition review.test_target"),
        "decomposition review.test_target.paths",
    )
    selectors = _require_string_array(
        _require_field(target, "selectors", "decomposition review.test_target"),
        "decomposition review.test_target.selectors",
    )
    return VerificationTarget(paths, selectors)


def _parse_subtask(value: Any, path: str) -> SubTask:
    item = _require_object(value, path)
    expected_fields = {
        "id",
        "objective",
        "acceptance_criteria",
        "constraints",
        "depends_on",
        "expected_scope",
    }
    _reject_unknown_fields(item, expected_fields, path)

    identifier = _require_nonempty_string(_require_field(item, "id", path), f"{path}.id")
    objective = _require_nonempty_string(
        _require_field(item, "objective", path), f"{path}.objective"
    )
    acceptance_criteria = _require_string_array(
        _require_field(item, "acceptance_criteria", path),
        f"{path}.acceptance_criteria",
        nonempty=True,
    )
    constraints = _require_string_array(
        _require_field(item, "constraints", path), f"{path}.constraints"
    )
    depends_on = _require_string_array(
        _require_field(item, "depends_on", path), f"{path}.depends_on"
    )
    scope = _parse_scope(_require_field(item, "expected_scope", path), f"{path}.expected_scope")

    return SubTask(identifier, objective, acceptance_criteria, constraints, depends_on, scope)


def _parse_scope(value: Any, path: str) -> ExpectedScope:
    scope = _require_object(value, path)
    fields = {
        "max_files",
        "max_changed_lines",
        "allow_dependencies",
        "allow_public_api",
        "allow_schema_changes",
        "planned_paths",
    }
    _reject_unknown_fields(scope, fields, path)

    max_files = _require_integer(_require_field(scope, "max_files", path), f"{path}.max_files")
    if max_files < 1:
        raise ValueError("max_files must be a positive integer")

    max_changed_lines = _require_integer(
        _require_field(scope, "max_changed_lines", path), f"{path}.max_changed_lines"
    )
    if max_changed_lines < 0:
        raise ValueError("max_changed_lines must be a non-negative integer")

    allow_dependencies = _require_boolean(
        _require_field(scope, "allow_dependencies", path), f"{path}.allow_dependencies"
    )
    allow_public_api = _require_boolean(
        _require_field(scope, "allow_public_api", path), f"{path}.allow_public_api"
    )
    allow_schema_changes = _require_boolean(
        _require_field(scope, "allow_schema_changes", path), f"{path}.allow_schema_changes"
    )
    planned_paths = _require_string_array(
        _require_field(scope, "planned_paths", path), f"{path}.planned_paths"
    )
    for pattern in planned_paths:
        if (
            pattern.startswith("/")
            or "\\" in pattern
            or ".." in pattern.split("/")
            or not re.fullmatch(r"[A-Za-z0-9._/*?-]+", pattern)
        ):
            raise ValueError(f"{path}.planned_paths contains an invalid repository path pattern")

    return ExpectedScope(
        max_files,
        max_changed_lines,
        allow_dependencies,
        allow_public_api,
        allow_schema_changes,
        planned_paths,
    )


def _require_object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    return value


def _require_field(value: dict[str, Any], name: str, path: str) -> Any:
    if name not in value:
        raise ValueError(f"{path} missing required field: {name}")
    return value[name]


def _reject_unknown_fields(value: dict[str, Any], allowed: set[str], path: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{path} has unknown field: {unknown[0]}")


def _require_nonempty_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string")
    return value.strip()


def _require_string_array(value: Any, path: str, nonempty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{path} must be an array of strings")
    if nonempty and not value:
        raise ValueError(f"{path} must not be empty")
    return tuple(
        _require_nonempty_string(item, f"{path}[{index}]")
        for index, item in enumerate(value)
    )


def _require_integer(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{path} must be an integer")
    return value


def _require_boolean(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{path} must be a boolean")
    return value
