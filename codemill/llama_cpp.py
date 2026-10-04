import json
import socket
import time
from dataclasses import asdict
from http.client import HTTPException
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .context import ContextBuilder, summarize_repository
from .decomposition import DECOMPOSITION_REVIEW_JSON_SCHEMA
from .models import InferenceMetrics, SubTask, Task, VerificationTarget
from .tools import CodingTools


DECOMPOSITION_SCHEMA = {
    "type": "object",
    "properties": {
        "subtasks": {
            "type": "array",
            "minItems": 0,
            "items": {
                "type": "object",
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
                        "required": [
                            "max_files",
                            "max_changed_lines",
                            "allow_dependencies",
                            "allow_public_api",
                            "allow_schema_changes",
                            "planned_paths",
                        ],
                        "additionalProperties": False,
                    },
                },
                "required": [
                    "id",
                    "objective",
                    "acceptance_criteria",
                    "constraints",
                    "depends_on",
                    "expected_scope",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["subtasks"],
    "additionalProperties": False,
}
REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "accepted": {"type": "boolean"},
        "findings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["accepted", "findings"],
    "additionalProperties": False,
}
TEXT_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
    "additionalProperties": False,
}
PATCH_SCHEMA = {
    "type": "object",
    "properties": {"patch": {"type": "string"}},
    "required": ["patch"],
    "additionalProperties": False,
}


class LlamaServerError(RuntimeError):
    pass


