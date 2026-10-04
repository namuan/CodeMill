import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from codemill.llama_cpp import LlamaCppModelDriver, LlamaServerError
from codemill.models import SubTask, Task, VerificationTarget
from codemill.repository_tools import LocalRepositoryTools


class ResponseServer:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                owner.requests.append(
                    (self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                )
                status, body = owner.responses.pop(0)
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(body).encode())

            def log_message(self, format, *args):
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


def response(content):
    return 200, {"choices": [{"message": {"content": json.dumps(content)}}]}


@pytest.fixture
def repository(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "greeting.py").write_text(
        "def greeting(name):\n    return name\n"
    )
    (tmp_path / "tests" / "test_greeting.py").write_text(
        "from src.greeting import greeting\n\ndef test_greeting():\n"
        "    assert greeting('Ada') == 'Ada'\n"
    )
    return LocalRepositoryTools(tmp_path)


def test_records_model_usage_and_latency():
    server = ResponseServer(
        [
            (
                200,
                {
                    "choices": [{"message": {"content": json.dumps({"text": "ok"})}}],
                    "usage": {
                        "prompt_tokens": 17,
                        "completion_tokens": 4,
                        "total_tokens": 21,
                    },
                },
            )
        ]
    )
    try:
        driver = LlamaCppModelDriver(endpoint=server.endpoint)

        driver._complete("locate", {"task": "test"}, {"type": "object"})

        call = driver.calls[0]
        assert call.operation == "locate"
        assert call.prompt_tokens == 17
        assert call.completion_tokens == 4
        assert call.total_tokens == 21
        assert call.duration_seconds >= 0
        assert call.succeeded
    finally:
        server.close()


def test_decompose_uses_openai_compatible_schema_constrained_request():
    server = ResponseServer(
        [response(
            {
                "subtasks": [
                    {
                        "id": "ST-001",
                        "objective": "preserve greeting",
                        "acceptance_criteria": ["name is returned"],
                        "constraints": [],
                        "depends_on": [],
                        "expected_scope": {
                            "max_files": 2,
                            "max_changed_lines": 30,
                            "allow_dependencies": False,
                            "allow_public_api": False,
                            "allow_schema_changes": False,
                            "planned_paths": [],
                        },
                    }
                ]
            }
        )]
    )
    try:
        driver = LlamaCppModelDriver(endpoint=server.endpoint, model="test-model")

        result = driver.decompose(Task("preserve greeting"), repository_tools())

        assert json.loads(result)["subtasks"][0]["id"] == "ST-001"
        path, request = server.requests[0]
        assert path == "/v1/chat/completions"
        assert request["model"] == "test-model"
        assert request["response_format"]["type"] == "json_schema"
        assert request["response_format"]["json_schema"]["strict"] is True
        schema = request["response_format"]["json_schema"]["schema"]
        assert schema["properties"]["subtasks"]["items"]["properties"]["id"]["minLength"] == 1
        assert request["messages"][0]["role"] == "system"
        assert "repository_context" in request["messages"][1]["content"]
    finally:
        server.close()


def test_decomposition_review_requests_no_change_evidence_schema(repository):
    server = ResponseServer(
        [
            response(
                {
                    "accepted": True,
                    "findings": [],
                    "already_satisfied": True,
                    "evidence": ["existing test covers the criterion"],
                    "test_target": {
                        "paths": ["tests/test_greeting.py"],
                        "selectors": ["test_greeting"],
                    },
                }
            )
        ]
    )
    try:
        driver = LlamaCppModelDriver(endpoint=server.endpoint)

        driver.review_decomposition(Task("preserve greeting"), (), repository)

        request = server.requests[0][1]
        schema = request["response_format"]["json_schema"]["schema"]
        assert "already_satisfied" in schema["required"]
        assert "evidence" in schema["required"]
        assert "test_target" in schema["required"]
        assert "existing tests" in request["messages"][1]["content"]
        assert "missing implementation" in request["messages"][1]["content"]
    finally:
        server.close()


def repository_tools():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    return LocalRepositoryTools(root)


def test_test_module_generation_returns_code_and_leaves_filename_to_harness(repository):
    server = ResponseServer([response({"code": "def test_greeting():\\n    assert True\\n"})])
    try:
        driver = LlamaCppModelDriver(endpoint=server.endpoint)

        code = driver.create_test_module(
            SubTask("ST-001", "preserve greeting", acceptance_criteria=("returns name",)),
            "plan",
            repository,
        )

        assert code.startswith("def test_greeting")
        request = server.requests[0][1]
        assert request["response_format"]["json_schema"]["name"] == "write_test"
        payload = json.loads(request["messages"][1]["content"])
        assert "harness chooses a new filename" in payload["instructions"]
        assert "do not invent" in payload["instructions"]
        assert "AttributeError failures are invalid" in payload["instructions"]
        assert "callable(getattr" in payload["instructions"]
    finally:
        server.close()


