import json
import subprocess

import pytest

from codemill.benchmark import BenchmarkDatasetError, load_benchmark_cases


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


def case_record(case_id, repository, revision):
    return {
        "id": case_id,
        "repository": repository,
        "base_revision": revision,
        "task": {
            "objective": "Return a stable greeting",
            "acceptance_criteria": ["greeting('Ada') returns 'Hello, Ada!'"],
            "constraints": ["Use the standard library"],
        },
    }


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


def test_rejects_repository_at_a_different_base_revision(tmp_path):
    revision = create_repository(tmp_path / "fixture")
    dataset = tmp_path / "cases.jsonl"
    write_case_file(dataset, [case_record("wrong-base", "fixture", "0" * 40)])

    with pytest.raises(BenchmarkDatasetError, match="does not match base_revision"):
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
