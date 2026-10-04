import json
import subprocess
from pathlib import Path

import pytest

from codemill.benchmark import BenchmarkDatasetError, load_benchmark_cases
from codemill.models import ExpectedScope


def create_repository(path):
    path.mkdir()
    (path / "sample.py").write_text("value = 1\n")
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "tests@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "CodeMill Tests"], check=True)
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "fixture"], check=True)
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def write_case_file(path, records):
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n")


def case_record(case_id, repository, revision, reference_revision=None):
    record = {
        "id": case_id,
        "repository": repository,
        "base_revision": revision,
        "task": {
            "objective": "Return a stable greeting",
            "acceptance_criteria": ["greeting('Ada') returns 'Hello, Ada!'"],
            "constraints": ["Use the standard library"],
        },
    }
    if reference_revision is not None:
        record["reference_revision"] = reference_revision
    return record


def test_curated_dataset_contains_pinned_historical_task_cases():
    dataset = Path(__file__).resolve().parents[1] / "benchmarks" / "cases.jsonl"
    records = [json.loads(line) for line in dataset.read_text().splitlines() if line.strip()]

    assert {record["id"] for record in records} == {
        "context-overlap-dedup-001",
        "git-status-001",
        "discard-invalid-red-test-001",
    }
    assert all(len(record["base_revision"]) == 40 for record in records)
    assert all(len(record["reference_revision"]) == 40 for record in records)
    assert all(record["task"]["acceptance_criteria"] for record in records)


def test_loads_reference_revision_for_patch_comparison(tmp_path):
    repository = tmp_path / "fixture"
    base_revision = create_repository(repository)
    (repository / "sample.py").write_text("value = 2\n")
    subprocess.run(["git", "-C", str(repository), "add", "sample.py"], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-qm", "reference"], check=True)
    reference_revision = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dataset = tmp_path / "cases.jsonl"
    write_case_file(
        dataset,
        [case_record("with-reference", "fixture", base_revision, reference_revision)],
    )

    case = load_benchmark_cases(dataset)[0]

    assert case.reference_revision == reference_revision


def test_rejects_unavailable_reference_revision(tmp_path):
    revision = create_repository(tmp_path / "fixture")
    dataset = tmp_path / "cases.jsonl"
    write_case_file(
        dataset,
        [case_record("missing-reference", "fixture", revision, "f" * 40)],
    )

    with pytest.raises(BenchmarkDatasetError, match="reference_revision is unavailable"):
        load_benchmark_cases(dataset)


def test_loads_repository_relative_to_explicit_dataset_root(tmp_path):
    revision = create_repository(tmp_path / "fixture")
    dataset_directory = tmp_path / "datasets"
    dataset_directory.mkdir()
    dataset = dataset_directory / "cases.jsonl"
    write_case_file(dataset, [case_record("rooted", "fixture", revision)])

    cases = load_benchmark_cases(dataset, repository_root=tmp_path)

    assert cases[0].repository == (tmp_path / "fixture").resolve()


def test_loads_case_specific_change_budgets(tmp_path):
    revision = create_repository(tmp_path / "fixture")
    record = case_record("scoped", "fixture", revision)
    record["task"]["expected_scope"] = {"max_files": 5, "max_changed_lines": 180}
    dataset = tmp_path / "cases.jsonl"
    write_case_file(dataset, [record])

    case = load_benchmark_cases(dataset)[0]

    assert case.task.expected_scope == ExpectedScope(max_files=5, max_changed_lines=180)


def test_rejects_invalid_case_specific_scope_budget(tmp_path):
    revision = create_repository(tmp_path / "fixture")
    record = case_record("bad-scope", "fixture", revision)
    record["task"]["expected_scope"] = {"max_changed_lines": -1}
    dataset = tmp_path / "cases.jsonl"
    write_case_file(dataset, [record])

    with pytest.raises(BenchmarkDatasetError, match="max_changed_lines must be a non-negative integer"):
        load_benchmark_cases(dataset)


def test_loads_repository_pinned_benchmark_case(tmp_path):
    revision = create_repository(tmp_path / "fixture")
    dataset = tmp_path / "cases.jsonl"
    write_case_file(dataset, [case_record("greeting-001", "fixture", revision)])

    cases = load_benchmark_cases(dataset)

    assert len(cases) == 1
    assert cases[0].id == "greeting-001"
    assert cases[0].repository == (tmp_path / "fixture").resolve()
    assert cases[0].base_revision == revision
    assert cases[0].task.objective == "Return a stable greeting"


def test_rejects_duplicate_case_ids(tmp_path):
    revision = create_repository(tmp_path / "fixture")
    record = case_record("duplicate", "fixture", revision)
    dataset = tmp_path / "cases.jsonl"
    write_case_file(dataset, [record, record])

    with pytest.raises(BenchmarkDatasetError, match="duplicate benchmark case id"):
        load_benchmark_cases(dataset)


def test_rejects_repository_path_traversal(tmp_path):
    revision = create_repository(tmp_path / "fixture")
    dataset = tmp_path / "cases.jsonl"
    write_case_file(dataset, [case_record("escape", "../outside", revision)])

    with pytest.raises(BenchmarkDatasetError, match="repository path escapes dataset root"):
        load_benchmark_cases(dataset)


def test_accepts_historical_base_revision_in_a_clean_repository(tmp_path):
    repository = tmp_path / "fixture"
    revision = create_repository(repository)
    (repository / "sample.py").write_text("value = 2\n")
    subprocess.run(["git", "-C", str(repository), "add", "sample.py"], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-qm", "advance"], check=True)
    dataset = tmp_path / "cases.jsonl"
    write_case_file(dataset, [case_record("historical", "fixture", revision)])

    cases = load_benchmark_cases(dataset)

    assert cases[0].base_revision == revision


def test_rejects_unavailable_base_revision(tmp_path):
    create_repository(tmp_path / "fixture")
    dataset = tmp_path / "cases.jsonl"
    write_case_file(dataset, [case_record("wrong-base", "fixture", "0" * 40)])

    with pytest.raises(BenchmarkDatasetError, match="base_revision is unavailable"):
        load_benchmark_cases(dataset)


def test_rejects_dirty_benchmark_repository(tmp_path):
    revision = create_repository(tmp_path / "fixture")
    (tmp_path / "fixture" / "untracked.txt").write_text("changed\n")
    dataset = tmp_path / "cases.jsonl"
    write_case_file(dataset, [case_record("dirty", "fixture", revision)])

    with pytest.raises(BenchmarkDatasetError, match="must be clean"):
        load_benchmark_cases(dataset)


def test_rejects_unpinned_revision_and_missing_acceptance_criteria(tmp_path):
    create_repository(tmp_path / "fixture")
    record = case_record("invalid", "fixture", "main")
    record["task"]["acceptance_criteria"] = []
    dataset = tmp_path / "cases.jsonl"
    write_case_file(dataset, [record])

    with pytest.raises(BenchmarkDatasetError, match="base_revision must be a full commit SHA"):
        load_benchmark_cases(dataset)