def test_test_module_revision_receives_invalid_red_diagnostics(repository):
    server = ResponseServer([response({"code": "def test_greeting():\\n    assert True\\n"})])
    try:
        driver = LlamaCppModelDriver(endpoint=server.endpoint)

        code = driver.revise_test_module(
            SubTask("ST-001", "preserve greeting", acceptance_criteria=("returns name",)),
            "plan",
            repository,
            "from codemill.context import missing_api",
            ("ImportError: cannot import name 'missing_api'",),
        )

        assert code.startswith("def test_greeting")
        request = server.requests[0][1]
        assert request["response_format"]["json_schema"]["name"] == "revise_test"
        payload = json.loads(request["messages"][1]["content"])
        assert "missing_api" in payload["rejected_module"]
        assert "ImportError" in payload["diagnostics"][0]
        assert "Do not weaken" in payload["instructions"]
        assert "AttributeError failures are invalid" in payload["instructions"]
        assert "callable(getattr" in payload["instructions"]
    finally:
        server.close()


def test_test_patch_uses_test_stage_context_and_returns_patch(repository):
    server = ResponseServer([response({"patch": "diff --git a/tests/test_greeting.py b/tests/test_greeting.py"})])
    try:
        driver = LlamaCppModelDriver(endpoint=server.endpoint)

        patch = driver.create_test_patch(
            SubTask(
                "ST-001",
                "preserve greeting",
                acceptance_criteria=("name is returned",),
            ),
            "plan",
            repository,
        )

        assert patch.startswith("diff --git")
        request = server.requests[0][1]
        assert "test context" in request["messages"][1]["content"]
        assert "test_greeting" in request["messages"][1]["content"]
        assert "behavioral_interface" in request["messages"][1]["content"]
    finally:
        server.close()


def test_revises_rejected_test_patch_with_existing_file_diagnostic(repository):
    server = ResponseServer([response({"patch": "diff --git a/tests/test_new.py b/tests/test_new.py"})])
    try:
        driver = LlamaCppModelDriver(endpoint=server.endpoint)

        patch = driver.revise_test_patch(
            SubTask("ST-001", "preserve greeting", acceptance_criteria=("returns name",)),
            "plan",
            repository,
            "patch to existing test",
            ("test patch may not modify a pre-existing test file",),
        )

        assert patch.startswith("diff --git")
        request = server.requests[0][1]
        assert request["response_format"]["json_schema"]["name"] == "revise_test"
        payload = json.loads(request["messages"][1]["content"])
        assert payload["rejected_patch"] == "patch to existing test"
        assert "does not already exist" in payload["instructions"]
    finally:
        server.close()


def test_locate_uses_structural_repository_context(repository):
    server = ResponseServer([response({"text": "Implement greeting in src/greeting.py."})])
    try:
        driver = LlamaCppModelDriver(endpoint=server.endpoint)

        plan = driver.locate_and_plan(
            SubTask("ST-001", "preserve greeting", acceptance_criteria=("greeting returns input",)),
            repository,
        )

        assert "src/greeting.py" in plan
        request = server.requests[0][1]
        assert request["response_format"]["json_schema"]["name"] == "locate"
        assert "candidate_definition" in request["messages"][1]["content"]
    finally:
        server.close()


def test_decomposition_review_includes_task_level_implementation_evidence(repository):
    (repository.root / "codemill").mkdir()
    (repository.root / "codemill" / "harness.py").write_text(
        "class CodingHarness:\n    def _run_subtask(self):\n        return 'discard test'\n"
    )
    server = ResponseServer(
        [
            response(
                {
                    "accepted": True,
                    "findings": [],
                    "already_satisfied": False,
                    "evidence": [],
                    "test_target": {"paths": [], "selectors": []},
                }
            )
        ]
    )
    try:
        driver = LlamaCppModelDriver(endpoint=server.endpoint)

        driver.review_decomposition(
            Task(
                "Update CodingHarness._run_subtask in codemill/harness.py.",
                ("Discard rejected focused tests.",),
            ),
            (SubTask("ST-001", "Handle failed focused verification"),),
            repository,
        )

        request = server.requests[0][1]
        payload = json.loads(request["messages"][1]["content"])
        assert "return 'discard test'" in payload["evidence_context"][0]["locate_context"]
    finally:
        server.close()