class LlamaCppModelDriver:
    def __init__(
        self,
        endpoint: str = "http://127.0.0.1:9090",
        model: str = "local-model",
        timeout: float = 120.0,
        retries: int = 2,
        max_tokens: int = 4096,
    ):
        if not endpoint.startswith(("http://", "https://")):
            raise ValueError("endpoint must be an HTTP or HTTPS URL")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if isinstance(retries, bool) or not isinstance(retries, int) or retries < 0:
            raise ValueError("retries must be a non-negative integer")
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 1:
            raise ValueError("max_tokens must be a positive integer")
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.retries = retries
        self.max_tokens = max_tokens
        self.calls: list[InferenceMetrics] = []

    def decompose(self, task: Task, tools: CodingTools) -> str:
        result = self._complete(
            "decompose",
            {
                "task": asdict(task),
                "repository_context": summarize_repository(tools).render(),
                "instructions": (
                    "Create the smallest independently verifiable vertical slices for behavior "
                    "that is not already satisfied. Return an empty subtasks array only if the "
                    "task is already satisfied; the independent review will require evidence and "
                    "a runnable existing test target before accepting that decision. Do not make "
                    "test-writing a subtask because the harness creates tests; every non-empty "
                    "slice must include production behavior. Give every slice a non-empty stable "
                    "ID such as ST-001 and a non-empty objective. "
                    "Include at least one observable acceptance criterion, constraints, only "
                    "necessary dependencies, and a conservative expected scope. Include both "
                    "planned production paths in planned_paths; the harness creates the focused "
                    "test file separately. Subtask file and line budgets apply to production edits, "
                    "while the user's task scope bounds total test and production changes. Set "
                    "scope permissions false unless the task requires them."
                ),
            },
            DECOMPOSITION_SCHEMA,
        )
        return json.dumps(result)

    def review_decomposition(
        self,
        task: Task,
        subtasks: tuple[SubTask, ...],
        tools: CodingTools,
    ) -> str:
        task_context = SubTask(
            "TASK-REVIEW",
            task.objective,
            task.acceptance_criteria,
            task.constraints,
            (),
            task.expected_scope,
        )
        context_tasks = (task_context, *subtasks[:3])
        evidence_context = [
            {
                "subtask_id": subtask.id,
                "locate_context": ContextBuilder(tools)
                .build_locate_context(subtask, char_budget=3500)
                .render(),
                "test_context": ContextBuilder(tools)
                .build_test_context(subtask, char_budget=3500)
                .render(),
            }
            for subtask in context_tasks[:4]
        ]
        result = self._complete(
            "review_decomposition",
            {
                "task": asdict(task),
                "subtasks": [asdict(subtask) for subtask in subtasks],
                "repository_context": summarize_repository(tools).render(),
                "evidence_context": evidence_context,
                "instructions": (
                    "Reject test-only or layer-oriented slices and bundled slices that are not "
                    "minimal, independently observable, or meaningfully verifiable. Tests are "
                    "created by the harness, so every implementation subtask must include "
                    "production behavior. Review the plan rather than require behavior to exist "
                    "already; a missing implementation or test is expected for non-empty plans "
                    "and is not by itself a reason to reject them. If subtasks are empty, accept "
                    "only when existing behavior already satisfies every task "
                    "criterion, provide specific evidence, and identify existing tests that "
                    "verify those criteria. For ordinary plans set already_satisfied false, "
                    "evidence empty, and test_target paths and selectors empty."
                ),
            },
            DECOMPOSITION_REVIEW_JSON_SCHEMA,
        )
        return json.dumps(result)

    def locate_and_plan(self, task: SubTask, tools: CodingTools) -> str:
        context = ContextBuilder(tools).build_locate_context(task)
        result = self._complete(
            "locate",
            {
                "subtask": asdict(task),
                "context": context.render(),
                "instructions": (
                    "Identify likely files and interfaces, then state the smallest behavior "
                    "slice, test target, constraints, and needed context. Do not mutate files."
                ),
            },
            TEXT_SCHEMA,
        )
        return result["text"]

    def create_test_patch(self, task: SubTask, plan: str, tools: CodingTools) -> str:
        context = ContextBuilder(tools).build_test_context(task)
        result = self._complete(
            "write_test",
            {
                "subtask": asdict(task),
                "plan": plan,
                "context": context.render(),
                "instructions": (
                    "Return the smallest syntactically valid git-apply-compatible unified diff "
                    "that adds a focused behavioral test. For a new file include `diff --git`, "
                    "`new file mode 100644`, `--- /dev/null`, the matching `+++ b/path`, and "
                    "an @@ hunk whose line counts exactly match its added lines. Add a new "
                    "test file and never modify a pre-existing test file. Return no markdown or "
                    "explanation, and do not change production files."
                ),
            },
            PATCH_SCHEMA,
        )
        return result["patch"]

    def revise_test_patch(
        self,
        task: SubTask,
        plan: str,
        tools: CodingTools,
        rejected_patch: str,
        diagnostics: tuple[str, ...],
    ) -> str:
        context = ContextBuilder(tools).build_test_context(task)
        result = self._complete(
            "revise_test",
            {
                "subtask": asdict(task),
                "plan": plan,
                "context": context.render(),
                "rejected_patch": rejected_patch,
                "diagnostics": diagnostics,
                "instructions": (
                    "Replace the rejected patch with a valid git-apply-compatible diff that "
                    "adds a new focused test file at a path that does not already exist. "
                    "Do not modify, delete, or rewrite any existing test file or production file. "
                    "Use exact unified-diff hunk counts and return no markdown or explanation."
                ),
            },
            PATCH_SCHEMA,
        )
        return result["patch"]

    def create_patch(
        self,
        task: SubTask,
        plan: str,
        tools: CodingTools,
        test_target: VerificationTarget,
        red_diagnostics: tuple[str, ...],
    ) -> str:
        context = ContextBuilder(tools).build_implementation_context(
            task,
            test_target,
            red_diagnostics,
        )
        result = self._complete(
            "implement",
            {
                "subtask": asdict(task),
                "plan": plan,
                "context": context.render(),
                "instructions": (
                    "Return the smallest unified diff that makes the accepted failing test pass. "
                    "Change production code only; preserve the accepted test and avoid unrelated work."
                ),
            },
            PATCH_SCHEMA,
        )
        return result["patch"]

    def review_implementation(
        self,
        task: SubTask,
        diff: str,
        tools: CodingTools,
        test_target: VerificationTarget,
    ) -> str:
        context = ContextBuilder(tools).build_implementation_context(task, test_target, ())
        result = self._complete(
            "review_implementation",
            {
                "subtask": asdict(task),
                "diff": diff,
                "context": context.render(),
                "instructions": (
                    "Accept only changes justified by the slice and behavioral tests. Reject "
                    "unnecessary abstractions, unrelated refactors, extra APIs, and unsupported behavior."
                ),
            },
            REVIEW_SCHEMA,
        )
        return json.dumps(result)

    def repair_patch(
        self,
        task: SubTask,
        diagnostics: tuple[str, ...],
        tools: CodingTools,
        test_target: VerificationTarget,
    ) -> str:
        context = ContextBuilder(tools).build_implementation_context(
            task,
            test_target,
            diagnostics,
        )
        result = self._complete(
            "repair",
            {
                "subtask": asdict(task),
                "diagnostics": diagnostics,
                "context": context.render(),
                "instructions": (
                    "Return only a minimal production-code unified diff that repairs the reported "
                    "failure. Do not modify the accepted test or unrelated files."
                ),
            },
            PATCH_SCHEMA,
        )
        return result["patch"]

    def _complete(
        self,
        operation: str,
        payload: dict[str, Any],
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        started = time.monotonic()
        try:
            result, prompt_tokens, completion_tokens, total_tokens = self._request(
                operation,
                payload,
                schema,
            )
        except Exception as error:
            self.calls.append(
                InferenceMetrics(
                    operation,
                    time.monotonic() - started,
                    succeeded=False,
                    error=f"{type(error).__name__}: {error}",
                )
            )
            raise
        self.calls.append(
            InferenceMetrics(
                operation,
                time.monotonic() - started,
                prompt_tokens,
                completion_tokens,
                total_tokens,
            )
        )
        return result

    def _request(
        self,
        operation: str,
        payload: dict[str, Any],
        schema: dict[str, Any],
    ) -> tuple[dict[str, Any], int | None, int | None, int | None]:
        body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are an operation-specific coding agent. Use only the supplied "
                            "repository evidence. Respect harness constraints and return exactly "
                            "the requested schema. Never claim tests passed or patches were applied."
                        ),
                    },
                    {"role": "user", "content": json.dumps(payload)},
                ],
                "temperature": 0.1,
                "max_tokens": self.max_tokens,
                "stream": False,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": operation,
                        "strict": True,
                        "schema": schema,
                    },
                },
            }
        ).encode()
        request = Request(
            f"{self.endpoint}/v1/chat/completions",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        for attempt in range(self.retries + 1):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    response_body = response.read().decode("utf-8")
                return self._parse_completion(response_body)
            except HTTPError as error:
                details = error.read().decode("utf-8", errors="replace")[:1000]
                if error.code >= 500 and attempt < self.retries:
                    time.sleep(0.1 * (2**attempt))
                    continue
                raise LlamaServerError(f"llama-server returned HTTP {error.code}: {details}") from error
            except (URLError, TimeoutError, socket.timeout, OSError, HTTPException) as error:
                if attempt < self.retries:
                    time.sleep(0.1 * (2**attempt))
                    continue
                raise LlamaServerError(f"llama-server request failed: {error}") from error
        raise LlamaServerError("llama-server request exhausted retries")

    @staticmethod
    def _parse_completion(
        response_body: str,
    ) -> tuple[dict[str, Any], int | None, int | None, int | None]:
        try:
            response = json.loads(response_body)
            message = response["choices"][0]["message"]
            refusal = message.get("refusal")
            if refusal:
                raise LlamaServerError(f"model refused operation: {refusal}")
            content = message["content"]
            if not isinstance(content, str):
                raise ValueError("completion content is not a string")
            parsed = json.loads(content)
            if not isinstance(parsed, dict):
                raise ValueError("completion content is not a JSON object")
            usage = response.get("usage", {})
            if not isinstance(usage, dict):
                usage = {}
            prompt_tokens = LlamaCppModelDriver._valid_token_count(usage.get("prompt_tokens"))
            completion_tokens = LlamaCppModelDriver._valid_token_count(
                usage.get("completion_tokens")
            )
            total_tokens = LlamaCppModelDriver._valid_token_count(usage.get("total_tokens"))
            if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
                total_tokens = prompt_tokens + completion_tokens
            return parsed, prompt_tokens, completion_tokens, total_tokens
        except LlamaServerError:
            raise
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise LlamaServerError("malformed completion response") from error

    @staticmethod
    def _valid_token_count(value: Any) -> int | None:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        return value
