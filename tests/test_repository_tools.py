import json

import pytest

from codemill.repository_tools import LocalRepositoryTools


def test_lists_repository_tree_to_requested_depth(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "src" / "module.py").write_text("value = 1\n")
    (tmp_path / "README.md").write_text("project\n")
    tools = LocalRepositoryTools(tmp_path)

    tree = tools.list_tree(".", depth=2)

    assert tree == ("docs/", "README.md", "src/", "src/module.py")


def test_rejects_invalid_tree_depth(tmp_path):
    tools = LocalRepositoryTools(tmp_path)

    with pytest.raises(ValueError, match="depth must be a non-negative integer"):
        tools.list_tree(".", depth=-1)


def test_reads_file_ranges_relative_to_repository_root(tmp_path):
    (tmp_path / "module.py").write_text("first\nsecond\nthird\n")
    tools = LocalRepositoryTools(tmp_path)

    assert tools.read_file("module.py", 2, 3) == "second\nthird\n"


def test_rejects_paths_outside_repository_root(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret")
    tools = LocalRepositoryTools(tmp_path)

    with pytest.raises(ValueError, match="path escapes repository root"):
        tools.read_file("../outside.txt")


def test_rejects_symlinks_that_escape_repository_root(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret")
    (tmp_path / "linked.txt").symlink_to(outside)
    tools = LocalRepositoryTools(tmp_path)

    with pytest.raises(ValueError, match="path escapes repository root"):
        tools.read_file("linked.txt")


def test_rejects_directories_and_missing_files(tmp_path):
    tools = LocalRepositoryTools(tmp_path)
    (tmp_path / "folder").mkdir()

    with pytest.raises(ValueError, match="not a regular file"):
        tools.read_file("folder")
    with pytest.raises(ValueError, match="does not exist"):
        tools.read_file("missing.py")


def test_search_text_uses_ripgrep_with_repository_relative_results(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "module.py").write_text("needle = 1\nother = 2\n")
    tools = LocalRepositoryTools(tmp_path)

    result = tools.search_text("needle")

    assert "src/module.py:1:needle = 1" in result


def test_finds_python_definitions_with_ast_grep(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "module.py").write_text(
        "class Cart:\n    def total(self):\n        return 0\n"
    )
    tools = LocalRepositoryTools(tmp_path)

    matches = json.loads(tools.find_definitions("total"))

    assert len(matches) == 1
    assert matches[0]["path"] == "src/module.py"
    assert matches[0]["name"] == "total"
    assert matches[0]["kind"] == "method"
    assert matches[0]["line"] == 2


def test_finds_ast_structural_patterns(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "cart.py").write_text(
        "class Cart:\n    def total(self):\n        return self.amount\n"
    )
    tools = LocalRepositoryTools(tmp_path)

    matches = json.loads(tools.find_structural("self.amount"))

    assert len(matches) == 1
    assert matches[0]["path"] == "src/cart.py"
    assert matches[0]["text"] == "self.amount"
    assert matches[0]["start_line"] == 3


def test_rejects_empty_structural_patterns(tmp_path):
    tools = LocalRepositoryTools(tmp_path)

    with pytest.raises(ValueError, match="pattern must not be empty"):
        tools.find_structural("  ")


def test_rejects_empty_definition_names(tmp_path):
    tools = LocalRepositoryTools(tmp_path)

    with pytest.raises(ValueError, match="name must not be empty"):
        tools.find_definitions("  ")


def test_rejects_empty_text_queries(tmp_path):
    tools = LocalRepositoryTools(tmp_path)

    with pytest.raises(ValueError, match="query must not be empty"):
        tools.search_text("  ")
