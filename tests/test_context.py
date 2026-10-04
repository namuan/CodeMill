from codemill.context import ContextBuilder, RepositoryMap, summarize_repository
from codemill.models import SubTask, VerificationTarget
from codemill.repository_tools import LocalRepositoryTools


def test_summarizes_languages_roots_and_configuration(tmp_path):
    (tmp_path / "src" / "service").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "src" / "service" / "index.ts").write_text("export const value = 1\n")
    (tmp_path / "tests" / "test_service.py").write_text("def test_service(): pass\n")
    (tmp_path / "pyproject.toml").write_text("[project]\n")
    (tmp_path / "package.json").write_text("{}\n")
    tools = LocalRepositoryTools(tmp_path)

    summary = summarize_repository(tools)

    assert summary == RepositoryMap(
        languages=("Python", "TypeScript"),
        source_roots=("src",),
        test_roots=("tests",),
        configuration_files=("package.json", "pyproject.toml"),
        tree=("docs/", "package.json", "pyproject.toml", "src/", "src/service/", "src/service/index.ts", "tests/", "tests/test_service.py"),
    )


def test_builds_test_context_from_slice_and_related_tests(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "clamp.py").write_text(
        "def clamp(value, low, high):\n    return max(low, min(value, high))\n"
    )
    (tmp_path / "tests" / "test_clamp.py").write_text(
        "from src.clamp import clamp\n\ndef test_clamp():\n    assert clamp(12, 0, 10) == 10\n"
    )
    subtask = SubTask(
        "clamp-upper-bound",
        "Implement clamp behavior",
        acceptance_criteria=("values above high return high",),
    )
    pack = ContextBuilder(LocalRepositoryTools(tmp_path)).build_test_context(subtask)

    rendered = pack.render()

    assert "values above high return high" in rendered
    assert "test_clamp" in rendered
    assert "return max(low, min(value, high))" not in rendered
    assert pack.stage == "test"
    assert pack.char_count <= pack.char_budget
    assert all(fragment.source for fragment in pack.fragments)


def test_deduplicates_overlapping_test_context_ranges(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "bounds.py").write_text(
        "def clamp(value):\n    return value\n\ndef bound(value):\n    return value\n"
    )
    (tmp_path / "tests" / "test_bounds.py").write_text(
        "from src.bounds import bound, clamp\n\ndef test_bounds():\n"
        "    assert clamp(1) == 1\n    assert bound(2) == 2\n"
    )
    subtask = SubTask(
        "bounds",
        "Use clamp and bound behavior",
        acceptance_criteria=("clamp and bound preserve their inputs",),
    )
    pack = ContextBuilder(LocalRepositoryTools(tmp_path)).build_test_context(subtask)

    test_fragments = [fragment for fragment in pack.fragments if fragment.kind == "test_convention"]

    assert len(test_fragments) == 1
    assert set(test_fragments[0].symbols) == {"bound", "clamp"}
    assert "clamp(1)" in test_fragments[0].text
    assert "bound(2)" in test_fragments[0].text


def test_builds_red_driven_implementation_context(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "clamp.py").write_text(
        "def clamp(value, low, high):\n    return None\n"
    )
    (tmp_path / "tests" / "test_clamp.py").write_text(
        "from src.clamp import clamp\n\ndef test_clamp():\n    assert clamp(12, 0, 10) == 10\n"
    )
    subtask = SubTask(
        "clamp-upper-bound",
        "Implement clamp behavior",
        acceptance_criteria=("values above high return high",),
    )
    pack = ContextBuilder(LocalRepositoryTools(tmp_path)).build_implementation_context(
        subtask,
        VerificationTarget(("tests/test_clamp.py",)),
        ("AssertionError: expected 10, got None",),
    )

    rendered = pack.render()

    assert "AssertionError: expected 10, got None" in rendered
    assert "assert clamp(12, 0, 10) == 10" in rendered
    assert "def clamp(value, low, high):" in rendered
    assert pack.stage == "implementation"
    assert pack.char_count <= pack.char_budget


def test_rejects_budget_too_small_for_required_context(tmp_path):
    subtask = SubTask(
        "small",
        "Implement a behavior",
        acceptance_criteria=("the behavior is observable",),
    )

    try:
        ContextBuilder(LocalRepositoryTools(tmp_path)).build_test_context(
            subtask,
            char_budget=20,
        )
    except ValueError as error:
        assert "required context exceeds character budget" in str(error)
    else:
        raise AssertionError("undersized context budget was accepted")


def test_renders_compact_repository_map():
    summary = RepositoryMap(
        languages=("Python",),
        source_roots=("codemill",),
        test_roots=("tests",),
        configuration_files=("pyproject.toml",),
        tree=("codemill/", "tests/", "pyproject.toml"),
    )

    rendered = summary.render()

    assert "Languages: Python" in rendered
    assert "Source roots: codemill" in rendered
    assert "Test roots: tests" in rendered
    assert "Configuration: pyproject.toml" in rendered
    assert "Tree:\n- codemill/" in rendered
