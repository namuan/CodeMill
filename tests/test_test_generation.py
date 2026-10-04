import pytest

from codemill.models import SubTask
from codemill.repository_tools import LocalRepositoryTools
from codemill.test_generation import build_test_file_patch, prepare_test_module


def test_adds_requested_api_guards_and_missing_pytest_import():
    task = SubTask("ST-001", "Implement LocalRepositoryTools.git_status()")
    source = (
        "from codemill.repository_tools import LocalRepositoryTools\n\n"
        "def test_status(tmp_path):\n"
        "    tools = LocalRepositoryTools(tmp_path)\n"
        "    with pytest.raises(ValueError):\n"
        "        tools.git_status()\n"
    )

    prepared, guarded_symbols = prepare_test_module(source, task)

    assert "import pytest" in prepared
    assert "assert callable(getattr(tools, 'git_status', None))" in prepared
    assert prepared.index("assert callable(getattr") < prepared.index("with pytest.raises")
    assert guarded_symbols == ("LocalRepositoryTools.git_status",)


def test_replaces_nonliteral_messages_on_requested_api_guards():
    task = SubTask("ST-001", "Implement LocalRepositoryTools.git_status()")
    source = (
        "def test_status():\n"
        "    tools = LocalRepositoryTools('repo')\n"
        "    assert callable(getattr(tools, 'git_status', None)), LocalRepositoryTools.git_status is missing\n"
        "    tools.git_status()\n"
    )

    prepared, guarded_symbols = prepare_test_module(source, task)

    assert "assert callable(getattr(tools, 'git_status', None)), 'LocalRepositoryTools.git_status is missing'" in prepared
    assert guarded_symbols == ("LocalRepositoryTools.git_status",)


def test_resolves_class_from_explicit_source_path(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "tools.py").write_text(
        "class LocalRepositoryTools:\n    def search_text(self, query):\n        return query\n"
    )
    tools = LocalRepositoryTools(tmp_path)
    task = SubTask("ST-001", "Implement git_status() in src/tools.py")
    source = (
        "from src.tools import LocalRepositoryTools\n\n"
        "def test_status(tmp_path):\n"
        "    tools = LocalRepositoryTools()\n"
        "    tools.git_status()\n"
    )

    prepared, guarded_symbols = prepare_test_module(source, task, tools)

    assert "assert callable(getattr(tools, 'git_status', None))" in prepared
    assert guarded_symbols == ("LocalRepositoryTools.git_status",)


def test_does_not_inject_guards_for_unmentioned_methods():
    task = SubTask("ST-001", "Implement LocalRepositoryTools.git_status()")
    source = "def test_status():\n    assert True\n"

    prepared, guarded_symbols = prepare_test_module(source, task)

    assert prepared == source
    assert guarded_symbols == ()


def test_builds_a_new_test_file_patch_at_a_harness_selected_path(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_existing.py").write_text("def test_existing():\n    assert True\n")
    tools = LocalRepositoryTools(tmp_path)

    patch = build_test_file_patch(
        "from package import value\n\ndef test_value():\n    assert value() == 1\n",
        "ST-001",
        tools,
    )

    assert "diff --git a/tests/test_codemill_st_001.py b/tests/test_codemill_st_001.py" in patch
    assert "new file mode 100644" in patch
    assert "--- /dev/null" in patch
    assert "+++ b/tests/test_codemill_st_001.py" in patch
    assert "+def test_value():" in patch


def test_avoids_existing_harness_generated_test_path(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_codemill_st_001.py").write_text("def test_old(): pass\n")
    tools = LocalRepositoryTools(tmp_path)

    patch = build_test_file_patch("def test_value():\n    assert True\n", "ST-001", tools)

    assert "tests/test_codemill_st_001_2.py" in patch


@pytest.mark.parametrize(
    "source",
    ("", "value = 1\n", "def test_broken(:\n    pass\n"),
)
def test_rejects_empty_invalid_or_non_test_modules(tmp_path, source):
    (tmp_path / "tests").mkdir()
    tools = LocalRepositoryTools(tmp_path)

    with pytest.raises(ValueError):
        build_test_file_patch(source, "ST-001", tools)
