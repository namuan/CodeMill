import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import ExpectedScope, Task


class BenchmarkDatasetError(ValueError):
    pass


@dataclass(frozen=True)
class BenchmarkCase:
    id: str
    repository: Path
    base_revision: str
    task: Task
    reference_revision: str | None = None


def load_benchmark_cases(
    path: str | Path,
    repository_root: str | Path | None = None,
) -> tuple[BenchmarkCase, ...]:
    dataset_path = Path(path).resolve(strict=True)
    if not dataset_path.is_file():
        raise BenchmarkDatasetError("benchmark dataset must be a file")
    root = (
        Path(repository_root).resolve(strict=True)
        if repository_root is not None
        else dataset_path.parent.resolve()
    )
    cases = []
    identifiers = set()
    for line_number, line in enumerate(dataset_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            case = _parse_case(record, root, line_number)
        except (json.JSONDecodeError, TypeError, KeyError, ValueError) as error:
            if isinstance(error, BenchmarkDatasetError):
                raise
            raise BenchmarkDatasetError(f"invalid benchmark case on line {line_number}: {error}") from error
        if case.id in identifiers:
            raise BenchmarkDatasetError(f"duplicate benchmark case id: {case.id}")
        identifiers.add(case.id)
        cases.append(case)
    if not cases:
        raise BenchmarkDatasetError("benchmark dataset contains no cases")
    return tuple(cases)


def _parse_case(record: Any, root: Path, line_number: int) -> BenchmarkCase:
    if not isinstance(record, dict):
        raise BenchmarkDatasetError(f"benchmark case on line {line_number} must be an object")
    _reject_unknown(
        record,
        {"id", "repository", "base_revision", "reference_revision", "task"},
        "benchmark case",
    )
    identifier = _nonempty_string(record.get("id"), "case id")
    repository_value = _nonempty_string(record.get("repository"), "repository")
    relative_repository = Path(repository_value)
    if relative_repository.is_absolute() or ".." in relative_repository.parts:
        raise BenchmarkDatasetError("repository path escapes dataset root")
    repository = (root / relative_repository).resolve(strict=False)
    try:
        repository.relative_to(root)
    except ValueError as error:
        raise BenchmarkDatasetError("repository path escapes dataset root") from error
    if not repository.is_dir():
        raise BenchmarkDatasetError(f"repository does not exist: {repository_value}")

    revision = _nonempty_string(record.get("base_revision"), "base_revision")
    if not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", revision):
        raise BenchmarkDatasetError("base_revision must be a full commit SHA")
    verify_benchmark_checkout(repository, revision)
    reference_revision = record.get("reference_revision")
    if reference_revision is not None:
        reference_revision = _nonempty_string(reference_revision, "reference_revision")
        if not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", reference_revision):
            raise BenchmarkDatasetError("reference_revision must be a full commit SHA")
        _verify_commit_available(repository, reference_revision, "reference_revision")

    task_value = record.get("task")
    if not isinstance(task_value, dict):
        raise BenchmarkDatasetError("task must be an object")
    _reject_unknown(task_value, {"objective", "acceptance_criteria", "constraints"}, "task")
    objective = _nonempty_string(task_value.get("objective"), "task objective")
    criteria = _string_array(task_value.get("acceptance_criteria"), "acceptance_criteria")
    if not criteria:
        raise BenchmarkDatasetError("acceptance_criteria must not be empty")
    constraints = _string_array(task_value.get("constraints", []), "constraints")
    return BenchmarkCase(
        identifier,
        repository,
        revision,
        Task(objective, criteria, constraints, ExpectedScope()),
        reference_revision,
    )


def verify_benchmark_checkout(repository: Path, revision: str) -> None:
    _verify_commit_available(repository, revision, "base_revision")
    git_path = shutil.which("git")
    if git_path is None:
        raise BenchmarkDatasetError("git executable is required to validate benchmark repositories")
    status = subprocess.run(
        [git_path, "-C", str(repository), "status", "--porcelain", "--untracked-files=all"],
        check=False,
        capture_output=True,
        text=True,
    )
    if status.returncode != 0:
        raise BenchmarkDatasetError("could not inspect benchmark repository status")
    if status.stdout.strip():
        raise BenchmarkDatasetError("benchmark repository must be clean")


def _verify_commit_available(repository: Path, revision: str, field: str) -> None:
    git_path = shutil.which("git")
    if git_path is None:
        raise BenchmarkDatasetError("git executable is required to validate benchmark repositories")
    result = subprocess.run(
        [git_path, "-C", str(repository), "cat-file", "-e", f"{revision}^{{commit}}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise BenchmarkDatasetError(f"benchmark {field} is unavailable in repository")


def _reject_unknown(value: dict[str, Any], allowed: set[str], description: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise BenchmarkDatasetError(f"{description} has unknown field: {unknown[0]}")


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkDatasetError(f"{field} must be a non-empty string")
    return value.strip()


def _string_array(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise BenchmarkDatasetError(f"{field} must be an array of strings")
    return tuple(_nonempty_string(item, field) for item in value)