def test_implementation_call_uses_red_diagnostics_and_accepted_test(repository):
    server = ResponseServer([response({"patch": "diff --git a/src/greeting.py b/src/greeting.py"})])
    try:
        driver = LlamaCppModelDriver(endpoint=server.endpoint)

        patch = driver.create_patch(
            SubTask("ST-001", "preserve greeting", acceptance_criteria=("returns name",)),
            "plan",
            repository,
            VerificationTarget(("tests/test_greeting.py",)),
            ("AssertionError: expected greeting",),
        )

        assert patch.startswith("diff --git")
        content = server.requests[0][1]["messages"][1]["content"]
        assert "implementation context" in content
        assert "AssertionError: expected greeting" in content
        assert "test_greeting.py" in content
    finally:
        server.close()


def test_review_operations_use_review_schema(repository):
    server = ResponseServer([response({"accepted": True, "findings": []})])
    try:
        driver = LlamaCppModelDriver(endpoint=server.endpoint)

        result = driver.review_decomposition(
            Task("preserve greeting"),
            (SubTask("ST-001", "preserve greeting", acceptance_criteria=("returns input",)),),
            repository,
        )

        assert json.loads(result)["accepted"] is True
        assert server.requests[0][1]["response_format"]["json_schema"]["name"] == "review_decomposition"
    finally:
        server.close()


def test_repair_call_uses_failure_diagnostics(repository):
    server = ResponseServer([response({"patch": "diff --git a/src/greeting.py b/src/greeting.py"})])
    try:
        driver = LlamaCppModelDriver(endpoint=server.endpoint)

        patch = driver.repair_patch(
            SubTask("ST-001", "preserve greeting", acceptance_criteria=("returns input",)),
            ("TypeError: input was None",),
            repository,
            VerificationTarget(("tests/test_greeting.py",)),
        )

        assert patch.startswith("diff --git")
        content = server.requests[0][1]["messages"][1]["content"]
        assert "TypeError: input was None" in content
        assert server.requests[0][1]["response_format"]["json_schema"]["name"] == "repair"
    finally:
        server.close()


def test_implementation_review_includes_accepted_test(repository):
    server = ResponseServer([response({"accepted": True, "findings": []})])
    try:
        driver = LlamaCppModelDriver(endpoint=server.endpoint)

        result = driver.review_implementation(
            SubTask("ST-001", "preserve greeting", acceptance_criteria=("returns input",)),
            "diff --git a/src/greeting.py b/src/greeting.py",
            repository,
            VerificationTarget(("tests/test_greeting.py",)),
        )

        assert json.loads(result)["accepted"] is True
        content = server.requests[0][1]["messages"][1]["content"]
        assert "accepted_test" in content
        assert "diff --git" in content
    finally:
        server.close()


def test_retries_transient_server_errors():
    server = ResponseServer(
        [
            (503, {"error": "busy"}),
            response(
                {
                    "subtasks": [
                        {
                            "id": "ST-001",
                            "objective": "fix",
                            "acceptance_criteria": ["works"],
                            "constraints": [],
                            "depends_on": [],
                            "expected_scope": {
                                "max_files": 2,
                                "max_changed_lines": 30,
                                "allow_dependencies": False,
                                "allow_public_api": False,
                                "allow_schema_changes": False,
                                "planned_paths": [],
                            },
                        }
                    ]
                }
            ),
        ]
    )
    try:
        driver = LlamaCppModelDriver(endpoint=server.endpoint, retries=1)

        assert json.loads(driver.decompose(Task("fix"), repository_tools()))["subtasks"]
        assert len(server.requests) == 2
    finally:
        server.close()


def test_reports_model_refusal():
    server = ResponseServer(
        [(200, {"choices": [{"message": {"refusal": "cannot comply", "content": None}}]})]
    )
    try:
        driver = LlamaCppModelDriver(endpoint=server.endpoint, retries=0)

        with pytest.raises(LlamaServerError, match="model refused operation"):
            driver.decompose(Task("task"), repository_tools())
    finally:
        server.close()


def test_reports_malformed_model_response():
    server = ResponseServer([(200, {"choices": []})])
    try:
        driver = LlamaCppModelDriver(endpoint=server.endpoint, retries=0)

        with pytest.raises(LlamaServerError, match="malformed completion response"):
            driver.decompose(Task("task"), repository_tools())
        assert len(driver.calls) == 1
        assert not driver.calls[0].succeeded
    finally:
        server.close()
