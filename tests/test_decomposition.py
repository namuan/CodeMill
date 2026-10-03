import json

import pytest

from codemill.decomposition import DECOMPOSITION_JSON_SCHEMA, parse_decomposition
from codemill.models import ExpectedScope


def valid_payload():
    return {
        "subtasks": [
            {
                "id": "ST-001",
                "objective": "Return the configured greeting",
                "acceptance_criteria": ["the greeting endpoint returns the configured text"],
                "constraints": ["do not add runtime dependencies"],
                "depends_on": [],
                "expected_scope": {
                    "max_files": 2,
                    "max_changed_lines": 40,
                    "allow_dependencies": False,
                    "allow_public_api": False,
                    "allow_schema_changes": False,
                },
            }
        ]
    }


def test_parses_structured_decomposition_and_scope():
    subtasks = parse_decomposition(json.dumps(valid_payload()))

    assert len(subtasks) == 1
    assert subtasks[0].id == "ST-001"
    assert subtasks[0].acceptance_criteria == (
        "the greeting endpoint returns the configured text",
    )
    assert subtasks[0].expected_scope == ExpectedScope(2, 40, False, False, False)


def test_schema_requires_all_contract_fields():
    required = DECOMPOSITION_JSON_SCHEMA["properties"]["subtasks"]["items"]["required"]

    assert required == [
        "id",
        "objective",
        "acceptance_criteria",
        "constraints",
        "depends_on",
        "expected_scope",
    ]


def test_rejects_missing_acceptance_criteria():
    payload = valid_payload()
    del payload["subtasks"][0]["acceptance_criteria"]

    with pytest.raises(ValueError, match="missing required field: acceptance_criteria"):
        parse_decomposition(json.dumps(payload))


def test_rejects_empty_acceptance_criteria():
    payload = valid_payload()
    payload["subtasks"][0]["acceptance_criteria"] = []

    with pytest.raises(ValueError, match="acceptance_criteria must not be empty"):
        parse_decomposition(json.dumps(payload))


def test_rejects_unknown_subtask_fields():
    payload = valid_payload()
    payload["subtasks"][0]["implementation_notes"] = "add a helper"

    with pytest.raises(ValueError, match="unknown field: implementation_notes"):
        parse_decomposition(json.dumps(payload))


def test_rejects_invalid_scope_values():
    payload = valid_payload()
    payload["subtasks"][0]["expected_scope"]["max_files"] = 0

    with pytest.raises(ValueError, match="max_files must be a positive integer"):
        parse_decomposition(json.dumps(payload))


def test_rejects_malformed_json():
    with pytest.raises(ValueError, match="invalid decomposition JSON"):
        parse_decomposition("not json")
